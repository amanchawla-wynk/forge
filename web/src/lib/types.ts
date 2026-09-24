// Mirrors the Pydantic models in `src/forge/score/engine.py`,
// `src/forge/score/planner.py`, `src/forge/score/report.py`, and
// `src/forge_dashboard/models.py`. Keep in sync with those files.

// Provider "cursor" is not an LLM provider: it authenticates to Cursor's
// Cloud Agents API with a Cursor-issued key (cursor.com/dashboard/api), not
// a provider API key. See docs/DECISIONS.md D-034.
export type Provider = "anthropic" | "openai" | "gemini" | "cursor";

export interface LLMConfig {
  provider: Provider;
  model: string;
  api_key: string;
}

export const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: "Anthropic (Claude)",
  openai: "OpenAI",
  gemini: "Google (Gemini)",
  cursor: "Cursor (Cloud Agents)",
};

// Current flagship/latest lineups as published by each provider. Kept short
// on purpose; the model field always accepts a custom id too.
export const PROVIDER_DEFAULT_MODELS: Record<Provider, string[]> = {
  anthropic: [
    "claude-opus-5-5",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-fable-5-1",
  ],
  openai: ["gpt-6-astra", "gpt-6-sol", "gpt-6-luna"],
  gemini: [
    "gemini-3.8-flash",
    "gemini-3.1-pro",
    "gemini-3.5-flash-lite",
    "gemini-3.1-deep-think",
  ],
  // No fixed list: Cursor resolves your account/team default model when
  // left blank. Enter an id from `GET /v1/models` (Cursor API) to pin one.
  cursor: [],
};

export const PROVIDER_MODEL_OPTIONAL: Record<Provider, boolean> = {
  anthropic: false,
  openai: false,
  gemini: false,
  cursor: true,
};

export type Verdict = "present" | "partial" | "absent" | "not_applicable";

export type Consumer =
  | "engineering"
  | "design"
  | "qa"
  | "data"
  | "risk"
  | "leadership"
  | "gtm";

export const CONSUMER_LABELS: Record<Consumer, string> = {
  engineering: "Engineering",
  design: "Design",
  qa: "QA",
  data: "Data",
  risk: "Risk / Legal / Privacy",
  leadership: "Leadership",
  gtm: "Go-To-Market",
};

export interface SupplementalAnswer {
  criterion_id: string;
  answer: string;
}

export interface ProductContextTerm {
  term: string;
  meaning: string;
  source_ref?: string | null;
}

export interface CriterionResult {
  criterion_id: string;
  name: string;
  verdict: Verdict;
  weight: number;
  credit: number;
  consumers: Consumer[];
  missing: string[];
  rationale: string;
  agreement: number;
  gate_triggered: boolean;
}

export interface ConsumerReadiness {
  consumer: Consumer;
  score: number;
  blocking: string[];
}

export interface Assessment {
  rubric_id: string;
  rubric_version: string;
  calibration_status: string;
  raw_score: number;
  band: string;
  band_label: string;
  uncapped_band: string;
  gates_failed: string[];
  confidence: number;
  criteria: CriterionResult[];
  consumers: ConsumerReadiness[];
}

export interface Question {
  criterion_id: string;
  criterion_name: string;
  target_field: string | null;
  question: string;
  missing_fields: string[];
  answer_requirements: string[];
  is_gate: boolean;
  band_if_answered: string;
  unblocks_consumers: string[];
}

export interface GapRecord {
  criterion_id: string;
  criterion_name: string;
  verdict: Verdict;
  missing_fields: string[];
  affected_consumers: string[];
  gate_triggered: boolean;
  rationale: string;
}

export interface NarrativeReport {
  headline: string;
  summary: string;
  key_gaps: string[];
  gaps: GapRecord[];
  consumer_gaps: Record<string, string[]>;
  blocked_consumers: string[];
  next_step: string | null;
  confidence_note: string;
}

export interface AssessmentResponse {
  source_path: string;
  report: NarrativeReport;
  assessment: Assessment;
  next_question: Question | null;
  supplemental_answers: SupplementalAnswer[];
  run_count: number;
  expected_run_count: number;
  disputed_criteria: string[];
  recommended_additional_runs: number;
  client_models: string[];
  product_context: ProductContextTerm[];
  warnings: string[];
  document_id: string;
  extraction_errors: string[];
}

export interface UploadResponse {
  document_id: string;
  filename: string;
  source_type: string;
}

export const BAND_STYLES: Record<
  string,
  { label: string; className: string }
> = {
  not_a_prd: {
    label: "Not a PRD",
    className: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-900",
  },
  needs_work: {
    label: "Needs work",
    className:
      "bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-950 dark:text-orange-300 dark:border-orange-900",
  },
  ready_with_gaps: {
    label: "Ready with gaps",
    className:
      "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950 dark:text-amber-300 dark:border-amber-900",
  },
  ready_to_build: {
    label: "Ready to build",
    className:
      "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-300 dark:border-emerald-900",
  },
};

export const VERDICT_STYLES: Record<
  Verdict,
  { label: string; className: string }
> = {
  present: {
    label: "Present",
    className:
      "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  },
  partial: {
    label: "Partial",
    className:
      "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  },
  absent: {
    label: "Absent",
    className: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  },
  not_applicable: {
    label: "N/A",
    className:
      "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400",
  },
};
