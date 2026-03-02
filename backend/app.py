from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.pipeline import (
    DATA_DIR,
    answer_question,
    build_index,
    delete_paper,
    get_paper_details,
    get_summary,
    ingest_pdf,
    init_db,
    list_papers,
    summarize_paper,
)

load_dotenv()
init_db()

app = FastAPI(title="PaperQA", version="0.2.0")
frontend_origins = ["http://127.0.0.1:3000", "http://localhost:3000"]
extra_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "").split(",") if o.strip()]
if extra_origins:
    frontend_origins = sorted(set(frontend_origins + extra_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOB_STORE: dict[str, dict] = {}
JOB_LOCK = threading.Lock()


def _is_db_locked_error(err: Exception) -> bool:
    return "database is locked" in str(err).lower()


class IngestRequest(BaseModel):
    file_path: str
    extract_equations: bool = True
    eq_pages: Literal["methods_appendix", "all"] = "methods_appendix"


class QARequest(BaseModel):
    question: str
    top_k: int = Field(default=10, ge=1, le=20)


def _set_job(job_key: str, **updates: object) -> None:
    with JOB_LOCK:
        current = JOB_STORE.get(job_key, {})
        current.update(updates)
        JOB_STORE[job_key] = current


def _run_upload_job(job_id: str, tmp_path: Path, extract_equations: bool, eq_pages: str) -> None:
    try:
        _set_job(job_id, status="running", step="ingest", message="PDF ingest 중...")
        ingest_result = ingest_pdf(
            file_path=str(tmp_path),
            extract_equations=extract_equations,
            eq_pages=eq_pages,
        )
        paper_id = str(ingest_result["paper_id"])

        _set_job(job_id, step="summarize", paper_id=paper_id, message="한국어 요약 생성 중...")
        summarize_paper(paper_id)

        _set_job(job_id, step="build_index", message="QA 인덱스 생성 중...")
        build_index(paper_id)

        _set_job(
            job_id,
            status="completed",
            step="done",
            message="완료",
            paper_id=paper_id,
        )
    except Exception as e:
        if _is_db_locked_error(e):
            _set_job(
                job_id,
                status="failed",
                step="error",
                message="실패: DB가 사용 중입니다. 잠시 후 다시 시도해 주세요.",
                error="database is locked",
            )
            return
        _set_job(
            job_id,
            status="failed",
            step="error",
            message=f"실패: {e}",
            error=str(e),
        )
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/jobs/upload_and_process")
async def upload_and_process_job(
    file: UploadFile = File(...),
    extract_equations: bool = Form(True),
    eq_pages: Literal["methods_appendix", "all"] = Form("methods_appendix"),
) -> dict:
    name = Path(file.filename or "").name
    if not name:
        raise HTTPException(status_code=400, detail="업로드 파일 이름이 비어 있습니다.")
    if Path(name).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    tmp_dir = DATA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid4().hex}_{name}"
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="업로드된 파일 내용이 비어 있습니다.")
    tmp_path.write_bytes(content)

    job_id = uuid4().hex
    _set_job(
        job_id,
        job_id=job_id,
        status="queued",
        step="queued",
        message="대기 중...",
        paper_id=None,
        error="",
    )
    worker = threading.Thread(
        target=_run_upload_job,
        args=(job_id, tmp_path, extract_equations, eq_pages),
        daemon=True,
    )
    worker.start()
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with JOB_LOCK:
        row = JOB_STORE.get(job_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"job_id '{job_id}' not found.")
    return row


@app.post("/papers/upload")
async def upload_paper(
    file: UploadFile = File(...),
    extract_equations: bool = Form(True),
    eq_pages: Literal["methods_appendix", "all"] = Form("methods_appendix"),
) -> dict:
    name = Path(file.filename or "").name
    if not name:
        raise HTTPException(status_code=400, detail="업로드 파일 이름이 비어 있습니다.")
    if Path(name).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    tmp_dir = DATA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid4().hex}_{name}"
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="업로드된 파일 내용이 비어 있습니다.")
        tmp_path.write_bytes(content)
        return ingest_pdf(
            file_path=str(tmp_path),
            extract_equations=extract_equations,
            eq_pages=eq_pages,
        )
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except sqlite3.OperationalError as e:
        if _is_db_locked_error(e):
            raise HTTPException(
                status_code=503,
                detail="DB가 사용 중입니다. 잠시 후 다시 시도해 주세요.",
            ) from e
        raise HTTPException(status_code=500, detail=f"DB 오류: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


@app.post("/papers/ingest")
def ingest(req: IngestRequest) -> dict:
    try:
        result = ingest_pdf(
            file_path=req.file_path,
            extract_equations=req.extract_equations,
            eq_pages=req.eq_pages,
        )
        return {"paper_id": result["paper_id"]}
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except sqlite3.OperationalError as e:
        if _is_db_locked_error(e):
            raise HTTPException(
                status_code=503,
                detail="DB가 사용 중입니다. 잠시 후 다시 시도해 주세요.",
            ) from e
        raise HTTPException(status_code=500, detail=f"DB 오류: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.get("/papers")
def papers(limit: int = Query(default=30, ge=1, le=200), q: str | None = Query(default=None)) -> dict:
    try:
        return list_papers(limit=limit, q=q)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.post("/papers/{paper_id}/build_index")
def build(paper_id: str) -> dict:
    try:
        return build_index(paper_id)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except sqlite3.OperationalError as e:
        if _is_db_locked_error(e):
            raise HTTPException(
                status_code=503,
                detail="DB가 사용 중입니다. 잠시 후 다시 시도해 주세요.",
            ) from e
        raise HTTPException(status_code=500, detail=f"DB 오류: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.post("/papers/{paper_id}/summarize")
def summarize(paper_id: str) -> dict:
    try:
        return summarize_paper(paper_id)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except sqlite3.OperationalError as e:
        if _is_db_locked_error(e):
            raise HTTPException(
                status_code=503,
                detail="DB가 사용 중입니다. 잠시 후 다시 시도해 주세요.",
            ) from e
        raise HTTPException(status_code=500, detail=f"DB 오류: {e}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.get("/papers/{paper_id}/summary")
def summary(paper_id: str) -> dict:
    try:
        return get_summary(paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.post("/papers/{paper_id}/qa")
def qa(paper_id: str, req: QARequest) -> dict:
    try:
        return answer_question(paper_id=paper_id, question=req.question, top_k=req.top_k)
    except (RuntimeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.get("/papers/{paper_id}")
def paper_detail(paper_id: str) -> dict:
    try:
        return get_paper_details(paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e


@app.delete("/papers/{paper_id}")
def paper_delete(paper_id: str) -> dict:
    try:
        return delete_paper(paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}") from e
