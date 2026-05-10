import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import Link from 'next/link';
import './globals.css';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: '介護ナビゲーター — Kaigo Navigator',
  description: 'Autonomous multi-agent eldercare coordination system for Japan',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body className={`${inter.className} min-h-screen bg-slate-50`}>
        {/* Glassmorphism header */}
        <header
          className="sticky top-0 z-50 border-b border-slate-200/80"
          style={{ background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(12px)' }}
        >
          <div className="max-w-5xl mx-auto px-4 h-14 flex items-center justify-between">
            <Link href="/" className="flex items-center gap-3 hover:opacity-75 transition-opacity">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-600 to-blue-400 flex items-center justify-center shadow-sm shadow-blue-200">
                <span className="text-white text-base">🏥</span>
              </div>
              <div>
                <div className="font-bold text-slate-900 text-sm leading-tight tracking-tight">
                  介護ナビゲーター
                </div>
                <div className="text-xs text-slate-400 leading-tight">Kaigo Navigator</div>
              </div>
            </Link>

            <span className="hidden sm:inline text-xs text-slate-500 bg-slate-100 border border-slate-200 px-3 py-1 rounded-full">
              Autonomous Eldercare AI · Japan
            </span>
          </div>
        </header>

        <main className="max-w-5xl mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
