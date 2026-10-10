import { ChatMessage, Claim } from '../../core/models/models';

/** Fields carried over when an unsaved claim is first persisted. */
export function createPayload(claim: Claim | null): { title?: string; purpose?: string } {
  return {
    title: claim && !claim.title_is_auto ? claim.title : undefined,
    purpose: claim?.purpose ?? undefined,
  };
}

/**
 * A local, not-yet-persisted claim shown when the user opens "New claim".
 * It is only created on the server on the first upload, chat message or "Save as draft".
 */
export function createUnsavedClaim(currency: string): Claim {
  const now = new Date().toISOString();
  return {
    id: '',
    user_id: '',
    title: 'New expense claim',
    title_is_auto: true,
    purpose: null,
    purpose_source: null,
    purpose_inferring: false,
    status: 'draft',
    currency,
    reference_no: null,
    created_at: now,
    updated_at: now,
    submitted_at: null,
    receipts: [],
    questions: [],
    messages: [],
    timeline: [],
    total_claimed: 0,
    total_reimbursable: 0,
    readiness: 0,
    checklist: [
      { key: 'uploaded', label: 'Receipts uploaded', done: false },
      { key: 'processed', label: 'All receipts read by the agent', done: false },
      { key: 'details', label: 'Required details captured', done: false },
      { key: 'policy', label: 'Policy checks passed', done: false },
      { key: 'duplicates', label: 'No unresolved duplicates', done: false },
      { key: 'purpose', label: 'Purpose / remarks added', done: false },
    ],
    groups: [],
    period_start: null,
    period_end: null,
  };
}

export function welcomeMessage(firstName: string, agentName: string): ChatMessage {
  return {
    id: 'local-welcome',
    role: 'agent',
    text:
      `Hi ${firstName}! 👋 I'm ${agentName}. Drop your bills here - photos, screenshots or PDFs - ` +
      `and I'll read them, sort them into categories, check them against policy and get your claim ready to submit.`,
    created_at: new Date().toISOString(),
    meta: {},
  };
}

export function localUserMessage(text: string): ChatMessage {
  return {
    id: `local-${Date.now()}`,
    role: 'user',
    text,
    created_at: new Date().toISOString(),
    meta: {},
  };
}
