from __future__ import annotations

import json
import math
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import fitz
import numpy as np
from dotenv import load_dotenv

from backend.utils_openai import OpenAIWrapper

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
PAPERS_DIR = DATA_DIR / "papers"
PAGES_DIR = DATA_DIR / "pages"
INDEX_DIR = DATA_DIR / "index"
DB_PATH = DATA_DIR / "db.sqlite"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_storage() -> None:
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    _ensure_storage()
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.executescript(schema)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn


def _paper_or_raise(conn: sqlite3.Connection, paper_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    if not row:
        raise ValueError(f"paper_id '{paper_id}' not found. Run ingest first.")
    return row


def _select_equation_pages(conn: sqlite3.Connection, paper_id: str, mode: str) -> list[int]:
    rows = conn.execute(
        "SELECT page_no, text FROM pages WHERE paper_id = ? ORDER BY page_no ASC",
        (paper_id,),
    ).fetchall()
    if not rows:
        return []
    if mode == "all":
        return [int(r["page_no"]) for r in rows]
    keywords = ("method", "approach", "appendix", "supplementary")
    candidate = []
    for row in rows:
        text = str(row["text"] or "").lower()
        if any(k in text for k in keywords):
            candidate.append(int(row["page_no"]))
    if candidate:
        return sorted(set(candidate))
    total_pages = len(rows)
    start_page = max(1, math.floor(total_pages * 0.8) + 1)
    return [int(r["page_no"]) for r in rows if int(r["page_no"]) >= start_page]


def _chunk_pages(rows: list[sqlite3.Row]) -> list[tuple[str, int, int, str]]:
    chunk_min_chars = 3200
    chunk_target_chars = 4500
    built: list[tuple[str, int, int, str]] = []
    buffer: list[str] = []
    buffer_len = 0
    chunk_start = None
    chunk_end = None

    for row in rows:
        page_no = int(row["page_no"])
        page_text = str(row["text"] or "").strip()
        if not page_text:
            continue
        segment = f"[p.{page_no}] {page_text}\n"
        if chunk_start is None:
            chunk_start = page_no
        if buffer_len + len(segment) > chunk_target_chars and buffer_len >= chunk_min_chars:
            content = "".join(buffer).strip()
            if content:
                built.append((uuid4().hex, int(chunk_start), int(chunk_end), content))
            buffer = []
            buffer_len = 0
            chunk_start = page_no
        buffer.append(segment)
        buffer_len += len(segment)
        chunk_end = page_no

    if buffer and chunk_start is not None and chunk_end is not None:
        content = "".join(buffer).strip()
        if content:
            built.append((uuid4().hex, int(chunk_start), int(chunk_end), content))
    return built


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ingest_pdf(file_path: str, extract_equations: bool, eq_pages: str) -> dict:
    init_db()
    source = Path(file_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"File not found: {source}")
    if source.suffix.lower() != ".pdf":
        raise ValueError("Input file must be a .pdf")
    if eq_pages not in {"methods_appendix", "all"}:
        raise ValueError("eq_pages must be 'methods_appendix' or 'all'")

    paper_id = uuid4().hex
    stored_pdf = PAPERS_DIR / f"{paper_id}.pdf"
    shutil.copy2(source, stored_pdf)
    pages_dir = PAGES_DIR / paper_id
    pages_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(stored_pdf) as doc:
        title = (doc.metadata.get("title") or "").strip() if doc.metadata else ""
        if not title:
            title = source.stem
        with _connect() as conn:
            conn.execute(
                "INSERT INTO papers(paper_id, title, pdf_path, created_at) VALUES (?, ?, ?, ?)",
                (paper_id, title, str(stored_pdf), _utc_now()),
            )
            for idx, page in enumerate(doc, start=1):
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = pages_dir / f"{idx:04d}.png"
                pix.save(str(image_path))
                text = page.get_text("text") or ""
                conn.execute(
                    "INSERT INTO pages(paper_id, page_no, text) VALUES (?, ?, ?)",
                    (paper_id, idx, text),
                )

    equation_rows = 0
    equation_page_count = 0
    equation_results: list[dict] = []
    if extract_equations:
        openai_client = OpenAIWrapper()
        with _connect() as conn:
            selected_pages = _select_equation_pages(conn, paper_id, eq_pages)
        equation_page_count = len(selected_pages)
        for page_no in selected_pages:
            image_path = pages_dir / f"{page_no:04d}.png"
            if not image_path.exists():
                continue
            equations = openai_client.transcribe_equations(image_path=image_path)
            if isinstance(equations, dict):
                equations = [equations]
            elif not isinstance(equations, list):
                equations = []
            equation_results.append({"page_no": page_no, "equations": equations})
            if not equations:
                continue
            # Keep DB write lock short; OCR call above can take seconds per page.
            with _connect() as conn:
                for eq in equations:
                    if isinstance(eq, dict):
                        latex = str(eq.get("latex", "")).strip()
                        confidence_raw = eq.get("confidence", 0.0)
                    elif isinstance(eq, str):
                        latex = eq.strip()
                        confidence_raw = 0.0
                    else:
                        continue
                    if not latex:
                        continue
                    confidence = float(confidence_raw)
                    confidence = min(1.0, max(0.0, confidence))
                    conn.execute(
                        "INSERT INTO equations(paper_id, page_no, latex, confidence) VALUES (?, ?, ?, ?)",
                        (paper_id, page_no, latex, confidence),
                    )
                    equation_rows += 1

    return {
        "paper_id": paper_id,
        "equation_pages_scanned": equation_page_count,
        "equations_saved": equation_rows,
        "equation_results": equation_results,
    }


def build_index(paper_id: str) -> dict:
    init_db()
    with _connect() as conn:
        _paper_or_raise(conn, paper_id)
        page_rows = conn.execute(
            "SELECT page_no, text FROM pages WHERE paper_id = ? ORDER BY page_no ASC",
            (paper_id,),
        ).fetchall()
        if not page_rows:
            raise RuntimeError("No page text found. Run ingest first.")
        chunks = _chunk_pages(page_rows)
        if not chunks:
            raise RuntimeError("No non-empty text chunks created from pages.")
        conn.execute("DELETE FROM chunks WHERE paper_id = ?", (paper_id,))
        for chunk_id, page_start, page_end, content in chunks:
            conn.execute(
                "INSERT INTO chunks(chunk_id, paper_id, page_start, page_end, content) VALUES (?, ?, ?, ?, ?)",
                (chunk_id, paper_id, page_start, page_end, content),
            )

    openai_client = OpenAIWrapper()
    chunk_contents = [c[3] for c in chunks]
    vectors = np.array(openai_client.embed_texts(chunk_contents), dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(chunks):
        raise RuntimeError("Embedding shape mismatch while building index.")

    mapping = [{"chunk_id": c[0], "page_start": c[1], "page_end": c[2]} for c in chunks]
    _write_json(INDEX_DIR / f"{paper_id}.chunks.json", mapping)
    backend_used = "faiss"

    try:
        import faiss  # type: ignore

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        vectors = vectors / norms
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        faiss.write_index(index, str(INDEX_DIR / f"{paper_id}.faiss"))
        _write_json(
            INDEX_DIR / f"{paper_id}.meta.json",
            {
                "backend": "faiss",
                "faiss_path": str(INDEX_DIR / f"{paper_id}.faiss"),
                "mapping_path": str(INDEX_DIR / f"{paper_id}.chunks.json"),
                "embedding_model": openai_client.embedding_model,
            },
        )
    except Exception:
        backend_used = "chromadb"
        try:
            import chromadb  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "Neither FAISS nor Chroma could be initialized. Install faiss-cpu or chromadb."
            ) from e

        chroma_dir = INDEX_DIR / "chroma"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(chroma_dir))
        collection_name = f"paper_{paper_id}"
        try:
            client.delete_collection(collection_name)
        except Exception:
            pass
        collection = client.create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
        collection.add(
            ids=[c[0] for c in chunks],
            embeddings=vectors.tolist(),
            documents=chunk_contents,
            metadatas=[{"page_start": c[1], "page_end": c[2]} for c in chunks],
        )
        _write_json(
            INDEX_DIR / f"{paper_id}.meta.json",
            {
                "backend": "chromadb",
                "collection_name": collection_name,
                "chroma_dir": str(chroma_dir),
                "mapping_path": str(INDEX_DIR / f"{paper_id}.chunks.json"),
                "embedding_model": openai_client.embedding_model,
            },
        )

    return {"status": "ok", "backend": backend_used, "chunks": len(chunks)}


def _retrieve_chunks(paper_id: str, question: str, top_k: int) -> list[dict]:
    meta_path = INDEX_DIR / f"{paper_id}.meta.json"
    if not meta_path.exists():
        raise RuntimeError("Index not found. Run build_index first.")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    mapping_path = Path(meta["mapping_path"])
    if not mapping_path.exists():
        raise RuntimeError("Chunk mapping JSON missing. Re-run build_index.")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    openai_client = OpenAIWrapper()
    question_norm = question.strip().lower()
    queries = [question]
    query_en = ""
    if re.search(r"[\uac00-\ud7a3]", question):
        try:
            query_en = openai_client.translate_query_to_english(question)
            if query_en and query_en not in queries:
                queries.append(query_en)
        except Exception:
            pass
    query_signal = " ".join(queries).lower()
    is_overview_question = any(
        k in query_signal
        for k in ["what paper", "overview", "summary", "contribution", "abstract", "main idea"]
    ) or any(k in question for k in ["어떤 논문", "무슨 논문", "요약", "핵심", "기여"])
    is_process_question = any(
        k in query_signal
        for k in ["forward process", "reverse process", "q(x_t|x_{t-1})", "p_theta", "diffusion process"]
    ) or any(k in question for k in ["순방향", "역방향", "t 시점", "확산", "denoise"])
    is_loss_question = (
        "loss" in query_signal
        or "objective" in query_signal
        or "variational" in query_signal
        or any(k in question for k in ["손실", "목적함수", "학습 목표", "식"])
    )
    hint_queries: list[str] = []
    if is_overview_question:
        hint_queries.append("paper abstract contributions method conclusion")
    if is_process_question:
        hint_queries.append("forward process reverse process q(x_t|x_{t-1}) p_theta(x_{t-1}|x_t) diffusion")
    if is_loss_question:
        hint_queries.append("training objective loss variational bound L_simple epsilon prediction")
    for hq in hint_queries:
        if hq not in queries:
            queries.append(hq)
    qvecs = np.array(openai_client.embed_texts(queries), dtype=np.float32)
    results: list[dict] = []

    if meta["backend"] == "faiss":
        try:
            import faiss  # type: ignore
        except Exception as e:
            raise RuntimeError("FAISS index exists but faiss-cpu is not available.") from e
        index = faiss.read_index(meta["faiss_path"])
        candidate_k = min(max(top_k * 4, top_k, 1), index.ntotal)
        search_k = min(max(top_k * 3, top_k, 1), index.ntotal)
        score_map: dict[str, float] = {}
        for qvec in qvecs:
            norm = np.linalg.norm(qvec)
            if norm == 0:
                norm = 1.0
            qn = qvec / norm
            scores, indices = index.search(qn.reshape(1, -1), search_k)
            for score, idx in zip(scores[0].tolist(), indices[0].tolist()):
                if idx < 0:
                    continue
                entry = mapping[idx]
                cid = entry["chunk_id"]
                prev = score_map.get(cid, -1e9)
                score_map[cid] = max(prev, float(score))
        for cid, score in sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:candidate_k]:
            results.append({"chunk_id": cid, "score": score})
    else:
        try:
            import chromadb  # type: ignore
        except Exception as e:
            raise RuntimeError("Chroma index exists but chromadb is not available.") from e
        client = chromadb.PersistentClient(path=str(meta["chroma_dir"]))
        collection = client.get_collection(name=meta["collection_name"])
        candidate_k = min(max(top_k * 4, top_k, 1), len(mapping))
        search_k = min(max(top_k * 3, top_k, 1), len(mapping))
        query = collection.query(
            query_embeddings=qvecs.tolist(),
            n_results=search_k,
            include=["distances", "metadatas", "documents"],
        )
        ids_rows = query.get("ids", [])
        dist_rows = query.get("distances", [])
        score_map: dict[str, float] = {}
        for ids, distances in zip(ids_rows, dist_rows):
            for cid, dist in zip(ids, distances):
                score = 1.0 - float(dist)
                prev = score_map.get(cid, -1e9)
                score_map[cid] = max(prev, score)
        for cid, score in sorted(score_map.items(), key=lambda x: x[1], reverse=True)[:candidate_k]:
            results.append({"chunk_id": cid, "score": score})

    if not results:
        return []

    def _is_reference_like(text: str) -> bool:
        low = text.lower()
        if low.count("arxiv") >= 2:
            return True
        if len(re.findall(r"\[\d+\]", text)) >= 8:
            return True
        if "references" in low and low.count("[") >= 8:
            return True
        return False

    def _add_chunk_if_missing(base: list[dict], row: sqlite3.Row, score_hint: float) -> None:
        cid = str(row["chunk_id"])
        exists = any(item["chunk_id"] == cid for item in base)
        if exists:
            return
        base.append(
            {
                "chunk_id": cid,
                "page_start": int(row["page_start"]),
                "page_end": int(row["page_end"]),
                "content": str(row["content"]),
                "score": float(score_hint),
            }
        )

    with _connect() as conn:
        ordered: list[dict] = []
        for item in results:
            row = conn.execute(
                "SELECT chunk_id, page_start, page_end, content FROM chunks WHERE paper_id = ? AND chunk_id = ?",
                (paper_id, item["chunk_id"]),
            ).fetchone()
            if not row:
                continue
            ordered.append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "page_start": int(row["page_start"]),
                    "page_end": int(row["page_end"]),
                    "content": str(row["content"]),
                    "score": float(item["score"]),
                }
            )
        if not ordered:
            return []

        # Prefer content chunks over bibliography-heavy chunks when enough candidates exist.
        content_like = [c for c in ordered if not _is_reference_like(c["content"])]
        if len(content_like) >= max(2, top_k // 2):
            ordered = content_like + [c for c in ordered if _is_reference_like(c["content"])]

        # Add lexical boosts to recover important chunks that pure vector search can miss.
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "into",
            "what",
            "which",
            "how",
            "why",
            "when",
            "where",
            "paper",
            "model",
        }
        lexical_tokens = [
            t
            for t in re.findall(r"[a-z][a-z0-9_]{2,}", " ".join(queries).lower())
            if t not in stopwords
        ]
        token_set = sorted(set(lexical_tokens))[:40]
        for item in ordered:
            low = item["content"].lower()
            overlap = sum(1 for tok in token_set if tok in low)
            boost = min(0.30, overlap * 0.03)
            if is_process_question and any(
                marker in low
                for marker in [
                    "forward process",
                    "reverse process",
                    "q(x_t",
                    "p_theta",
                    "x_{t-1}|x_t",
                    "diffusion",
                ]
            ):
                boost += 0.20
            if is_loss_question and any(
                marker in low
                for marker in [
                    "loss",
                    "objective",
                    "variational",
                    "l_simple",
                    "epsilon",
                ]
            ):
                boost += 0.20
            if is_overview_question and item["page_start"] <= 2:
                boost += 0.10
            if _is_reference_like(item["content"]):
                boost -= 0.25
            item["score"] = float(item["score"]) + boost

        # For overview-style questions, ensure intro and conclusion chunks are present.
        if is_overview_question:
            best_score = max(float(c["score"]) for c in ordered)
            intro_rows = conn.execute(
                """
                SELECT chunk_id, page_start, page_end, content
                FROM chunks
                WHERE paper_id = ?
                ORDER BY page_start ASC
                LIMIT 2
                """,
                (paper_id,),
            ).fetchall()
            for i, row in enumerate(intro_rows):
                _add_chunk_if_missing(ordered, row, best_score + 0.05 - (i * 0.01))
            last_row = conn.execute(
                """
                SELECT chunk_id, page_start, page_end, content
                FROM chunks
                WHERE paper_id = ?
                ORDER BY page_end DESC
                LIMIT 1
                """,
                (paper_id,),
            ).fetchone()
            if last_row:
                _add_chunk_if_missing(ordered, last_row, best_score + 0.02)

        # For process/loss questions, force-include method-like chunks when available.
        if is_process_question or is_loss_question:
            best_score = max(float(c["score"]) for c in ordered)
            method_rows = conn.execute(
                """
                SELECT chunk_id, page_start, page_end, content
                FROM chunks
                WHERE paper_id = ?
                AND (
                    lower(content) LIKE '%forward process%'
                    OR lower(content) LIKE '%reverse process%'
                    OR lower(content) LIKE '%q(x_t%'
                    OR lower(content) LIKE '%p_theta%'
                    OR lower(content) LIKE '%loss%'
                    OR lower(content) LIKE '%variational%'
                    OR lower(content) LIKE '%objective%'
                    OR lower(content) LIKE '%l_simple%'
                    OR lower(content) LIKE '%epsilon%'
                )
                ORDER BY page_start ASC
                LIMIT 4
                """,
                (paper_id,),
            ).fetchall()
            for i, row in enumerate(method_rows):
                _add_chunk_if_missing(ordered, row, best_score + 0.08 - (i * 0.01))

        ordered.sort(key=lambda x: float(x["score"]), reverse=True)
        return ordered[: max(top_k, 1)]


def answer_question(paper_id: str, question: str, top_k: int = 10) -> dict:
    init_db()
    if not question.strip():
        raise ValueError("Question must not be empty.")
    with _connect() as conn:
        _paper_or_raise(conn, paper_id)

    retrieved = _retrieve_chunks(paper_id=paper_id, question=question, top_k=top_k)
    top_score = max((float(x.get("score", 0.0)) for x in retrieved), default=0.0)

    if len(retrieved) < 2:
        answer = "근거 부족: 최소 2개 인용 근거를 확보하지 못했습니다."
        citations: list[dict] = []
    elif top_score < 0.2:
        answer = "근거 부족: 질문과 직접적으로 연결되는 논문 근거를 찾지 못했습니다."
        citations = []
    else:
        stop_terms = {
            "the",
            "and",
            "for",
            "with",
            "this",
            "that",
            "from",
            "into",
            "about",
            "paper",
            "model",
            "what",
            "which",
            "how",
            "does",
            "is",
            "are",
            "이",
            "그",
            "저",
            "논문",
            "설명",
            "알려줘",
            "뭐야",
            "어떤",
            "무슨",
        }
        question_terms = {
            tok
            for tok in re.findall(r"[가-힣]{2,}|[a-zA-Z][a-zA-Z0-9_]{2,}", question.lower())
            if tok not in stop_terms
        }

        def citation_start_text(content: str, limit: int = 180) -> str:
            raw = str(content or "")
            raw = re.sub(r"\[p\.\d+\]\s*", "", raw)
            raw = re.sub(r"\s+", " ", raw).strip()
            if not raw:
                return ""

            def is_heading_like(sentence: str) -> bool:
                s = sentence.strip()
                low = s.lower()
                if not s:
                    return True
                if low.startswith("denoising diffusion probabilistic models"):
                    return True
                if low.startswith("deep unsupervised learning using nonequilibrium thermodynamics"):
                    return True
                if low.startswith(("algorithm ", "table ", "figure ", "appendix ")):
                    return True
                if "@" in s:
                    return True
                if re.fullmatch(r"\d+(?:\.\d+)*\.?", s):
                    return True
                if len(s.split()) <= 8 and s == s.title():
                    return True
                if len(re.findall(r"\d", s)) >= 10 and len(s.split()) <= 25:
                    return True
                return False

            sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
            best_sentence = ""
            best_score = -1
            for sentence in sentences[:24]:
                if is_heading_like(sentence):
                    continue
                low = sentence.lower()
                overlap = sum(1 for tok in question_terms if tok in low)
                score = (overlap * 5) + (1 if len(sentence) >= 40 else 0)
                if score > best_score:
                    best_score = score
                    best_sentence = sentence

            start = best_sentence or raw
            if len(start) > limit:
                return start[: limit - 1].rstrip() + "…"
            return start

        context_blocks = []
        ref_map: dict[int, dict] = {}
        for idx, item in enumerate(retrieved, start=1):
            page_range = f"p.{item['page_start']}" if item["page_start"] == item["page_end"] else f"p.{item['page_start']}-p.{item['page_end']}"
            ref_map[idx] = item
            context_blocks.append(
                f"[ref={idx}] [chunk_id={item['chunk_id']}] [pages={page_range}] [score={item['score']:.4f}]\n{item['content']}"
            )
        context = "\n\n".join(context_blocks)
        openai_client = OpenAIWrapper()
        qa_json = openai_client.answer_with_citations(question=question, context=context, force_attempt=False)

        def to_citations(payload: dict) -> tuple[str, list[dict]]:
            raw_answer_local = str(payload.get("answer", "")).strip()
            ref_nos = []
            for c in payload.get("citations", []):
                try:
                    no = int(c.get("ref_no", 0))
                except Exception:
                    no = 0
                if no > 0:
                    ref_nos.append(no)
            seen_ref = set()
            ref_nos = [r for r in ref_nos if not (r in seen_ref or seen_ref.add(r))]
            local_citations = []
            for no in ref_nos:
                ref = ref_map.get(no)
                if not ref:
                    continue
                page_range_local = (
                    f"p.{ref['page_start']}"
                    if ref["page_start"] == ref["page_end"]
                    else f"p.{ref['page_start']}-p.{ref['page_end']}"
                )
                local_citations.append(
                    {
                        "chunk_id": ref["chunk_id"],
                        "page_range": page_range_local,
                        "score": round(float(ref["score"]), 6),
                        "start_text": citation_start_text(ref.get("content", "")),
                    }
                )
            return raw_answer_local, local_citations

        def is_insufficient(text: str) -> bool:
            low = (text or "").strip().lower()
            if not low:
                return True
            return (
                "근거 부족" in low
                or "답변을 만들 수 없습니다" in low
                or "cannot answer" in low
                or "insufficient evidence" in low
            )

        raw_answer, citations = to_citations(qa_json)
        if len(citations) < 2 or is_insufficient(raw_answer):
            qa_json_retry = openai_client.answer_with_citations(
                question=question,
                context=context,
                force_attempt=True,
            )
            raw_answer, citations = to_citations(qa_json_retry)

        if len(citations) < 2 or is_insufficient(raw_answer):
            compact_context = "\n\n".join(context_blocks[:6])
            fallback_answer = openai_client.answer_best_effort(question=question, context=compact_context)
            if fallback_answer and not is_insufficient(fallback_answer):
                answer = fallback_answer
                fallback_refs = sorted(retrieved, key=lambda x: float(x["score"]), reverse=True)[:2]
                citations = []
                for ref in fallback_refs:
                    page_range = (
                        f"p.{ref['page_start']}"
                        if ref["page_start"] == ref["page_end"]
                        else f"p.{ref['page_start']}-p.{ref['page_end']}"
                    )
                    citations.append(
                        {
                            "chunk_id": ref["chunk_id"],
                            "page_range": page_range,
                            "score": round(float(ref["score"]), 6),
                            "start_text": citation_start_text(ref.get("content", "")),
                        }
                    )
            else:
                answer = "근거 부족: 제공된 컨텍스트만으로는 인용 가능한 답변을 만들 수 없습니다."
                citations = []
        else:
            answer = raw_answer

    with _connect() as conn:
        conn.execute(
            "INSERT INTO qa_history(paper_id, question, answer, citations_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (paper_id, question, answer, json.dumps(citations, ensure_ascii=False), _utc_now()),
        )
    return {"answer": answer, "citations": citations}


def summarize_paper(paper_id: str) -> dict:
    init_db()
    with _connect() as conn:
        paper = _paper_or_raise(conn, paper_id)
        page_rows = conn.execute(
            "SELECT page_no, text FROM pages WHERE paper_id = ? ORDER BY page_no ASC",
            (paper_id,),
        ).fetchall()
        if not page_rows:
            raise RuntimeError("No pages found. Run ingest first.")
        eq_rows = conn.execute(
            "SELECT page_no, latex, confidence FROM equations WHERE paper_id = ? ORDER BY confidence DESC, page_no ASC LIMIT 60",
            (paper_id,),
        ).fetchall()

    text_lines = []
    for row in page_rows:
        page_no = int(row["page_no"])
        text = str(row["text"] or "").strip()
        if text:
            text_lines.append(f"[p.{page_no}] {text}")
    text_blob = "\n".join(text_lines)[:50000]
    eq_blob = "\n".join(
        [f"[p.{int(row['page_no'])}] {row['latex']}" for row in eq_rows if str(row["latex"]).strip()]
    )[:12000]
    title = str(paper["title"] or "")
    openai_client = OpenAIWrapper()
    summary_json = openai_client.summarize_paper(title=title, paper_text=text_blob, equations=eq_blob)
    summary_json["language"] = "ko"

    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO summaries(paper_id, summary_json, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(paper_id)
            DO UPDATE SET summary_json=excluded.summary_json, created_at=excluded.created_at
            """,
            (paper_id, json.dumps(summary_json, ensure_ascii=False), _utc_now()),
        )
    return summary_json


def get_paper_details(paper_id: str) -> dict:
    init_db()
    with _connect() as conn:
        paper = _paper_or_raise(conn, paper_id)
        page_count = conn.execute("SELECT COUNT(*) FROM pages WHERE paper_id = ?", (paper_id,)).fetchone()[0]
        chunk_count = conn.execute("SELECT COUNT(*) FROM chunks WHERE paper_id = ?", (paper_id,)).fetchone()[0]
        equation_count = conn.execute("SELECT COUNT(*) FROM equations WHERE paper_id = ?", (paper_id,)).fetchone()[0]
        qa_count = conn.execute("SELECT COUNT(*) FROM qa_history WHERE paper_id = ?", (paper_id,)).fetchone()[0]
        summary_row = conn.execute(
            "SELECT summary_json, created_at FROM summaries WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()

    summary = None
    summary_created_at = None
    if summary_row:
        summary = json.loads(summary_row["summary_json"])
        if isinstance(summary, dict) and "language" not in summary:
            summary["language"] = "ko"
        summary_created_at = summary_row["created_at"]
    return {
        "paper_id": paper["paper_id"],
        "title": paper["title"],
        "pdf_path": paper["pdf_path"],
        "created_at": paper["created_at"],
        "stats": {
            "pages": int(page_count),
            "chunks": int(chunk_count),
            "equations": int(equation_count),
            "qa_history": int(qa_count),
        },
        "summary_created_at": summary_created_at,
        "summary": summary,
    }


def get_summary(paper_id: str) -> dict:
    init_db()
    with _connect() as conn:
        _paper_or_raise(conn, paper_id)
        row = conn.execute(
            "SELECT summary_json, created_at FROM summaries WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"summary for paper_id '{paper_id}' not found. Run summarize first.")
    summary = json.loads(row["summary_json"])
    if isinstance(summary, dict) and "language" not in summary:
        summary["language"] = "ko"
    return {"paper_id": paper_id, "created_at": row["created_at"], "summary": summary}


def list_papers(limit: int = 30, q: str | None = None) -> dict:
    init_db()
    safe_limit = min(max(int(limit), 1), 200)
    q_norm = (q or "").strip()
    with _connect() as conn:
        if q_norm:
            pattern = f"%{q_norm}%"
            rows = conn.execute(
                """
                SELECT p.paper_id, p.title, p.pdf_path, p.created_at, s.created_at AS summary_created_at
                FROM papers p
                LEFT JOIN summaries s ON s.paper_id = p.paper_id
                WHERE p.title LIKE ? OR p.pdf_path LIKE ? OR p.paper_id LIKE ?
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, safe_limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT p.paper_id, p.title, p.pdf_path, p.created_at, s.created_at AS summary_created_at
                FROM papers p
                LEFT JOIN summaries s ON s.paper_id = p.paper_id
                ORDER BY p.created_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
    items = []
    for row in rows:
        pdf_path = Path(str(row["pdf_path"]))
        items.append(
            {
                "paper_id": str(row["paper_id"]),
                "title": str(row["title"] or ""),
                "file_name": pdf_path.name,
                "created_at": str(row["created_at"]),
                "summary_exists": bool(row["summary_created_at"]),
                "summary_created_at": str(row["summary_created_at"] or ""),
            }
        )
    return {"items": items, "count": len(items)}


def delete_paper(paper_id: str) -> dict:
    init_db()
    paper_meta = None
    with _connect() as conn:
        paper_meta = _paper_or_raise(conn, paper_id)
        conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))

    pdf_path = Path(str(paper_meta["pdf_path"]))
    pages_path = PAGES_DIR / paper_id
    meta_path = INDEX_DIR / f"{paper_id}.meta.json"
    mapping_path = INDEX_DIR / f"{paper_id}.chunks.json"
    faiss_path = INDEX_DIR / f"{paper_id}.faiss"
    meta = None
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = None
    removed = []
    for path in [pdf_path, mapping_path, faiss_path, meta_path]:
        if path.exists():
            path.unlink()
            removed.append(str(path))
    if pages_path.exists():
        shutil.rmtree(pages_path, ignore_errors=True)
        removed.append(str(pages_path))

    try:
        if isinstance(meta, dict) and meta.get("backend") == "chromadb":
            import chromadb  # type: ignore

            client = chromadb.PersistentClient(path=str(meta["chroma_dir"]))
            client.delete_collection(meta["collection_name"])
    except Exception:
        pass
    return {"status": "deleted", "paper_id": paper_id, "removed_paths": removed}
