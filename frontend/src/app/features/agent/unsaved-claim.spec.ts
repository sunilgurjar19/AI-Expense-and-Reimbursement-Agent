import { makeClaim } from '@testing/fixtures';

import { createPayload, createUnsavedClaim, localUserMessage, welcomeMessage } from './unsaved-claim';

describe('unsaved-claim helpers', () => {
  const NOW = new Date('2026-10-10T08:30:00.000Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  describe('createPayload', () => {
    it('sends nothing for a claim that does not exist yet', () => {
      expect(createPayload(null)).toEqual({ title: undefined, purpose: undefined });
    });

    it('omits an auto-generated title so the server can generate its own', () => {
      const claim = makeClaim({ title: 'New expense claim', title_is_auto: true, purpose: null });
      expect(createPayload(claim)).toEqual({ title: undefined, purpose: undefined });
    });

    it('carries over a title the user typed and the remarks', () => {
      const claim = makeClaim({ title: 'Goa offsite', title_is_auto: false, purpose: 'Team offsite' });
      expect(createPayload(claim)).toEqual({ title: 'Goa offsite', purpose: 'Team offsite' });
    });
  });

  describe('createUnsavedClaim', () => {
    it('creates an empty local draft in the requested currency', () => {
      const claim = createUnsavedClaim('USD');

      expect(claim).toEqual(
        expect.objectContaining({
          id: '',
          title: 'New expense claim',
          title_is_auto: true,
          status: 'draft',
          currency: 'USD',
          purpose: null,
          receipts: [],
          questions: [],
          messages: [],
          total_claimed: 0,
          total_reimbursable: 0,
          readiness: 0,
        }),
      );
    });

    it('timestamps the draft with the current time', () => {
      const claim = createUnsavedClaim('INR');
      expect(claim.created_at).toBe(NOW.toISOString());
      expect(claim.updated_at).toBe(NOW.toISOString());
    });

    it('starts with the full readiness checklist, nothing done', () => {
      const { checklist } = createUnsavedClaim('INR');

      expect(checklist.map((item) => item.key)).toEqual([
        'uploaded',
        'processed',
        'details',
        'policy',
        'duplicates',
        'purpose',
      ]);
      expect(checklist.every((item) => !item.done)).toBe(true);
    });

    it('returns a fresh object each time (no shared mutable state)', () => {
      const a = createUnsavedClaim('INR');
      const b = createUnsavedClaim('INR');
      a.checklist[0].done = true;
      expect(b.checklist[0].done).toBe(false);
    });
  });

  describe('welcomeMessage', () => {
    it('greets the user by first name as the agent', () => {
      const message = welcomeMessage('Asha', 'Rika');

      expect(message.id).toBe('local-welcome');
      expect(message.role).toBe('agent');
      expect(message.text).toMatch(/^Hi Asha! .* I'm Rika\./);
      expect(message.created_at).toBe(NOW.toISOString());
    });
  });

  describe('localUserMessage', () => {
    it('wraps the text as an optimistic user message with a time-based local id', () => {
      expect(localUserMessage("What's my total?")).toEqual({
        id: `local-${NOW.getTime()}`,
        role: 'user',
        text: "What's my total?",
        created_at: NOW.toISOString(),
        meta: {},
      });
    });
  });
});
