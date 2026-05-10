'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { api } from '@/lib/api';
import { getPatientContext, type PatientContext } from '@/lib/patient-context';
import type { ReviewResponse } from '@/types';

// ── Service metadata ──────────────────────────────────────────────────────────
const SERVICE_META: Record<string, { name: string; emoji: string; color: string }> = {
  '11': { name: '訪問介護',    emoji: '🏠', color: 'bg-blue-100 text-blue-700 border-blue-200' },
  '12': { name: '訪問入浴',    emoji: '🛁', color: 'bg-cyan-100 text-cyan-700 border-cyan-200' },
  '13': { name: '訪問看護',    emoji: '💊', color: 'bg-green-100 text-green-700 border-green-200' },
  '14': { name: '訪問リハビリ', emoji: '🏃', color: 'bg-orange-100 text-orange-700 border-orange-200' },
  '21': { name: '通所介護',    emoji: '🌅', color: 'bg-purple-100 text-purple-700 border-purple-200' },
  '22': { name: '通所リハビリ', emoji: '💪', color: 'bg-indigo-100 text-indigo-700 border-indigo-200' },
  '31': { name: '短期入所',    emoji: '🏨', color: 'bg-pink-100 text-pink-700 border-pink-200' },
  '41': { name: '特養ホーム',  emoji: '🏡', color: 'bg-rose-100 text-rose-700 border-rose-200' },
  '42': { name: '老健施設',    emoji: '🏥', color: 'bg-red-100 text-red-700 border-red-200' },
};

const CARE_LABELS = ['未認定', '要介護1', '要介護2', '要介護3', '要介護4', '要介護5'];
const CARE_COLORS = [
  'bg-slate-100 text-slate-600',
  'bg-green-100 text-green-700',
  'bg-green-100 text-green-700',
  'bg-amber-100 text-amber-700',
  'bg-amber-100 text-amber-700',
  'bg-red-100 text-red-700',
];

function parseServiceCodes(content: string): string[] {
  const match = content.match(/Service codes needed: \[([^\]]*)\]/);
  if (!match) return [];
  return match[1].split(',').map(c => c.trim().replace(/['"]/g, '')).filter(Boolean);
}

function parseConfidence(content: string): string | null {
  const match = content.match(/Ranking confidence: ([^.]+)/);
  return match ? match[1].trim() : null;
}

// ── Shared components ─────────────────────────────────────────────────────────
function Spinner({ sm }: { sm?: boolean }) {
  return (
    <svg className={`animate-spin ${sm ? 'h-4 w-4' : 'h-8 w-8'}`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function ScoreBadge({ score }: { score: number }) {
  const cls = score >= 80 ? 'bg-green-100 text-green-700' : score >= 60 ? 'bg-amber-100 text-amber-700' : 'bg-red-100 text-red-700';
  return <span className={`${cls} text-xs font-bold px-2 py-0.5 rounded-full shrink-0`}>{score}/100</span>;
}

function PatientBanner({ ctx }: { ctx: PatientContext }) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-100 to-blue-50 border border-blue-200 flex items-center justify-center text-base">
        👤
      </div>
      <div>
        <div className="font-semibold text-slate-900 text-sm leading-tight">{ctx.name}</div>
        <div className="text-xs text-slate-400">{ctx.age}歳 · {ctx.ward}</div>
      </div>
      <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${CARE_COLORS[ctx.care_level] ?? CARE_COLORS[0]}`}>
        {CARE_LABELS[ctx.care_level] ?? '不明'}
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [data, setData] = useState<ReviewResponse | null>(null);
  const [patient, setPatient] = useState<PatientContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPatient(getPatientContext(id));
    api.review(id)
      .then(setData)
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleApprove = async () => {
    setApproving(true);
    setError(null);
    try {
      await api.approve(id);
      router.push(`/dashboard/${id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Approval failed');
      setApproving(false);
    }
  };

  const handleReject = async () => {
    await api.reject(id).catch(() => null);
    router.push('/');
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 gap-3 text-blue-500">
        <Spinner />
        <p className="text-slate-500 text-sm">Loading care request...</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl p-6 text-center max-w-md mx-auto">
        <p className="font-semibold mb-1">Error loading request</p><p>{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const discoveryMsg = data.messages.find(m => m.agent === 'service_discovery');
  const paperworkMsg = data.messages.find(m => m.agent === 'paperwork');
  const detectedCodes = discoveryMsg ? parseServiceCodes(discoveryMsg.content) : [];
  const confidence = discoveryMsg ? parseConfidence(discoveryMsg.content) : null;
  const elapsedSec = patient?.elapsed_ms ? (patient.elapsed_ms / 1000).toFixed(1) : null;

  return (
    <div className="space-y-5 pb-28 fade-in">

      {/* ── Header ── */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-slate-900">Human Review</h1>
            <span className="bg-amber-100 text-amber-800 text-xs font-semibold px-2.5 py-1 rounded-full">
              ⏳ Awaiting Approval
            </span>
          </div>
          <p className="text-slate-400 text-xs">
            人間によるレビュー · <code className="bg-slate-100 px-1.5 py-0.5 rounded">{id}</code>
          </p>
        </div>
        {patient && <PatientBanner ctx={patient} />}
      </div>

      {/* ── AI attribution callout ── */}
      <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-100 rounded-2xl px-5 py-4">
        <div className="flex items-center gap-x-4 gap-y-1 flex-wrap text-sm">
          <span className="font-semibold text-blue-700">
            🤖 AI completed{elapsedSec ? ` in ${elapsedSec}s` : ''}
          </span>
          <span className="text-slate-300">·</span>
          <span className="text-slate-600">{data.forms_prefilled.length} forms pre-filled</span>
          <span className="text-slate-300">·</span>
          <span className="text-slate-600">{data.top_matches.length} facilities ranked</span>
          <span className="text-slate-300">·</span>
          <span className="font-semibold text-green-600">~4 hours of paperwork saved</span>
        </div>
      </div>

      {/* ── Detected service codes ── */}
      {detectedCodes.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
              Detected Services / 検出サービス
            </span>
            {confidence && (
              <span className="text-xs text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">
                Confidence: {confidence}
              </span>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {detectedCodes.map(code => {
              const meta = SERVICE_META[code];
              return meta ? (
                <span key={code} className={`text-xs px-3 py-1.5 rounded-full border font-medium flex items-center gap-1.5 ${meta.color}`}>
                  {meta.emoji} {code} · {meta.name}
                </span>
              ) : (
                <span key={code} className="text-xs px-2.5 py-1 rounded-full border bg-slate-100 text-slate-600 border-slate-200">
                  Code {code}
                </span>
              );
            })}
          </div>
          {paperworkMsg && (
            <p className="text-xs text-slate-400 mt-3 leading-relaxed">{paperworkMsg.content}</p>
          )}
        </div>
      )}

      {/* ── Two-column layout ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Left — Facilities */}
        <div>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
            Matched Facilities / マッチした施設
          </h2>
          <div className="space-y-3">
            {data.top_matches.map((f, i) => (
              <div key={i} className="bg-white border border-slate-200 rounded-2xl p-4 shadow-sm">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{i === 0 ? '🥇' : i === 1 ? '🥈' : '🥉'}</span>
                    <span className="font-semibold text-slate-900 text-sm">{f.name}</span>
                  </div>
                  <ScoreBadge score={f.match_score} />
                </div>
                <div className="w-full bg-slate-100 rounded-full h-1.5 mb-3">
                  <div
                    className={`h-1.5 rounded-full ${f.match_score >= 80 ? 'bg-green-500' : f.match_score >= 60 ? 'bg-amber-500' : 'bg-red-500'}`}
                    style={{ width: `${f.match_score}%` }}
                  />
                </div>
                {f.reason_en && <p className="text-xs text-slate-700 mb-1 leading-relaxed">{f.reason_en}</p>}
                {f.reason_jp && <p className="text-xs text-slate-500 leading-relaxed">{f.reason_jp}</p>}
                {f.cautions && f.cautions.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {f.cautions.map((c, j) => (
                      <p key={j} className="text-xs text-amber-700 bg-amber-50 px-2 py-1 rounded">⚠️ {c}</p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Right — Forms */}
        <div>
          <h2 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
            Pre-filled Forms / 申請書（自動入力済）
          </h2>
          <div className="space-y-3">
            {data.forms_prefilled.map((form, i) => {
              const requiredFields = new Set(form.requires_fields ?? []);
              return (
                <div key={i} className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
                  <div className="bg-slate-50 border-b border-slate-200 px-4 py-2.5 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span>📄</span>
                      <span className="font-medium text-slate-900 text-sm">{form.form_name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      {requiredFields.size > 0 && (
                        <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
                          {requiredFields.size} field{requiredFields.size > 1 ? 's' : ''} needed
                        </span>
                      )}
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${form.status === 'prefilled' ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
                        {form.status}
                      </span>
                    </div>
                  </div>
                  <div className="divide-y divide-slate-50">
                    {Object.entries(form.fields).map(([key, value]) => {
                      const isEmpty = value === null || value === undefined || value === '';
                      const needsManual = requiredFields.has(key);
                      return (
                        <div key={key} className={`flex items-center px-4 py-2 text-xs ${needsManual ? 'bg-amber-50' : ''}`}>
                          <span className={`w-36 shrink-0 ${needsManual ? 'text-amber-700 font-medium' : 'text-slate-400'}`}>
                            {needsManual && '✏️ '}{key}
                          </span>
                          <span className={isEmpty ? 'text-amber-500 italic' : 'text-slate-900 font-medium'}>
                            {isEmpty ? '— enter manually' : String(value)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {form.notes_en && (
                    <div className="bg-blue-50 border-t border-blue-100 px-4 py-2 text-xs text-blue-700">
                      ℹ️ {form.notes_en}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg p-3">{error}</div>
      )}

      {/* ── Sticky action bar ── */}
      <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-slate-200 shadow-lg no-print"
        style={{ background: 'rgba(255,255,255,0.95)', backdropFilter: 'blur(12px)' }}>
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 mr-auto">
            <span className="text-xs text-slate-400">Request</span>
            <code className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded text-xs">{id}</code>
            <span className="text-xs text-slate-300">·</span>
            <span className="text-xs text-slate-500">{data.forms_prefilled.length} form(s) · {data.top_matches.length} match(es)</span>
          </div>
          <button
            onClick={handleReject}
            disabled={approving}
            className="flex-1 sm:flex-none sm:w-32 border border-slate-200 text-slate-600 font-semibold py-2.5 rounded-xl hover:bg-slate-50 transition-colors text-sm disabled:opacity-50"
          >
            ❌ Reject
          </button>
          <button
            onClick={handleApprove}
            disabled={approving}
            className="flex-1 sm:flex-none sm:w-72 text-white font-semibold py-2.5 rounded-xl transition-all flex items-center justify-center gap-2 text-sm disabled:opacity-50"
            style={{ background: approving ? '#cbd5e1' : 'linear-gradient(135deg, #16a34a, #15803d)' }}
          >
            {approving ? (
              <><Spinner sm /> Generating care plan...</>
            ) : (
              '✅ Approve & Generate Care Plan / 承認'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
