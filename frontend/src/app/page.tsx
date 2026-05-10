'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { setPatientContext } from '@/lib/patient-context';

const WARDS = [
  '千代田区', '中央区', '港区', '新宿区', '文京区',
  '台東区', '墨田区', '江東区', '品川区', '目黒区',
  '大田区', '世田谷区', '渋谷区', '中野区', '杉並区',
  '豊島区', '北区', '荒川区', '板橋区', '練馬区',
  '足立区', '葛飾区', '江戸川区',
];

const CARE_LEVELS = [
  { value: 0, label: '0 — 未認定 (Not yet assessed)' },
  { value: 1, label: '1 — 要介護1 (Care level 1)' },
  { value: 2, label: '2 — 要介護2 (Care level 2)' },
  { value: 3, label: '3 — 要介護3 (Care level 3)' },
  { value: 4, label: '4 — 要介護4 (Care level 4)' },
  { value: 5, label: '5 — 要介護5 (Care level 5)' },
];

const PIPELINE_STEPS = [
  { label: 'Intake',        labelJp: '受付',     icon: '📋', pause: false },
  { label: 'Discovery',     labelJp: '施設検索',  icon: '🔍', pause: false },
  { label: 'Paperwork',     labelJp: '書類作成',  icon: '📝', pause: false },
  { label: 'Human Review',  labelJp: '人間確認',  icon: '👤', pause: true  },
  { label: 'Scheduling',    labelJp: 'スケジュール', icon: '📅', pause: false },
  { label: 'Monitoring',    labelJp: 'モニタリング', icon: '📊', pause: false },
];

// Real MHLW figures
const CRISIS_STATS = [
  { number: '30%',    label: 'Population 65+',    jp: '高齢化率',     note: 'Highest globally' },
  { number: '11M',    label: 'Worker shortage',   jp: '介護人材不足',  note: 'Projected by 2040' },
  { number: '4–6 wks', label: 'Paperwork time',  jp: '申請処理期間',  note: 'Per 介護保険 application' },
];

function Spinner() {
  return (
    <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

export default function SubmitPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    needs_description: '',
    ward: '世田谷区',
    patient_age: 78,
    patient_name: '患者A',
    care_level: 2,
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeStep, setActiveStep] = useState(-1);
  const [linePct, setLinePct] = useState(0);

  // Animate pipeline steps during the ~15s processing window
  useEffect(() => {
    if (!loading) {
      setActiveStep(-1);
      setLinePct(0);
      return;
    }
    setActiveStep(0);
    setLinePct(0);

    // Steps 0→1→2→3 advancing over ~12s (redirect fires before step 3 completes)
    const timings = [
      { step: 1, line: 20, delay: 3500 },
      { step: 2, line: 40, delay: 7500 },
      { step: 3, line: 60, delay: 12500 },
    ];
    const timers = timings.map(({ step, line, delay }) =>
      setTimeout(() => { setActiveStep(step); setLinePct(line); }, delay)
    );
    return () => timers.forEach(clearTimeout);
  }, [loading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const t0 = Date.now();
    try {
      const res = await api.submit(form);
      setPatientContext(res.request_id, {
        name: form.patient_name,
        age: form.patient_age,
        ward: form.ward,
        care_level: form.care_level,
        elapsed_ms: Date.now() - t0,
      });
      router.push(`/review/${res.request_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submission failed');
      setLoading(false);
    }
  };

  const charCount = form.needs_description.length;

  return (
    <div className="max-w-2xl mx-auto hero-glow min-h-[calc(100vh-56px)] pb-12">

      {/* Hero */}
      <div className="text-center pt-10 mb-8">
        <div className="inline-flex items-center gap-2 bg-blue-50 border border-blue-100 text-blue-600 text-xs font-medium px-3 py-1 rounded-full mb-4">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
          5 autonomous AI agents · LangGraph · Groq · Pinecone
        </div>
        <h1 className="text-4xl font-bold text-slate-900 mb-1 tracking-tight">Care Request</h1>
        <p className="text-2xl font-bold text-gradient mb-3">介護申請を提出する</p>
        <p className="text-slate-400 text-sm max-w-md mx-auto leading-relaxed">
          Describe the patient&apos;s needs in Japanese or English — AI handles matching,
          paperwork, scheduling, and monitoring automatically.
        </p>
      </div>

      {/* Japan crisis stats — the problem this solves */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        {CRISIS_STATS.map((s, i) => (
          <div key={i} className="bg-white border border-slate-200 rounded-2xl p-4 text-center shadow-sm">
            <div className="text-2xl font-bold text-slate-900 leading-none mb-1">{s.number}</div>
            <div className="text-xs font-semibold text-slate-600 mb-0.5">{s.label}</div>
            <div className="text-xs text-slate-400">{s.jp}</div>
            <div className="text-xs text-slate-300 mt-1">{s.note}</div>
          </div>
        ))}
      </div>

      {/* Pipeline — animated during processing */}
      <div className="bg-white border border-slate-200 rounded-2xl p-5 mb-6 shadow-sm">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-4 text-center">
          {loading ? 'Agents Running...' : 'Agent Pipeline'}
        </p>
        <div className="relative flex items-start justify-between">
          {/* Connecting track */}
          <div className="absolute top-4 left-4 right-4 h-0.5 bg-slate-100 z-0 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-400 rounded-full transition-all duration-1000 ease-in-out"
              style={{ width: `${linePct}%` }}
            />
          </div>

          {PIPELINE_STEPS.map((step, i) => {
            const isCompleted = i < activeStep;
            const isActive    = i === activeStep && loading;
            const isPending   = activeStep === -1 || i > activeStep;

            return (
              <div key={i} className="relative z-10 flex flex-col items-center gap-1.5 flex-1">
                {/* Circle */}
                <div className="relative">
                  {/* Ping ring for active step */}
                  {isActive && (
                    <span className={`absolute inset-0 rounded-full animate-ping opacity-30 ${step.pause ? 'bg-amber-400' : 'bg-blue-400'}`} />
                  )}
                  <div className={`relative w-8 h-8 rounded-full flex items-center justify-center text-sm border-2 bg-white shadow-sm transition-all duration-500 ${
                    isCompleted
                      ? 'border-blue-500 bg-blue-500 shadow-blue-200'
                      : isActive
                        ? step.pause ? 'border-amber-400 shadow-amber-100' : 'border-blue-500 shadow-blue-100'
                        : 'border-slate-200'
                  }`}>
                    {isCompleted ? (
                      <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    ) : (
                      <span className={isActive && !step.pause ? 'text-blue-600' : isPending && !step.pause ? 'opacity-50' : ''}>
                        {step.icon}
                      </span>
                    )}
                  </div>
                </div>

                {/* Labels */}
                <div className="text-center hidden sm:block">
                  <div className={`leading-tight font-medium transition-colors duration-300 ${
                    isCompleted ? 'text-blue-600'
                    : isActive ? step.pause ? 'text-amber-600' : 'text-blue-600'
                    : 'text-slate-300'
                  }`} style={{ fontSize: '10px' }}>
                    {step.pause && isActive ? '⏸ ' : ''}{step.label}
                  </div>
                  <div className="text-slate-300" style={{ fontSize: '9px' }}>{step.labelJp}</div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit} className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">
        <div className="p-6 space-y-5">

          {/* Needs description */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-sm font-medium text-slate-700">
                Care Needs <span className="text-slate-400 font-normal">/ 患者のニーズ</span>
              </label>
              <span className={`text-xs tabular-nums transition-colors ${charCount > 0 ? 'text-blue-400' : 'text-slate-300'}`}>
                {charCount} chars
              </span>
            </div>
            <textarea
              className="w-full border border-slate-200 rounded-xl p-3 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none transition bg-slate-50 focus:bg-white"
              rows={4}
              placeholder={'週3回の訪問介護と月1回の訪問看護が必要。認知症初期。歩行困難。\n(e.g. Home visit care 3x/week + nursing 1x/month. Early dementia. Limited mobility.)'}
              value={form.needs_description}
              onChange={e => setForm(f => ({ ...f, needs_description: e.target.value }))}
              required
            />
          </div>

          {/* Ward + Care level */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Ward <span className="text-slate-400 font-normal">/ 区</span>
              </label>
              <select
                className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-slate-50 focus:bg-white transition"
                value={form.ward}
                onChange={e => setForm(f => ({ ...f, ward: e.target.value }))}
              >
                {WARDS.map(w => <option key={w} value={w}>{w}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Care Level <span className="text-slate-400 font-normal">/ 介護度</span>
              </label>
              <select
                className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-slate-50 focus:bg-white transition"
                value={form.care_level}
                onChange={e => setForm(f => ({ ...f, care_level: Number(e.target.value) }))}
              >
                {CARE_LEVELS.map(l => <option key={l.value} value={l.value}>{l.label}</option>)}
              </select>
            </div>
          </div>

          {/* Age + Name */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Patient Age <span className="text-slate-400 font-normal">/ 年齢</span>
              </label>
              <input
                type="number" min={60} max={120}
                className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-slate-50 focus:bg-white transition"
                value={form.patient_age}
                onChange={e => setForm(f => ({ ...f, patient_age: Number(e.target.value) }))}
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">
                Patient Name <span className="text-slate-400 font-normal">/ 患者名</span>
              </label>
              <input
                type="text"
                className="w-full border border-slate-200 rounded-xl px-3 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-slate-50 focus:bg-white transition"
                value={form.patient_name}
                onChange={e => setForm(f => ({ ...f, patient_name: e.target.value }))}
                placeholder="患者A"
              />
            </div>
          </div>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl p-3">
              {error}
            </div>
          )}
        </div>

        {/* Submit button — gradient, flush to card bottom */}
        <button
          type="submit"
          disabled={loading || !form.needs_description.trim()}
          className="w-full py-4 px-4 text-sm font-semibold transition-all flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
          style={{
            background: loading || !form.needs_description.trim()
              ? '#e2e8f0'
              : 'linear-gradient(135deg, #1d4ed8 0%, #0ea5e9 100%)',
            color: loading || !form.needs_description.trim() ? '#94a3b8' : 'white',
          }}
        >
          {loading ? (
            <>
              <Spinner />
              Processing care request...
            </>
          ) : (
            <>Submit Care Request <span className="opacity-75 font-normal">/ 申請を提出</span> →</>
          )}
        </button>
      </form>

      {/* Footer */}
      <div className="flex items-center justify-center gap-3 mt-5">
        {['LangGraph', 'Groq', 'Pinecone', 'Langfuse'].map((t, i) => (
          <span key={i} className="flex items-center gap-3">
            {i > 0 && <span className="text-slate-200">·</span>}
            <span className="text-xs text-slate-400">{t}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
