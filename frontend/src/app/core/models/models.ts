/** Types mirroring the FastAPI schemas (backend/app/models). */

export type Role = 'employee' | 'manager';

export interface User {
  id: string;
  username: string;
  name: string;
  email: string;
  role: Role;
  department: string;
  employee_code: string;
  cost_center: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface DemoUser {
  username: string;
  password: string;
  name: string;
  role: Role;
}

export type ReceiptStage =
  | 'uploaded'
  | 'reading'
  | 'extracting'
  | 'verifying'
  | 'categorising'
  | 'validating'
  | 'duplicate_check'
  | 'completed'
  | 'failed';

export type ReceiptStatus =
  | 'processing'
  | 'complete'
  | 'needs_info'
  | 'questionable'
  | 'excluded'
  | 'failed';

export type Severity = 'info' | 'warning' | 'error';

export interface Flag {
  code: string;
  severity: Severity;
  message: string;
}

export interface LineItem {
  description: string;
  amount: number | null;
  quantity: number | null;
  unit_price: number | null;
}

export interface ExpenseData {
  vendor: string | null;
  /** Merchant name as printed, in the original script. */
  vendor_local: string | null;
  language: string | null;
  date: string | null;
  total_amount: number | null;
  currency: string | null;
  tax_amount: number | null;
  category: string | null;
  payment_method: string | null;
  invoice_number: string | null;
  location: string | null;
  description: string | null;
  business_purpose: string | null;
  attendees: string | null;
  line_items: LineItem[];
}

export interface Receipt {
  id: string;
  claim_id: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  uploaded_at: string;
  stage: ReceiptStage;
  progress: number;
  status: ReceiptStatus;
  error: string | null;
  data: ExpenseData;
  confidence: Record<string, number>;
  confirmed_fields: string[];
  is_receipt: boolean;
  extraction_source: string | null;
  extraction_notes: string | null;
  /** Set when the document couldn't actually be read (e.g. a photo with the offline engine). */
  read_warning: string | null;
  amount_in_base: number | null;
  reimbursable_amount: number | null;
  flags: Flag[];
  missing_fields: string[];
  duplicate_of: string | null;
  duplicate_note: string | null;
  duplicate_acknowledged: boolean;
  justification: string | null;
  excluded: boolean;
  /** business_purpose was copied from the claim's remarks. */
  purpose_inherited: boolean;
}

export type QuestionType = 'text' | 'number' | 'date' | 'select' | 'choice';

export interface QuestionOption {
  value: string;
  label: string;
}

export interface Question {
  id: string;
  key: string;
  receipt_id: string | null;
  kind: string;
  prompt: string;
  type: QuestionType;
  options: QuestionOption[];
  default: unknown;
}

export interface ChatMessage {
  id: string;
  role: 'agent' | 'user' | 'system';
  text: string;
  created_at: string;
  meta: Record<string, unknown>;
}

export type ClaimStatus =
  | 'draft'
  | 'processing'
  | 'needs_attention'
  | 'ready'
  | 'submitted'
  | 'approved'
  | 'rejected'
  | 'paid';

export interface TimelineEvent {
  status: string;
  label: string;
  actor: string;
  note: string | null;
  at: string;
}

export interface ChecklistItem {
  key: string;
  label: string;
  done: boolean;
}

export interface CategoryGroup {
  category: string;
  label: string;
  icon: string;
  count: number;
  total: number;
}

export interface Claim {
  id: string;
  user_id: string;
  title: string;
  title_is_auto: boolean;
  purpose: string | null;
  /** 'agent' when Rika wrote the remarks, 'user' once the employee edits them. */
  purpose_source: 'user' | 'agent' | null;
  purpose_inferring: boolean;
  status: ClaimStatus;
  currency: string;
  reference_no: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  receipts: Receipt[];
  questions: Question[];
  messages: ChatMessage[];
  timeline: TimelineEvent[];
  total_claimed: number;
  total_reimbursable: number;
  readiness: number;
  checklist: ChecklistItem[];
  groups: CategoryGroup[];
  period_start: string | null;
  period_end: string | null;
}

export interface ClaimSummary {
  id: string;
  title: string;
  status: ClaimStatus;
  reference_no: string | null;
  currency: string;
  total_claimed: number;
  total_reimbursable: number;
  readiness: number;
  receipt_count: number;
  pending_questions: number;
  period_start: string | null;
  period_end: string | null;
  created_at: string;
  updated_at: string;
  submitted_at: string | null;
  owner_name: string | null;
}

export type ReceiptUpdate = Partial<
  Omit<ExpenseData, 'line_items' | 'vendor_local' | 'language'> & {
    justification: string | null;
    excluded: boolean;
  }
>;

/** A receipt document as shown in the attachment viewer. */
export interface Attachment {
  id: string;
  name: string;
  mimeType: string;
  sizeBytes: number;
  subtitle: string;
  viewUrl: string;
  downloadUrl: string;
}

export interface AppNotification {
  id: string;
  user_id: string;
  level: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  link: string | null;
  read: boolean;
  created_at: string;
}

export interface CategoryRule {
  key: string;
  label: string;
  icon: string;
  limit_per_item: number | null;
  requires: string[];
}

export interface PublicConfig {
  app_name: string;
  agent_name: string;
  company: string;
  currency: string;
  llm_provider: string;
  max_upload_mb: number;
  allowed_extensions: string[];
  pipeline_stages: ReceiptStage[];
  categories: CategoryRule[];
  currencies: string[];
  policy: {
    max_receipt_age_days: number;
    receipt_required_above: number;
    claim_requires_purpose: boolean;
    blocked_keywords: string[];
  };
}

export interface DashboardSummary {
  currency: string;
  counts: Partial<Record<ClaimStatus, number>>;
  drafts: number;
  pending_questions: number;
  ready_to_submit: number;
  in_flight_amount: number;
  reimbursed_amount: number;
  receipts_processed: number;
  by_category: { category: string; label: string; icon: string; total: number }[];
  recent: ClaimSummary[];
  pending_approvals: number;
}

export interface ProviderStatus {
  name: 'ollama' | 'claude' | 'mock';
  label: string;
  configured: boolean;
  healthy: boolean | null;
  detail: string;
  models: Record<string, string>;
}

export interface LlmSettings {
  active: ProviderStatus['name'];
  fallback_chain: string[];
  providers: ProviderStatus[];
}
