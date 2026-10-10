import { makeCategory, makeReceipt } from '@testing/fixtures';

import type { PolicyStore } from '../config/policy.store';
import {
  CLAIM_STATUS,
  EDITABLE_STATUSES,
  JOURNEY,
  PIPELINE,
  RECEIPT_STATUS,
  claimLink,
  receiptSubtitle,
} from './display';
import { CategoryRule, ClaimStatus, ReceiptStage } from './models';

const ALL_CLAIM_STATUSES: ClaimStatus[] = [
  'draft',
  'processing',
  'needs_attention',
  'ready',
  'submitted',
  'approved',
  'rejected',
  'paid',
];

describe('claimLink', () => {
  it.each(['draft', 'processing', 'needs_attention', 'ready'] as ClaimStatus[])(
    'opens an editable (%s) claim in the agent workspace',
    (status) => {
      expect(claimLink({ id: 'c-7', status })).toEqual(['/agent', 'c-7']);
    },
  );

  it.each(['submitted', 'approved', 'rejected', 'paid'] as ClaimStatus[])(
    'opens a locked (%s) claim in the read-only detail view',
    (status) => {
      expect(claimLink({ id: 'c-7', status })).toEqual(['/claims', 'c-7']);
    },
  );
});

describe('receiptSubtitle', () => {
  /** receiptSubtitle only needs PolicyStore.category(), so a structural stub is enough. */
  const policyWith = (...categories: CategoryRule[]) =>
    ({
      category: (key: string | null | undefined) => categories.find((c) => c.key === key),
    }) as unknown as PolicyStore;

  const policy = policyWith(makeCategory({ key: 'meals', label: 'Meals' }));

  it('joins merchant and category label', () => {
    const receipt = makeReceipt({ data: { vendor: 'Taj Hotel', category: 'meals' } });
    expect(receiptSubtitle(receipt, policy)).toBe('Taj Hotel · Meals');
  });

  it('shows only the merchant when the category is unknown', () => {
    const receipt = makeReceipt({ data: { vendor: 'Taj Hotel', category: 'spa' } });
    expect(receiptSubtitle(receipt, policy)).toBe('Taj Hotel');
  });

  it('shows only the category when the merchant was not extracted', () => {
    const receipt = makeReceipt({ data: { vendor: null, category: 'meals' } });
    expect(receiptSubtitle(receipt, policy)).toBe('Meals');
  });

  it('falls back to "Receipt" when nothing is known yet', () => {
    const receipt = makeReceipt({ data: { vendor: null, category: null } });
    expect(receiptSubtitle(receipt, policy)).toBe('Receipt');
  });
});

describe('display metadata', () => {
  it('has a label, tone and icon for every claim status', () => {
    for (const status of ALL_CLAIM_STATUSES) {
      expect(CLAIM_STATUS[status], status).toEqual(
        expect.objectContaining({ label: expect.any(String), tone: expect.any(String), icon: expect.any(String) }),
      );
    }
  });

  it('describes every receipt status', () => {
    expect(Object.keys(RECEIPT_STATUS).sort()).toEqual(
      ['complete', 'excluded', 'failed', 'needs_info', 'processing', 'questionable'],
    );
  });

  it('places every claim status on exactly one journey step', () => {
    for (const status of ALL_CLAIM_STATUSES) {
      const steps = JOURNEY.filter((step) => step.statuses.includes(status));
      expect(steps.map((s) => s.key), status).toHaveLength(1);
    }
  });

  it('lists the receipt pipeline in processing order, ending in "completed"', () => {
    const order: ReceiptStage[] = [
      'uploaded',
      'reading',
      'extracting',
      'verifying',
      'categorising',
      'validating',
      'duplicate_check',
      'completed',
    ];
    expect(PIPELINE.map((p) => p.stage)).toEqual(order);
  });

  it('treats only pre-submission statuses as editable', () => {
    expect(EDITABLE_STATUSES).toEqual(['draft', 'processing', 'needs_attention', 'ready']);
  });
});
