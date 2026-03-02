"use client";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { SummaryJson } from "@/lib/api";

function MarkdownBlock({ text }: { text: string }) {
  return (
    <div className="prose-box">
      <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}

export default function SummaryView({ summary }: { summary: SummaryJson }) {
  return (
    <div className="space-y-4">
      <div className="card p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">한 줄 요약</p>
        <MarkdownBlock text={summary.one_sentence} />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">문제 정의</p>
          <MarkdownBlock text={summary.problem} />
        </div>
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">핵심 아이디어</p>
          <ul className="list-disc space-y-2 pl-5 text-sm text-slate-800">
            {summary.key_idea.map((item, i) => (
              <li key={`${item}-${i}`}>
                <MarkdownBlock text={item} />
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="card p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">방법</p>
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <p className="mb-1 text-xs font-semibold text-slate-500">입력</p>
            <ul className="list-disc pl-5 text-sm text-slate-800">
              {summary.method.inputs.map((input, i) => (
                <li key={`${input}-${i}`}>{input}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-1 text-xs font-semibold text-slate-500">모델</p>
            <MarkdownBlock text={summary.method.model} />
          </div>
          <div>
            <p className="mb-1 text-xs font-semibold text-slate-500">학습 목표</p>
            <MarkdownBlock text={summary.method.training_objective} />
          </div>
        </div>
      </div>

      <div className="card p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">수학 핵심</p>
        <div className="space-y-3">
          {summary.math_core.map((item, idx) => (
            <div key={`${item.name}-${idx}`} className="rounded-lg border border-slate-200 p-3">
              <p className="font-semibold text-slate-900">{item.name}</p>
              <MarkdownBlock text={`$$${item.latex}$$`} />
              <MarkdownBlock text={item.meaning} />
            </div>
          ))}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">한계</p>
          <ul className="list-disc space-y-2 pl-5 text-sm text-slate-800">
            {summary.limitations.map((item, i) => (
              <li key={`${item}-${i}`}>
                <MarkdownBlock text={item} />
              </li>
            ))}
          </ul>
        </div>
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-brand-600">재현 체크리스트</p>
          <ul className="list-disc space-y-2 pl-5 text-sm text-slate-800">
            {summary.repro_checklist.map((item, i) => (
              <li key={`${item}-${i}`}>
                <MarkdownBlock text={item} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
