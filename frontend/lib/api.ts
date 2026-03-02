export type EqPagesMode = "methods_appendix" | "all";

export type SummaryJson = {
  language: "ko";
  one_sentence: string;
  problem: string;
  key_idea: string[];
  method: {
    inputs: string[];
    model: string;
    training_objective: string;
  };
  math_core: Array<{
    name: string;
    latex: string;
    meaning: string;
  }>;
  limitations: string[];
  repro_checklist: string[];
};

export type Citation = {
  chunk_id: string;
  page_range: string;
  score: number;
  start_text?: string;
};

export type QAResponse = {
  answer: string;
  citations: Citation[];
};

export type PaperListItem = {
  paper_id: string;
  title: string;
  file_name: string;
  created_at: string;
  summary_exists: boolean;
  summary_created_at: string;
};

export type PaperDetail = {
  paper_id: string;
  title: string;
  pdf_path: string;
  created_at: string;
  stats: {
    pages: number;
    chunks: number;
    equations: number;
    qa_history: number;
  };
  summary_created_at: string | null;
  summary: SummaryJson | null;
};

export type UploadJobStatus = {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  step: "queued" | "ingest" | "summarize" | "build_index" | "done" | "error";
  message: string;
  paper_id: string | null;
  error?: string;
};

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers || {})
    },
    cache: "no-store"
  });
  if (!res.ok) {
    let message = `요청 실패 (${res.status})`;
    try {
      const data = await res.json();
      message = data?.detail || message;
    } catch {
      message = `${message}: ${res.statusText}`;
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

export async function uploadPaper(
  file: File,
  options?: { extractEquations?: boolean; eqPages?: EqPagesMode }
): Promise<{ paper_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("extract_equations", String(options?.extractEquations ?? true));
  form.append("eq_pages", options?.eqPages ?? "methods_appendix");
  return request<{ paper_id: string }>("/papers/upload", {
    method: "POST",
    body: form
  });
}

export async function startUploadAndProcessJob(
  file: File,
  options?: { extractEquations?: boolean; eqPages?: EqPagesMode }
): Promise<{ job_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("extract_equations", String(options?.extractEquations ?? true));
  form.append("eq_pages", options?.eqPages ?? "methods_appendix");
  return request<{ job_id: string }>("/jobs/upload_and_process", {
    method: "POST",
    body: form
  });
}

export async function getUploadJob(jobId: string): Promise<UploadJobStatus> {
  return request<UploadJobStatus>(`/jobs/${jobId}`);
}

export async function summarizePaper(paperId: string): Promise<SummaryJson> {
  return request<SummaryJson>(`/papers/${paperId}/summarize`, {
    method: "POST"
  });
}

export async function buildPaperIndex(paperId: string): Promise<{ status: string; backend: string; chunks: number }> {
  return request<{ status: string; backend: string; chunks: number }>(`/papers/${paperId}/build_index`, {
    method: "POST"
  });
}

export async function askQuestion(paperId: string, question: string, topK = 10): Promise<QAResponse> {
  return request<QAResponse>(`/papers/${paperId}/qa`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, top_k: topK })
  });
}

export async function listPapers(limit = 50, q?: string): Promise<{ items: PaperListItem[]; count: number }> {
  const qp = new URLSearchParams({ limit: String(limit) });
  if (q?.trim()) qp.set("q", q.trim());
  return request<{ items: PaperListItem[]; count: number }>(`/papers?${qp.toString()}`);
}

export async function getPaper(paperId: string): Promise<PaperDetail> {
  return request<PaperDetail>(`/papers/${paperId}`);
}

export async function getSummary(paperId: string): Promise<{ paper_id: string; created_at: string; summary: SummaryJson }> {
  return request<{ paper_id: string; created_at: string; summary: SummaryJson }>(`/papers/${paperId}/summary`);
}

export async function deletePaper(paperId: string): Promise<{ status: string; paper_id: string }> {
  return request<{ status: string; paper_id: string }>(`/papers/${paperId}`, { method: "DELETE" });
}
