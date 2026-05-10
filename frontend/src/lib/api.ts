import type {
  SubmitResponse,
  ReviewResponse,
  ApprovalResponse,
  ScheduleResponse,
  MonitoringResponse,
} from '@/types';

const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export interface SubmitPayload {
  needs_description: string;
  ward: string;
  patient_age: number;
  patient_name?: string;
  care_level?: number;
}

export const api = {
  submit: (data: SubmitPayload) =>
    req<SubmitResponse>('/care-request', { method: 'POST', body: JSON.stringify(data) }),

  review: (id: string) =>
    req<ReviewResponse>(`/care-request/${id}/review`),

  approve: (id: string) =>
    req<ApprovalResponse>(`/care-request/${id}/approve`, { method: 'POST' }),

  reject: (id: string) =>
    req<ApprovalResponse>(`/care-request/${id}/reject`, { method: 'POST' }),

  schedule: (id: string) =>
    req<ScheduleResponse>(`/care-request/${id}/schedule`),

  monitoring: (id: string) =>
    req<MonitoringResponse>(`/care-request/${id}/monitoring`),
};
