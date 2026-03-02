"use client";

import type { PaperListItem } from "@/lib/api";

type Props = {
  papers: PaperListItem[];
  selectedPaperId: string;
  onSelect: (paperId: string) => void;
};

export default function PaperPicker({ papers, selectedPaperId, onSelect }: Props) {
  return (
    <div className="card p-4">
      <p className="mb-2 text-sm font-semibold text-slate-700">논문 선택</p>
      <select
        className="input"
        value={selectedPaperId}
        onChange={(e) => onSelect(e.target.value)}
      >
        <option value="">선택하세요</option>
        {papers.map((paper) => (
          <option key={paper.paper_id} value={paper.paper_id}>
            {paper.title || paper.file_name} ({paper.summary_exists ? "요약 있음" : "요약 없음"})
          </option>
        ))}
      </select>
    </div>
  );
}
