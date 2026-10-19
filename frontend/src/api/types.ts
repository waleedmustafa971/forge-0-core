export type InvestigationStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';
export type Verdict = 'verified_fix' | 'no_verified_fix' | 'inconclusive' | 'no_failure_observed';

export interface RuntimeProfile {
  runtime: 'node' | 'python' | 'unknown';
  runner: string | null;
  test_targets: string[];
  image: string | null;
  notes: string[];
}

export interface RepositoryProfile {
  file_count: number;
  languages: Record<string, number>;
  frameworks: string[];
  package_manager: string | null;
  dependencies: Record<string, string>;
  source_files: string[];
  test_files: string[];
  runtime: RuntimeProfile;
}

export interface ScanTest {
  name: string;
  file: string | null;
  status: 'passed' | 'failed' | 'skipped' | 'todo';
  error: string;
}

export interface ScanResult {
  scanned_at: string;
  exit_code: number | null;
  duration_ms: number;
  command: string[];
  image: string;
  total: number;
  passed: number;
  failed: number;
  tests: ScanTest[];
}

export interface Repository {
  id: string;
  name: string;
  source_type: 'demo' | 'local' | 'git';
  source: string;
  commit_sha: string | null;
  profile: RepositoryProfile;
  last_scan: ScanResult | null;
  created_at: string;
}

export interface Usage {
  model_calls?: number;
  experiments?: number;
  sandbox_runs?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  tokens_estimated?: boolean;
  estimated_cost_usd?: number;
  elapsed_s?: number;
}

export interface Budget {
  max_model_calls?: number;
  max_experiments?: number;
  max_repair_attempts?: number;
  max_experiment_rounds?: number;
  time_budget_s?: number;
}

export interface Investigation {
  id: string;
  repository_id: string;
  title: string;
  symptom: string;
  target_test: string | null;
  mode: 'forge' | 'baseline';
  status: InvestigationStatus;
  phase: string;
  active_agent: string | null;
  verdict: Verdict | null;
  provider: string;
  model: string;
  simulated: boolean;
  provider_note: string | null;
  budget: Budget;
  usage: Usage;
  summary: Record<string, unknown> | null;
  root_cause: string | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface FailureObservation {
  test_name: string;
  file: string | null;
  error: string | null;
  error_name: string | null;
  failure_type: string | null;
  stack_frames: string[];
  implicated_files: string[];
}

export interface InvestigationReportData {
  repository: string;
  file_count: number;
  languages: Record<string, number>;
  frameworks: string[];
  runtime: RuntimeProfile;
  observed_failures: FailureObservation[];
  target_failure: FailureObservation | null;
  reproduction_confirmed: boolean | null;
  relevant_files: { path: string; reason: string; truncated: boolean }[];
  notes: string[];
}

export interface InvestigationDetail extends Investigation {
  investigation_report: InvestigationReportData | null;
  repository_name: string | null;
  counts: Record<string, number>;
}

export interface ForgeEvent {
  id: number;
  investigation_id: string;
  ts: string;
  agent: string;
  type: string;
  message: string;
  data: Record<string, unknown>;
  investigation_title?: string | null;
}

export interface BeliefStep {
  experiment: string;
  before: number;
  after: number;
  matched: boolean | null;
  reason: string | null;
}

export interface Hypothesis {
  id: string;
  key: string;
  title: string;
  explanation: string;
  suspected_locations: string[];
  supporting_evidence: string[];
  contradicting_evidence: string[];
  prior: number;
  confidence: number;
  status: 'open' | 'supported' | 'weakened' | 'refuted' | 'confirmed';
  rank: number;
  history: BeliefStep[];
}

export interface Prediction {
  hypothesis: string;
  outcome: 'pass' | 'fail';
  output_contains?: string | null;
  rationale?: string;
}

export interface PredictionEvaluation {
  hypothesis: string;
  predicted: string;
  output_contains: string | null;
  observed: string;
  matched: boolean;
  reason: string;
}

export interface TestCase {
  name: string;
  file: string | null;
  status: 'passed' | 'failed' | 'skipped' | 'todo';
  duration_ms: number | null;
  error: string | null;
  error_name: string | null;
  failure_type: string | null;
}

export interface ExecutionResult {
  runner: string;
  image: string;
  command: string[];
  exit_code: number | null;
  timed_out: boolean;
  duration_ms: number;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  infra_error: string | null;
  sandbox: Record<string, string | number | boolean>;
  test_run: { tests: TestCase[]; total: number; passed: number; failed: number; skipped: number } | null;
}

export interface Experiment {
  id: string;
  key: string;
  round: number;
  designed_by: string;
  kind: 'reproduction' | 'discrimination' | 'intervention';
  objective: string;
  hypothesis_keys: string[];
  predictions: Prediction[];
  spec: {
    files?: { path: string; content: string }[];
    source_edits?: { file: string; search: string; replace: string }[];
    run?: string[];
    test_name_pattern?: string | null;
    success_condition?: string;
    failure_condition?: string;
    discriminating?: boolean;
    warnings?: string[];
  };
  status: 'planned' | 'running' | 'completed' | 'invalid';
  outcome: 'pass' | 'fail' | 'error' | 'timeout' | null;
  result: ExecutionResult | null;
  evaluation: {
    detail?: string;
    predictions?: PredictionEvaluation[];
    belief_before?: { hypotheses: Record<string, number>; unexplained: number };
    belief_after?: { hypotheses: Record<string, number>; unexplained: number };
    intervention_diff?: string;
    errors?: string[];
  } | null;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
}

export interface TestDelta {
  name: string;
  baseline: string | null;
  patched: string | null;
}

export interface Verification {
  verdict: 'verified' | 'rejected' | 'error';
  reasons: string[];
  target_test: string | null;
  target_baseline: string | null;
  target_patched: string | null;
  target_repeat_runs: string[];
  fixed: string[];
  regressions: string[];
  still_failing: string[];
  unchanged_passing: number;
  baseline_summary: Record<string, number>;
  patched_summary: Record<string, number>;
  deltas: TestDelta[];
  reverification?: { verdict: string; reasons: string[]; regressions: string[]; repeats: string[] };
}

export interface Patch {
  id: string;
  key: string;
  attempt: number;
  hypothesis_key: string | null;
  summary: string;
  rationale: string;
  edits: { file: string; search: string; replace: string }[];
  diff: string;
  files_changed: { path: string; added: number; removed: number; created: boolean }[];
  status: 'proposed' | 'applied' | 'verified' | 'rejected' | 'apply_failed' | 'empty';
  verification: Verification | null;
  review_status: 'pending' | 'approved' | 'rejected';
  review_note: string | null;
  created_at: string;
}

export interface Health {
  status: string;
  version: string;
  database: { ok: boolean; dialect: string; detail: string };
  sandbox: { ok: boolean; detail: string; docker_command: string; server_version: string | null };
  provider: { requested: string; active: string; model: string; simulated: boolean; fallback_reason: string | null };
}

export interface RuntimeConfig {
  ai_provider: 'mock' | 'meta' | 'openai';
  meta_model: string;
  openai_compat_model: string;
  temperature: number;
  max_tokens: number;
  max_experiments: number;
  max_model_calls: number;
  max_repair_attempts: number;
  max_experiment_rounds: number;
  time_budget_s: number;
}

export interface SettingsResponse {
  runtime: RuntimeConfig;
  secrets: { meta_api_key_configured: boolean; openai_compat_api_key_configured: boolean };
  endpoints: { meta_api_base_url: string; openai_compat_base_url: string };
  pricing: { input_per_m: number; output_per_m: number };
  meta: { reasoning_effort: string | null; structured_output: string };
}

export interface Dashboard {
  active: number;
  completed: number;
  failed: number;
  verified_repairs: number;
  no_verified_fix: number;
  inconclusive: number;
  experiments_total: number;
  experiments_failed_to_run: number;
  patches_rejected: number;
  repositories: number;
  investigations_last_7d: number;
  recent_activity: ForgeEvent[];
}

export interface EvidenceReport {
  investigation: {
    id: string;
    title: string;
    repository: string | null;
    mode: string;
    status: string;
    verdict: Verdict | null;
    verdict_text: string | null;
    created_at: string | null;
    finished_at: string | null;
    error: string | null;
  };
  provider: { name: string; model: string; simulated: boolean; note: string | null; disclaimer: string | null };
  symptom: string;
  target_failure: FailureObservation | null;
  reproduced: boolean | null;
  root_cause: string | null;
  hypotheses: Hypothesis[];
  rejected_hypotheses: Hypothesis[];
  experiments: {
    key: string;
    kind: string;
    objective: string;
    outcome: string | null;
    evaluation: Experiment['evaluation'];
    discriminating: boolean | null;
    intervention: boolean;
    execution: { exit_code: number | null; duration_ms: number | null; command: string[] | null };
  }[];
  patches: {
    key: string;
    summary: string;
    rationale: string;
    status: string;
    review_status: string;
    diff: string;
    verification: Partial<Verification>;
  }[];
  proposed_fix: string | null;
  decisions: { ts: string; type: string; message: string }[];
  usage: Usage;
  budget: Budget;
  model_calls: number;
}

export interface BenchmarkRunSummary {
  file: string;
  run_id: string;
  created_at: string;
  provider: string;
  simulated: boolean;
}
