"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { deletePaper, listPapers, type PaperListItem } from "@/lib/api";

export default function HistoryPage() {
  const [papers, setPapers] = useState<PaperListItem[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async (q?: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await listPapers(100, q);
      setPapers(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "내역 조회 실패");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const sorted = useMemo(
    () =>
      [...papers].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      ),
    [papers]
  );

  return (
    <div className="space-y-4">
      <section className="card p-5">
        <h1 className="text-xl font-bold text-slate-900">요약 내역</h1>
        <p className="mt-1 text-sm text-slate-600">최신순 정렬, 제목/파일명/paper_id 검색을 지원합니다.</p>

        <div className="mt-4 flex gap-2">
          <input
            className="input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="제목, 파일명, paper_id 검색"
            onKeyDown={(e) => {
              if (e.key === "Enter") void load(search);
            }}
          />
          <button className="btn-primary" onClick={() => void load(search)}>
            검색
          </button>
          <button
            className="btn-secondary"
            onClick={() => {
              setSearch("");
              void load("");
            }}
          >
            초기화
          </button>
        </div>
      </section>

      {error && <div className="rounded-lg bg-rose-100 p-3 text-sm text-rose-800">오류: {error}</div>}
      {loading && <div className="card p-4 text-sm text-slate-700">불러오는 중...</div>}

      {!loading && sorted.length === 0 && (
        <div className="card p-5 text-sm text-slate-700">
          저장된 내역이 없습니다. <Link href="/" className="text-brand-600 underline">업로드 페이지</Link>로 이동하세요.
        </div>
      )}

      {!loading && sorted.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-100 text-slate-700">
                <tr>
                  <th className="px-4 py-3 text-left">제목/파일명</th>
                  <th className="px-4 py-3 text-left">paper_id</th>
                  <th className="px-4 py-3 text-left">요약 상태</th>
                  <th className="px-4 py-3 text-left">생성일</th>
                  <th className="px-4 py-3 text-left">동작</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((paper) => (
                  <tr key={paper.paper_id} className="border-t border-slate-200">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">
                        {paper.title || paper.file_name}
                      </div>
                      <div className="text-xs text-slate-500">{paper.file_name}</div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{paper.paper_id}</td>
                    <td className="px-4 py-3">
                      {paper.summary_exists ? (
                        <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-700">
                          요약 있음
                        </span>
                      ) : (
                        <span className="rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-700">
                          요약 없음
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-700">
                      {new Date(paper.created_at).toLocaleString("ko-KR")}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-2">
                        <Link href={`/?paper_id=${paper.paper_id}`} className="btn-secondary">
                          요약 보기
                        </Link>
                        <Link href={`/qa?paper_id=${paper.paper_id}`} className="btn-secondary">
                          QA
                        </Link>
                        <button
                          className="rounded-lg border border-rose-300 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                          onClick={async () => {
                            if (!confirm("이 내역을 삭제할까요?")) return;
                            try {
                              await deletePaper(paper.paper_id);
                              await load(search);
                            } catch (e) {
                              setError(
                                e instanceof Error ? e.message : "삭제 중 오류가 발생했습니다."
                              );
                            }
                          }}
                        >
                          삭제
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
