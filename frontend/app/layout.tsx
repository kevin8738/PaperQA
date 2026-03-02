import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "PaperQA",
  description: "한국어 논문 요약/QA"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <div className="min-h-screen bg-gradient-to-b from-brand-50 via-slate-50 to-slate-100">
          <header className="border-b border-slate-200 bg-white/90 backdrop-blur">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4">
              <Link href="/" className="text-lg font-bold text-brand-900">
                PaperQA
              </Link>
              <nav className="flex gap-2">
                <Link href="/" className="btn-secondary">
                  업로드/요약
                </Link>
                <Link href="/qa" className="btn-secondary">
                  QA
                </Link>
                <Link href="/history" className="btn-secondary">
                  요약 내역
                </Link>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
