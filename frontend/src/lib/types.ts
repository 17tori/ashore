export interface User {
  id: string;
  email: string;
  display_name: string;
  timezone: string;
  ai_external_consent: boolean;
  settings: Record<string, any>;
}

export interface Vacancy {
  id: string;
  source: string;
  is_sample: boolean;
  hh_id: string | null;
  url: string | null;
  apply_url: string | null;
  title: string;
  employer_name: string;
  area_name: string | null;
  salary_from: number | null;
  salary_to: number | null;
  salary_currency: string | null;
  work_formats: string[];
  employment_type: string | null;
  experience_id: string | null;
  key_skills: string[];
  published_at: string | null;
  archived: boolean;
  has_test: boolean;
  response_letter_required: boolean;
  description_text?: string;
}

export interface Match {
  id: string;
  vacancy: Vacancy;
  score: number | null;
  decision: string | null;
  ai_decision: string | null;
  user_decision: string | null;
  matched_skills: string[];
  missing_skills: string[];
  risks: string[];
  salary_match: string;
  experience_match: string;
  reasoning_summary: string;
  recommended_resume_id: string | null;
  search_profile_id: string | null;
  analysis_source: string;
  hidden: boolean;
  times_seen: number;
  discovered_at: string;
  application: { id: string; status: string } | null;
  analysis?: Record<string, any>;
}

export interface LetterIssue {
  code: string;
  severity: "error" | "warning";
  message: string;
}

export interface Letter {
  id: string;
  text: string;
  template_kind: string;
  tone: string;
  generator: string;
  validation: { issues?: LetterIssue[]; blocking?: boolean };
  edited_by_user: boolean;
}

export interface Application {
  id: string;
  status: string;
  channel: string | null;
  confirmed_by: string | null;
  vacancy: Vacancy;
  resume_id: string | null;
  match_id: string | null;
  attempts: number;
  sent_at: string | null;
  status_changed_at: string | null;
  last_error: string | null;
  notes: string;
  letter: Letter | null;
  created_at: string;
  events?: { from: string | null; to: string; actor: string; note: string; at: string }[];
}

export interface ApproveResult {
  mode: "api" | "manual";
  status?: string;
  detail?: string;
  reason?: string;
  apply_url?: string | null;
  letter_text?: string;
  application: Application;
}

export interface Resume {
  id: string;
  title: string;
  source: string;
  version: number;
  file_name: string | null;
  is_primary: boolean;
  profile_confirmed: boolean;
  quality: { score?: number; recommendations?: string[]; checks?: Record<string, boolean> };
  hh_resume_id: string | null;
  hh_status: string | null;
  created_at: string;
  skills_count: number;
  level: string | null;
  profile?: CandidateProfile;
  visibility?: Visibility;
}

export interface Fact {
  source: string;
  confirmed: boolean;
}

export interface CandidateProfile {
  headline: string;
  summary: string;
  desired_positions: string[];
  skills: ({ name: string; years: number | null } & Fact)[];
  experience: ({ company: string; title: string; start: string | null; end: string | null; current: boolean; description: string; technologies: string[]; commercial: boolean } & Fact)[];
  education: ({ institution: string; degree: string; field: string; year: number | null } & Fact)[];
  projects: ({ name: string; description: string; technologies: string[]; url: string | null } & Fact)[];
  certificates: ({ name: string; year: number | null } & Fact)[];
  languages: { name: string; level: string }[];
  achievements: string[];
  level: string;
  total_experience_months: number;
  has_commercial_experience: boolean;
  min_salary: number | null;
  currency: string;
  work_formats: string[];
  employment_types: string[];
  assumptions: { field: string; value: string; reason: string }[];
  [key: string]: unknown;
}

export interface Visibility {
  linked_to_hh: boolean;
  hh_status: string | null;
  can_publish: boolean | null;
  api_publish: { status: string; detail: string };
  mode: "api" | "reminders";
  last_platform_confirmed_at: string | null;
  last_user_marked_at: string | null;
  next_allowed_at: string | null;
  cooldown_active: boolean;
  paid_operations: string;
  manual_url: string;
}

export interface SearchProfile {
  id: string;
  name: string;
  is_active: boolean;
  resume_id: string | null;
  positions: string[];
  skills: string[];
  areas: { id: string | null; name: string }[];
  work_formats: string[];
  employment_types: string[];
  experience: string[];
  salary_min: number | null;
  currency: string;
  only_with_salary: boolean;
  excluded_employers: { id: string | null; name: string }[];
  excluded_keywords: string[];
  period_days: number;
  eligible_threshold: number;
  review_threshold: number;
  daily_apply_limit: number;
  weights: Record<string, number>;
  letter_template: string;
  letter_tone: string;
  letter_length: string;
  letter_mode: string;
  search_interval_minutes: number;
  last_run_at: string | null;
}

export interface Capability {
  status: "verified" | "conditional" | "unavailable" | "unknown";
  detail: string;
  checked_at: string | null;
}

export interface Overview {
  found: number;
  suitable: number;
  suitable_rate: number | null;
  sent: number;
  sent_platform_confirmed: number;
  viewed: number;
  invitations: number;
  rejections: number;
  invitation_rate: number | null;
  avg_sent_score: number | null;
  duplicates: number;
  api_calls: number;
  api_errors: number;
  ai_cost: number;
  paid_hh_cost: number;
}

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string;
  payload: Record<string, any>;
  read: boolean;
  created_at: string;
}

export interface AutomationState {
  mode: "manual" | "assisted" | "auto";
  paused: boolean;
  paused_reason: string | null;
  allowed_resume_ids: string[];
  allowed_positions: string[];
  min_score: number;
  salary_min: number | null;
  employment_types: string[];
  excluded_employers: { id: string | null; name: string }[];
  daily_limit: number;
  letter_rules: Record<string, any>;
  stop_conditions: Record<string, any>;
  apply_windows: { days: number[]; start: string; end: string }[];
  confirmed_at: string | null;
  ai_monthly_budget: number;
  rules_hash: string;
  auto_active: boolean;
  auto_confirmed_for_current_rules: boolean;
  auto_problems: string[];
  sent_today: number;
  in_apply_window: boolean;
  hard_daily_cap: number;
}
