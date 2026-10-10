/**
 * Typed test-data builders. Each returns a complete, realistic object; pass overrides
 * for just the fields a test cares about so the intent of the test stays visible.
 */
import type {
  AppNotification,
  CategoryRule,
  Claim,
  ClaimSummary,
  DashboardSummary,
  ExpenseData,
  LlmSettings,
  ProviderStatus,
  PublicConfig,
  Question,
  Receipt,
  User,
} from '../src/app/core/models/models';

export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 'u-1',
    username: 'employee',
    name: 'Asha Verma',
    email: 'asha@example.com',
    role: 'employee',
    department: 'Sales',
    employee_code: 'EMP-001',
    cost_center: 'CC-100',
    ...overrides,
  };
}

export function makeManager(overrides: Partial<User> = {}): User {
  return makeUser({
    id: 'u-9',
    username: 'manager',
    name: 'Meera Iyer',
    role: 'manager',
    department: 'Finance',
    ...overrides,
  });
}

export function makeExpense(overrides: Partial<ExpenseData> = {}): ExpenseData {
  return {
    vendor: 'Uber',
    vendor_local: null,
    language: 'en',
    date: '2026-10-01',
    total_amount: 827,
    currency: 'INR',
    tax_amount: null,
    category: 'travel',
    payment_method: 'card',
    invoice_number: 'INV-42',
    location: 'Mumbai',
    description: 'Airport cab',
    business_purpose: 'Client visit',
    attendees: null,
    line_items: [],
    ...overrides,
  };
}

type ReceiptOverrides = Omit<Partial<Receipt>, 'data'> & { data?: Partial<ExpenseData> };

export function makeReceipt(overrides: ReceiptOverrides = {}): Receipt {
  const { data, ...rest } = overrides;
  return {
    id: 'r-1',
    claim_id: 'c-1',
    file_name: 'uber.pdf',
    mime_type: 'application/pdf',
    size_bytes: 48_000,
    uploaded_at: '2026-10-01T10:00:00Z',
    stage: 'completed',
    progress: 100,
    status: 'complete',
    error: null,
    data: makeExpense(data),
    confidence: { vendor: 0.97, total_amount: 0.9 },
    confirmed_fields: [],
    is_receipt: true,
    extraction_source: 'mock',
    extraction_notes: null,
    read_warning: null,
    amount_in_base: 827,
    reimbursable_amount: 827,
    flags: [],
    missing_fields: [],
    duplicate_of: null,
    duplicate_note: null,
    duplicate_acknowledged: false,
    justification: null,
    excluded: false,
    purpose_inherited: false,
    ...rest,
  };
}

export function makeQuestion(overrides: Partial<Question> = {}): Question {
  return {
    id: 'q-1',
    key: 'r-1:business_purpose',
    receipt_id: 'r-1',
    kind: 'business_purpose',
    prompt: 'What was the **business purpose** of this trip?',
    type: 'text',
    options: [],
    default: null,
    ...overrides,
  };
}

export function makeClaim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 'c-1',
    user_id: 'u-1',
    title: 'Mumbai client visit',
    title_is_auto: false,
    purpose: 'Quarterly review with Acme',
    purpose_source: 'user',
    purpose_inferring: false,
    status: 'ready',
    currency: 'INR',
    reference_no: null,
    created_at: '2026-10-01T09:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    submitted_at: null,
    receipts: [],
    questions: [],
    messages: [],
    timeline: [],
    total_claimed: 827,
    total_reimbursable: 827,
    readiness: 100,
    checklist: [],
    groups: [],
    period_start: '2026-10-01',
    period_end: '2026-10-01',
    ...overrides,
  };
}

export function makeClaimSummary(overrides: Partial<ClaimSummary> = {}): ClaimSummary {
  return {
    id: 'c-1',
    title: 'Mumbai client visit',
    status: 'draft',
    reference_no: null,
    currency: 'INR',
    total_claimed: 827,
    total_reimbursable: 827,
    readiness: 40,
    receipt_count: 1,
    pending_questions: 0,
    period_start: null,
    period_end: null,
    created_at: '2026-10-01T09:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    submitted_at: null,
    owner_name: 'Asha Verma',
    ...overrides,
  };
}

export function makeNotification(overrides: Partial<AppNotification> = {}): AppNotification {
  return {
    id: 'n-1',
    user_id: 'u-1',
    level: 'info',
    title: 'Claim approved',
    message: 'Your claim was approved by Meera.',
    link: '/claims/c-1',
    read: false,
    created_at: '2026-10-01T10:00:00Z',
    ...overrides,
  };
}

export function makeCategory(overrides: Partial<CategoryRule> = {}): CategoryRule {
  return {
    key: 'travel',
    label: 'Travel',
    icon: '🚕',
    limit_per_item: 5000,
    requires: [],
    ...overrides,
  };
}

export function makePublicConfig(overrides: Partial<PublicConfig> = {}): PublicConfig {
  return {
    app_name: 'Expense & Reimbursement Agent',
    agent_name: 'Rika',
    company: 'Acme Corp',
    currency: 'INR',
    llm_provider: 'mock',
    max_upload_mb: 20,
    allowed_extensions: ['.pdf', '.png'],
    pipeline_stages: ['uploaded', 'reading', 'completed'],
    categories: [
      makeCategory(),
      makeCategory({ key: 'meals', label: 'Meals', icon: '🍽️', limit_per_item: 2000 }),
      makeCategory({ key: 'lodging', label: 'Lodging', icon: '🏨', limit_per_item: 8000, requires: ['business_purpose'] }),
    ],
    currencies: ['INR', 'USD'],
    policy: {
      max_receipt_age_days: 90,
      receipt_required_above: 500,
      claim_requires_purpose: true,
      blocked_keywords: ['alcohol', 'beer', 'wine'],
    },
    ...overrides,
  };
}

export function makeDashboard(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    currency: 'INR',
    counts: { draft: 2, submitted: 1 },
    drafts: 2,
    pending_questions: 0,
    ready_to_submit: 1,
    in_flight_amount: 12_500,
    reimbursed_amount: 40_000,
    receipts_processed: 14,
    by_category: [],
    recent: [],
    pending_approvals: 0,
    ...overrides,
  };
}

export function makeProvider(overrides: Partial<ProviderStatus> = {}): ProviderStatus {
  return {
    name: 'ollama',
    label: 'Ollama',
    configured: true,
    healthy: null,
    detail: 'Not checked yet',
    models: { vision: 'gemma3:4b' },
    ...overrides,
  };
}

export function makeLlmSettings(overrides: Partial<LlmSettings> = {}): LlmSettings {
  return {
    active: 'ollama',
    fallback_chain: ['mock'],
    providers: [
      makeProvider(),
      makeProvider({ name: 'claude', label: 'Claude', configured: false, models: { chat: 'claude-sonnet' } }),
      makeProvider({ name: 'mock', label: 'Offline rules', models: {} }),
    ],
    ...overrides,
  };
}
