export interface PatientContext {
  name: string;
  age: number;
  ward: string;
  care_level: number;
  elapsed_ms?: number;
}

const key = (id: string) => `kaigo_patient_${id}`;

export function setPatientContext(requestId: string, data: PatientContext): void {
  if (typeof window === 'undefined') return;
  sessionStorage.setItem(key(requestId), JSON.stringify(data));
}

export function getPatientContext(requestId: string): PatientContext | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(key(requestId));
    return raw ? (JSON.parse(raw) as PatientContext) : null;
  } catch {
    return null;
  }
}
