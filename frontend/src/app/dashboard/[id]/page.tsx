'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { api } from '@/lib/api';
import { getPatientContext, type PatientContext } from '@/lib/patient-context';
import type { ScheduleResponse, MonitoringResponse } from '@/types';

// ── Service metadata ──────────────────────────────────────────────────────────
const SERVICE_ROW_COLOR: Record<string, string> = {
  '11': 'border-l-blue-400',  '12': 'border-l-cyan-400',
  '13': 'border-l-green-500', '14': 'border-l-orange-400',
  '21': 'border-l-purple-400','22': 'border-l-indigo-400',
  '31': 'border-l-pink-400',
};
const SERVICE_EMOJI: Record<string, string> = {
  '11': '🏠', '12': '🛁', '13': '💊', '14': '🏃',
  '21': '🌅', '22': '💪', '31': '🏨',
};
const CARE_LABELS = ['未認定', '要介護1', '要介護2', '要介護3', '要介護4', '要介護5'];
const CARE_COLORS = [
  'bg-slate-100 text-slate-600', 'bg-green-100 text-green-700',
  'bg-green-100 text-green-700', 'bg-amber-100 text-amber-700',
  'bg-amber-100 text-amber-700', 'bg-red-100 text-red-700',
];

// ── Animated circular score gauge ────────────────────────────────────────────
function ScoreGauge({ score }: { score: number }) {
  const [display, setDisplay] = useState(0);

  useEffect(() => {
    const duration = 1400;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - t, 3); // cubic ease-out
      setDisplay(score * eased);
      if (t < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [score]);

  const r = 44;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - display / 100);
  const hex = score >= 80 ? '#16a34a' : score >= 60 ? '#d97706' : '#dc2626';
  const trackHex = score >= 80 ? '#dcfce7' : score >= 60 ? '#fef3c7' : '#fee2e2';

  return (
    <svg width="110" height="110" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r={r} fill="none" stroke={trackHex} strokeWidth="10" />
      <circle cx="60" cy="60" r={r} fill="none" stroke={hex} strokeWidth="10"
        strokeDasharray={circ} strokeDashoffset={offset}
        strokeLinecap="round" transform="rotate(-90 60 60)"
      />
      <text x="60" y="56" textAnchor="middle" fontSize="24" fontWeight="bold" fill={hex}>
        {Math.round(display)}
      </text>
      <text x="60" y="73" textAnchor="middle" fontSize="11" fill="#94a3b8">/ 100</text>
    </svg>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function Spinner() {
  return (
    <svg className="animate-spin h-8 w-8 text-blue-500" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function addDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toLocaleDateString('ja-JP', { year: 'numeric', month: 'long', day: 'numeric' });
}

function scoreStyle(score: number) {
  if (score >= 80) return { text: 'text-green-600', bg: 'bg-green-50', border: 'border-green-200', bar: 'bg-green-500' };
  if (score >= 60) return { text: 'text-amber-500', bg: 'bg-amber-50', border: 'border-amber-200', bar: 'bg-amber-400' };
  return               { text: 'text-red-500',   bg: 'bg-red-50',   border: 'border-red-200',   bar: 'bg-red-500' };
}
function riskStyle(level: string) {
  if (level === 'low')    return { emoji: '🟢', label: 'Low',    text: 'text-green-700', bg: 'bg-green-50',  border: 'border-green-200',  bar: 'bg-green-500' };
  if (level === 'medium') return { emoji: '🟡', label: 'Medium', text: 'text-amber-600', bg: 'bg-amber-50',  border: 'border-amber-200',  bar: 'bg-amber-400' };
  return                         { emoji: '🔴', label: 'High',   text: 'text-red-700',   bg: 'bg-red-50',    border: 'border-red-200',    bar: 'bg-red-500'   };
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
      <span className="bg-green-100 text-green-800 text-xs font-semibold px-2.5 py-1 rounded-full">
        ✅ Complete
      </span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const [schedule, setSchedule]   = useState<ScheduleResponse | null>(null);
  const [monitoring, setMonitoring] = useState<MonitoringResponse | null>(null);
  const [patient, setPatient]     = useState<PatientContext | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [copied, setCopied]       = useState(false);

  useEffect(() => {
    setPatient(getPatientContext(id));
    Promise.all([api.schedule(id), api.monitoring(id)])
      .then(([s, m]) => { setSchedule(s); setMonitoring(m); })
      .catch(err => setError(err.message))
      .finally(() => setLoading(false));
  }, [id]);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(window.location.href).catch(() => null);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, []);

  const handlePrint = () => window.print();

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 gap-3">
        <Spinner />
        <p className="text-slate-500 text-sm">Building care plan dashboard...</p>
      </div>
    );
  }
  if (error || !schedule || !monitoring) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl p-6 text-center max-w-md mx-auto">
        <p className="font-semibold mb-1">Error loading dashboard</p>
        <p>{error ?? 'Unknown error'}</p>
      </div>
    );
  }

  const score = monitoring.care_plan_score ?? 0;
  const sc = scoreStyle(score);
  const rs = riskStyle(monitoring.risk_level);
  const reviewDate = addDays(monitoring.next_review_days);

  return (
    <div className="space-y-6 fade-in">

      {/* ── Header ── */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Care Plan Dashboard</h1>
          <p className="text-slate-400 text-xs mt-0.5">
            介護計画ダッシュボード · <code className="bg-slate-100 px-1.5 py-0.5 rounded">{id}</code>
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 no-print">
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 px-3 py-2 rounded-xl hover:bg-slate-50 transition-colors"
          >
            {copied ? '✅ Copied!' : '🔗 Copy Link'}
          </button>
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 text-xs font-medium text-white px-3 py-2 rounded-xl transition-colors"
            style={{ background: 'linear-gradient(135deg, #1d4ed8, #0ea5e9)' }}
          >
            🖨️ Export PDF
          </button>
        </div>
      </div>

      {/* Patient banner */}
      {patient && <PatientBanner ctx={patient} />}

      {/* ── KPI row ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">

        {/* Score */}
        <div className={`border rounded-2xl overflow-hidden flex flex-col ${sc.bg} ${sc.border}`}>
          <div className={`h-1 w-full ${sc.bar}`} />
          <div className="p-5 flex flex-col items-center flex-1">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2 self-start">
              Care Plan Score
            </div>
            <ScoreGauge score={score} />
          </div>
        </div>

        {/* Risk */}
        <div className={`border rounded-2xl overflow-hidden ${rs.bg} ${rs.border}`}>
          <div className={`h-1 w-full ${rs.bar}`} />
          <div className="p-5">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Risk Level</div>
            <div className="text-5xl mb-2">{rs.emoji}</div>
            <div className={`text-xl font-bold ${rs.text}`}>{rs.label}</div>
            <div className="text-xs text-slate-400 mt-1">Next review: {reviewDate}</div>
          </div>
        </div>

        {/* Visits */}
        <div className="bg-blue-50 border border-blue-200 rounded-2xl overflow-hidden">
          <div className="h-1 w-full bg-blue-500" />
          <div className="p-5">
            <div className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">Visits / Week</div>
            <div className="text-5xl font-bold text-blue-600">{schedule.total_visits_per_week}</div>
            <div className="text-xs text-blue-500 mt-2 leading-relaxed">{schedule.schedule_summary_en}</div>
            <div className="text-xs text-blue-400 mt-0.5">{schedule.schedule_summary_jp}</div>
          </div>
        </div>
      </div>

      {/* ── Alerts ── */}
      {monitoring.monitoring_alerts.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4">
          <h3 className="text-sm font-semibold text-amber-800 mb-2">⚠️ Monitoring Alerts</h3>
          <ul className="space-y-1">
            {monitoring.monitoring_alerts.map((a, i) => (
              <li key={i} className="text-sm text-amber-700">• {a}</li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Assessment ── */}
      <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
        <h2 className="font-semibold text-slate-900 mb-3">
          Care Plan Assessment
          <span className="text-slate-400 font-normal text-sm ml-2">/ 介護計画評価</span>
        </h2>
        <p className="text-sm text-slate-700 leading-relaxed mb-1.5">{monitoring.overall_assessment_en}</p>
        <p className="text-sm text-slate-400 leading-relaxed">{monitoring.overall_assessment_jp}</p>

        {monitoring.recommendations_en.length > 0 && (
          <div className="mt-4 pt-4 border-t border-slate-100">
            <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-3">
              Recommendations / 推奨事項
            </h3>
            <div className="space-y-3">
              {monitoring.recommendations_en.map((r, i) => (
                <div key={i} className="flex gap-3">
                  <span className="text-blue-500 font-bold text-sm shrink-0 w-5">{i + 1}.</span>
                  <div>
                    <p className="text-sm text-slate-700 leading-relaxed">{r}</p>
                    {monitoring.recommendations_jp[i] && (
                      <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{monitoring.recommendations_jp[i]}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="mt-4 text-xs text-slate-400">
          Next review recommended: {reviewDate}
        </div>
      </div>

      {/* ── 4-Week Visit Calendar ── */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between flex-wrap gap-3">
          <div>
            <h2 className="font-semibold text-slate-900">
              4-Week Visit Schedule
              <span className="text-slate-400 font-normal text-sm ml-2">/ 4週間訪問スケジュール</span>
            </h2>
            <p className="text-xs text-slate-400 mt-0.5">{schedule.schedule_summary_jp}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {Array.from(new Set(schedule.scheduled_visits.map(v => v.service_code))).map(code => (
              <span key={code} className={`text-xs px-2 py-0.5 rounded border-l-4 bg-slate-50 text-slate-600 ${SERVICE_ROW_COLOR[code] ?? 'border-l-slate-300'}`}>
                {SERVICE_EMOJI[code] ?? '•'} {code}
              </span>
            ))}
          </div>
        </div>

        {schedule.weeks.map(week => (
          <div key={week.week}>
            <div className="bg-slate-50 px-5 py-2 border-b border-slate-100">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">Week {week.week}</span>
            </div>
            {week.visits.map((v, i) => (
              <div key={i} className={`flex items-center px-5 py-3 border-b border-slate-50 hover:bg-slate-50 transition-colors text-sm border-l-4 ${SERVICE_ROW_COLOR[v.service_code] ?? 'border-l-slate-300'}`}>
                <span className="w-24 shrink-0 text-xs text-slate-400">{v.date}</span>
                <span className="w-8 shrink-0 text-xs font-medium text-slate-500">{v.day_jp}</span>
                <span className="w-14 shrink-0 font-semibold text-slate-900">{v.time}</span>
                <span className="flex-1 text-slate-800">
                  {SERVICE_EMOJI[v.service_code] ?? ''} {v.service_name}
                  <span className="text-slate-400 mx-1.5 text-xs">·</span>
                  <span className="text-xs text-slate-500">{v.service_name_en}</span>
                </span>
                <span className="text-xs text-slate-400 shrink-0">{v.duration_min} min</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* ── LINE Reminder Cards ── */}
      {schedule.line_reminders.length > 0 && (
        <div>
          <h2 className="font-semibold text-slate-900 mb-3">
            LINE Reminder Templates
            <span className="text-slate-400 font-normal text-sm ml-2">/ LINEリマインダーテンプレート</span>
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {schedule.line_reminders.map((r, i) => (
              <div key={i} className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
                <div className="px-4 py-2.5 flex items-center gap-2" style={{ backgroundColor: '#06C755' }}>
                  <span className="text-white text-xs font-black tracking-wide">LINE</span>
                  <span className="text-white text-base">{SERVICE_EMOJI[r.service_code] ?? ''}</span>
                  <span className="text-white text-xs font-medium opacity-95">{r.service_name}</span>
                  <span className="ml-auto text-white text-xs opacity-70 capitalize">{r.trigger.replace('_', ' ')}</span>
                </div>
                <div className="p-4">
                  <div className="bg-slate-100 rounded-2xl rounded-tl-sm px-4 py-3 max-w-xs">
                    <p className="text-sm text-slate-900 whitespace-pre-line leading-relaxed">{r.message_jp}</p>
                  </div>
                  <div className="flex gap-2 mt-3 flex-wrap">
                    {r.quick_reply_options.map((opt, j) => (
                      <span key={j} className="text-xs px-3 py-1 rounded-full border font-medium"
                        style={{ color: '#06C755', borderColor: '#06C755', backgroundColor: 'rgba(6,199,85,0.06)' }}>
                        {opt}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="bg-slate-50 px-4 py-2 border-t border-slate-100 text-xs text-slate-400 truncate">
                  {r.message_en.slice(0, 70)}…
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Footer ── */}
      <div className="text-center pt-4 pb-2 no-print">
        <Link href="/" className="text-sm text-blue-600 hover:text-blue-700 font-medium transition-colors">
          ← Submit another care request / 新しい申請を提出する
        </Link>
      </div>
    </div>
  );
}
