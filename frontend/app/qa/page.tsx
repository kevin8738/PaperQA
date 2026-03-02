"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import Chat, { type ChatMessage } from "@/components/Chat";
import PaperPicker from "@/components/PaperPicker";
import { askQuestion, listPapers, type PaperListItem } from "@/lib/api";

function QAInnerPage() {
  const searchParams = useSearchParams();
  const queryPaperId = searchParams.get("paper_id") || "";
  const [papers, setPapers] = useState<PaperListItem[]>([]);
  const [selectedPaperId, setSelectedPaperId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listPapers(100)
      .then((res) => {
        setPapers(res.items);
        if (queryPaperId) {
          setSelectedPaperId(queryPaperId);
        } else if (res.items.length > 0) {
          setSelectedPaperId(res.items[0].paper_id);
        }
      })
      .catch((e: Error) => setError(e.message));
  }, [queryPaperId]);

  const selectedPaper = useMemo(
    () => papers.find((p) => p.paper_id === selectedPaperId) || null,
    [papers, selectedPaperId]
  );

  const onSend = async (text: string) => {
    if (!selectedPaperId) {
      setError("먼저 논문을 선택해 주세요.");
      return;
    }
    setError("");
    const userMessage: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      text
    };
    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);
    try {
      const result = await askQuestion(selectedPaperId, text, 10);
      const assistantMessage: ChatMessage = {
        id: `a-${Date.now()}`,
        role: "assistant",
        text: result.answer,
        citations: result.citations
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "질문 처리 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  if (papers.length === 0 && !error) {
    return (
      <div className="card p-6">
        <p className="text-sm text-slate-700">저장된 논문이 없습니다. 먼저 업로드를 진행해 주세요.</p>
        <div className="mt-3 flex gap-2">
          <Link href="/" className="btn-primary">
            업로드로 이동
          </Link>
          <Link href="/history" className="btn-secondary">
            내역 보기
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
      <div className="space-y-3">
        <PaperPicker
          papers={papers}
          selectedPaperId={selectedPaperId}
          onSelect={(id) => {
            setSelectedPaperId(id);
            setMessages([]);
          }}
        />
        <div className="card p-4 text-sm text-slate-700">
          <p className="font-semibold text-slate-900">선택된 논문</p>
          <p className="mt-1 break-all">{selectedPaper?.title || selectedPaper?.file_name || "없음"}</p>
          <p className="mt-1 text-xs text-slate-500">paper_id: {selectedPaperId || "-"}</p>
          <div className="mt-3 flex gap-2">
            <Link href="/history" className="btn-secondary">
              내역으로 이동
            </Link>
            <Link
              href={selectedPaperId ? `/?paper_id=${selectedPaperId}` : "/"}
              className="btn-secondary"
            >
              요약 보기
            </Link>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {error && <div className="rounded-lg bg-rose-100 p-3 text-sm text-rose-800">오류: {error}</div>}
        {!selectedPaperId ? (
          <div className="card p-6 text-sm text-slate-700">
            paper_id가 없습니다. <Link href="/history" className="text-brand-600 underline">요약 내역</Link>에서 논문을 선택해 주세요.
          </div>
        ) : (
          <Chat messages={messages} isLoading={loading} onSend={onSend} />
        )}
      </div>
    </div>
  );
}

export default function QAPage() {
  return (
    <Suspense fallback={<div className="card p-5 text-sm text-slate-700">QA 페이지 로딩 중...</div>}>
      <QAInnerPage />
    </Suspense>
  );
}
