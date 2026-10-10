import type { PolicyStore } from '../config/policy.store';
import { ClaimStatus, Receipt, ReceiptStage, ReceiptStatus } from './models';

/** Presentation metadata shared across screens. */

export interface StatusMeta {
  label: string;
  tone: 'neutral' | 'brand' | 'info' | 'warning' | 'success' | 'danger';
  icon: string;
}

export const CLAIM_STATUS: Record<ClaimStatus, StatusMeta> = {
  draft: { label: 'Draft', tone: 'neutral', icon: '📝' },
  processing: { label: 'Agent working', tone: 'brand', icon: '⚙️' },
  needs_attention: { label: 'Needs your input', tone: 'warning', icon: '💬' },
  ready: { label: 'Ready to submit', tone: 'success', icon: '✅' },
  submitted: { label: 'Awaiting approval', tone: 'info', icon: '📨' },
  approved: { label: 'Approved', tone: 'success', icon: '👍' },
  rejected: { label: 'Returned', tone: 'danger', icon: '↩️' },
  paid: { label: 'Reimbursed', tone: 'success', icon: '💸' },
};

export const RECEIPT_STATUS: Record<ReceiptStatus, StatusMeta> = {
  processing: { label: 'Processing', tone: 'brand', icon: '⚙️' },
  complete: { label: 'Complete', tone: 'success', icon: '✓' },
  needs_info: { label: 'Needs info', tone: 'warning', icon: '?' },
  questionable: { label: 'Check', tone: 'warning', icon: '!' },
  excluded: { label: 'Excluded', tone: 'neutral', icon: '–' },
  failed: { label: 'Failed', tone: 'danger', icon: '✕' },
};

export const PIPELINE: { stage: ReceiptStage; label: string; icon: string }[] = [
  { stage: 'uploaded', label: 'Uploaded', icon: '📥' },
  { stage: 'reading', label: 'Reading', icon: '👀' },
  { stage: 'extracting', label: 'Extracting', icon: '🧠' },
  { stage: 'verifying', label: 'Double-check', icon: '🧐' },
  { stage: 'categorising', label: 'Categorising', icon: '🗂️' },
  { stage: 'validating', label: 'Policy check', icon: '🛡️' },
  { stage: 'duplicate_check', label: 'Duplicates', icon: '🔍' },
  { stage: 'completed', label: 'Done', icon: '✨' },
];

/** The end-to-end claim journey shown at the top of the agent workspace. */
export const JOURNEY: { key: string; label: string; statuses: ClaimStatus[] }[] = [
  { key: 'collect', label: 'Collect', statuses: ['draft'] },
  { key: 'read', label: 'Read & extract', statuses: ['processing'] },
  { key: 'review', label: 'Review', statuses: ['needs_attention'] },
  { key: 'ready', label: 'Ready', statuses: ['ready'] },
  { key: 'submitted', label: 'Approval', statuses: ['submitted', 'rejected'] },
  { key: 'approved', label: 'Payout', statuses: ['approved'] },
  { key: 'paid', label: 'Reimbursed', statuses: ['paid'] },
];

export const FIELD_LABELS: Record<string, string> = {
  vendor: 'Merchant',
  date: 'Date',
  total_amount: 'Amount',
  currency: 'Currency',
  tax_amount: 'Tax',
  category: 'Category',
  payment_method: 'Payment method',
  invoice_number: 'Invoice #',
  location: 'City',
  description: 'Description',
  business_purpose: 'Business purpose',
  attendees: 'Attendees',
};

export const EDITABLE_STATUSES: ClaimStatus[] = ['draft', 'processing', 'needs_attention', 'ready'];

/** Editable claims open in the agent workspace; everything else in the read-only detail view. */
export function claimLink(claim: { id: string; status: ClaimStatus }): string[] {
  return EDITABLE_STATUSES.includes(claim.status) ? ['/agent', claim.id] : ['/claims', claim.id];
}

/** "Merchant · Category" line used under attachment names. */
export function receiptSubtitle(receipt: Receipt, policy: PolicyStore): string {
  const parts = [receipt.data.vendor, policy.category(receipt.data.category)?.label].filter(Boolean);
  return parts.join(' · ') || 'Receipt';
}
