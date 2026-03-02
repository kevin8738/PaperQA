"use client";

import { useState } from "react";
import type { Citation } from "@/lib/api";

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
};

type Props = {
  messages: ChatMessage[];
  isLoading: boolean;
  onSend: (text: string) => void;
};

export default function Chat({ messages, isLoading, onSend }: Props) {
  const [input, setInput] = useState("");
  const [openCitationIds, setOpenCitationIds] = useState<Record<string, boolean>>({});

  const submit = () => {
    if (!input.trim() || isLoading) return;
    onSend(input.trim());
    setInput("");
  };

  return (
    <div className="card flex h-[70vh] flex-col p-4">
      <div className="mb-3 flex-1 space-y-3 overflow-y-auto rounded-lg bg-slate-50 p-3">
        {messages.length === 0 && (
          <p className="text-sm text-slate-500">질문을 입력하면 근거 인용과 함께 답변을 생성합니다.</p>
        )}
        {messages.map((m) => {
          const isWarning = m.role === "assistant" && m.text.includes("근거 부족");
          const canToggle = m.role === "assistant" && (m.citations?.length || 0) > 0;
          const isOpen = openCitationIds[m.id] ?? false;
          return (
            <div key={m.id} className={`max-w-3xl rounded-xl px-4 py-3 text-sm ${m.role === "user" ? "ml-auto bg-brand-600 text-white" : "bg-white text-slate-900"}`}>
              <div className="whitespace-pre-wrap">{m.text}</div>
              {isWarning && (
                <span className="mt-2 inline-flex rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                  근거 부족
                </span>
              )}
              {canToggle && (
                <div className="mt-2">
                  <button
                    className="text-xs font-semibold text-brand-600 underline"
                    onClick={() =>
                      setOpenCitationIds((prev) => ({ ...prev, [m.id]: !isOpen }))
                    }
                  >
                    {isOpen ? "인용 접기" : "인용 보기"}
                  </button>
                  {isOpen && (
                    <div className="mt-2 space-y-1 rounded-lg border border-slate-200 bg-slate-50 p-2 text-xs text-slate-700">
                      {m.citations?.map((c) => (
                        <div key={`${m.id}-${c.chunk_id}`}>
                          시작 문장: {c.start_text || "(텍스트 없음)"} | page_range: {c.page_range} | score: {c.score.toFixed(4)}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="flex gap-2">
        <textarea
          className="input min-h-20"
          value={input}
          placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <button className="btn-primary h-fit" disabled={isLoading || !input.trim()} onClick={submit}>
          {isLoading ? "전송 중..." : "전송"}
        </button>
      </div>
    </div>
  );
}
