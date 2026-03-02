"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import SummaryView from "@/components/SummaryView";
import {
  getUploadJob,
  getPaper,
  startUploadAndProcessJob,
  type SummaryJson
} from "@/lib/api";

function UploadAndSummarizeInner() {
  const searchParams = useSearchParams();
  const queryPaperId = searchParams.get("paper_id") || "";
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [isBusy, setIsBusy] = useState(false);
  const [status, setStatus] = useState("업로드할 PDF를 선택하세요.");
  const [error, setError] = useState("");
  const [paperId, setPaperId] = useState("");
  const [jobId, setJobId] = useState("");
  const [summary, setSummary] = useState<SummaryJson | null>(null);
  const pollRef = useRef<number | null>(null);

  const clearPoll = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const stepText = (step: string, message: string) => {
    if (message) return message;
    if (step === "ingest") return "1/3 업로드 및 텍스트/수식 추출 중...";
    if (step === "summarize") return "2/3 한국어 구조화 요약 생성 중...";
    if (step === "build_index") return "3/3 QA용 인덱스 생성 중...";
    if (step === "done") return "완료";
    return "처리 중...";
  };

  const startPolling = (targetJobId: string) => {
    clearPoll();
    pollRef.current = window.setInterval(async () => {
      try {
        const job = await getUploadJob(targetJobId);
        setStatus(stepText(job.step, job.message));
        if (job.paper_id) setPaperId(job.paper_id);
        if (job.status === "failed") {
          clearPoll();
          localStorage.removeItem("paperqa_active_job");
          setIsBusy(false);
          setError(job.error || job.message || "처리 중 오류가 발생했습니다.");
          return;
        }
        if (job.status === "completed" && job.paper_id) {
          clearPoll();
          localStorage.removeItem("paperqa_active_job");
          const detail = await getPaper(job.paper_id);
          setSummary(detail.summary);
          setStatus("완료: 요약과 QA 인덱스가 준비되었습니다.");
          setIsBusy(false);
        }
      } catch (e) {
        clearPoll();
        localStorage.removeItem("paperqa_active_job");
        setIsBusy(false);
        setError(e instanceof Error ? e.message : "상태 조회 중 오류가 발생했습니다.");
      }
    }, 1500);
  };

  useEffect(() => {
    if (!queryPaperId) return;
    setIsBusy(true);
    setStatus("저장된 요약을 불러오는 중...");
    setError("");
    getPaper(queryPaperId)
      .then((data) => {
        setPaperId(data.paper_id);
        if (data.summary) {
          setSummary(data.summary);
          setStatus("저장된 요약을 불러왔습니다.");
        } else {
          setStatus("요약이 아직 없어 새로 생성할 수 있습니다.");
        }
      })
      .catch((e: Error) => {
        setError(e.message);
      })
      .finally(() => setIsBusy(false));
  }, [queryPaperId]);

  useEffect(() => {
    const activeJobId = localStorage.getItem("paperqa_active_job");
    if (!activeJobId) return;
    setJobId(activeJobId);
    setIsBusy(true);
    setStatus("진행 중인 작업을 복구하는 중...");
    startPolling(activeJobId);
    return () => clearPoll();
  }, []);

  useEffect(() => {
    return () => clearPoll();
  }, []);

  const runPipeline = async () => {
    if (!file) {
      setError("PDF 파일을 먼저 선택해 주세요.");
      return;
    }
    setIsBusy(true);
    setError("");
    setSummary(null);
    try {
      setStatus("요청 등록 중...");
      const job = await startUploadAndProcessJob(file, {
        extractEquations: true,
        eqPages: "methods_appendix"
      });
      setJobId(job.job_id);
      localStorage.setItem("paperqa_active_job", job.job_id);
      setStatus("1/3 업로드 및 텍스트/수식 추출 중...");
      startPolling(job.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "처리 중 오류가 발생했습니다.");
      setStatus("실패");
      setIsBusy(false);
      clearPoll();
      localStorage.removeItem("paperqa_active_job");
    }
  };

  return (
    <div className="space-y-6">
      <section className="card p-5">
        <h1 className="text-xl font-bold text-slate-900">PDF 업로드 후 한국어 요약</h1>
        <p className="mt-1 text-sm text-slate-600">
          업로드 한 번으로 수식 추출, 한국어 요약, QA 인덱스 생성까지 자동으로 진행합니다.
        </p>

        <div
          className={`mt-4 rounded-xl border-2 border-dashed p-6 text-center ${
            dragOver ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            setDragOver(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const dropped = e.dataTransfer.files?.[0];
            if (dropped && dropped.type === "application/pdf") {
              setFile(dropped);
              setError("");
            } else {
              setError("PDF 파일만 업로드할 수 있습니다.");
            }
          }}
        >
          <p className="mb-3 text-sm text-slate-700">
            PDF를 드래그 앤 드롭하거나 아래에서 파일을 선택하세요.
          </p>
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => {
              const picked = e.target.files?.[0] || null;
              setFile(picked);
              setError("");
            }}
          />
          {file && <p className="mt-3 text-sm font-medium text-slate-800">선택 파일: {file.name}</p>}
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button className="btn-primary" disabled={isBusy} onClick={runPipeline}>
            {isBusy ? "처리 중..." : "업로드하고 요약 생성"}
          </button>
          {paperId && (
            <>
              <Link className="btn-secondary" href={`/qa?paper_id=${paperId}`}>
                QA 하러 가기
              </Link>
              <Link className="btn-secondary" href="/history">
                요약 내역 보기
              </Link>
            </>
          )}
        </div>

        <div className="mt-4 rounded-lg bg-slate-100 p-3 text-sm text-slate-800">상태: {status}</div>
        {jobId && <div className="mt-2 text-xs text-slate-500">job_id: {jobId}</div>}
        {error && <div className="mt-3 rounded-lg bg-rose-100 p-3 text-sm text-rose-800">오류: {error}</div>}
      </section>

      {summary && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-slate-900">요약 결과</h2>
            <span className="rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-700">
              language: {summary.language}
            </span>
          </div>
          <SummaryView summary={summary} />
        </section>
      )}
    </div>
  );
}

export default function UploadAndSummarizePage() {
  return (
    <Suspense fallback={<div className="card p-5 text-sm text-slate-700">페이지 로딩 중...</div>}>
      <UploadAndSummarizeInner />
    </Suspense>
  );
}
