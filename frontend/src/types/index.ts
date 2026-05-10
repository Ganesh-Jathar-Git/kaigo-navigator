export interface TopMatch {
  rank?: number;
  id?: string;
  name: string;
  match_score: number;
  reason_en?: string;
  reason_jp?: string;
  cautions?: string[];
  address?: string;
  phone?: string;
}

export interface PrefillForm {
  form_name: string;
  fields: Record<string, string | number | null>;
  status: string;
  requires_fields?: string[];
  notes_en?: string;
  notes_jp?: string;
}

export interface Visit {
  date: string;
  day_jp: string;
  service_code: string;
  service_name: string;
  service_name_en: string;
  time: string;
  duration_min: number;
  facility: string;
  notes?: string;
}

export interface LineReminder {
  service_code: string;
  service_name: string;
  trigger: string;
  message_jp: string;
  message_en: string;
  quick_reply_options: string[];
}

export interface Week {
  week: number;
  visits: Visit[];
}

export interface Message {
  agent: string;
  content: string;
}

export interface SubmitResponse {
  request_id: string;
  status: string;
  elapsed_ms: number;
  ward: string;
  service_codes_identified: string[];
  top_matches: TopMatch[];
  forms_required: string[];
  forms_prefilled: PrefillForm[];
  messages: Message[];
  error: string | null;
}

export interface ReviewResponse {
  request_id: string;
  status: string;
  forms_required: string[];
  forms_prefilled: PrefillForm[];
  top_matches: TopMatch[];
  messages: Message[];
}

export interface ApprovalResponse {
  request_id: string;
  status: string;
  message: string;
  messages: Message[];
  care_plan_score: number | null;
  scheduled_visits_count: number | null;
  line_reminders_count: number | null;
}

export interface ScheduleResponse {
  request_id: string;
  status: string;
  scheduled_visits: Visit[];
  line_reminders: LineReminder[];
  schedule_summary_en: string;
  schedule_summary_jp: string;
  total_visits_per_week: number;
  weeks: Week[];
}

export interface MonitoringResponse {
  request_id: string;
  status: string;
  care_plan_score: number | null;
  monitoring_alerts: string[];
  risk_level: string;
  overall_assessment_en: string;
  overall_assessment_jp: string;
  recommendations_en: string[];
  recommendations_jp: string[];
  next_review_days: number;
}
