import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ClaimStatus, ReceiptStatus } from '../../core/models/models';
import { StatusPill } from './status-pill';

describe('StatusPill', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(inputs: { claimStatus?: ClaimStatus; receiptStatus?: ReceiptStatus } = {}) {
    const fixture = TestBed.createComponent(StatusPill);
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    await fixture.whenStable();
    const pill = fixture.nativeElement.querySelector('.pill') as HTMLElement;
    return {
      pill,
      label: pill.textContent!.trim(),
      icon: pill.querySelector('.icon')?.textContent?.trim(),
      dot: pill.querySelector('.dot'),
      fixture,
    };
  }

  it('shows "Draft" when no status is given', async () => {
    const { label, pill } = await render();
    expect(label).toContain('Draft');
    expect(pill.classList).toContain('tone-neutral');
  });

  it.each([
    ['needs_attention', 'Needs your input', 'tone-warning', '💬'],
    ['ready', 'Ready to submit', 'tone-success', '✅'],
    ['submitted', 'Awaiting approval', 'tone-info', '📨'],
    ['rejected', 'Returned', 'tone-danger', '↩️'],
  ] as const)('renders claim status %s with label, tone and icon', async (status, text, tone, emoji) => {
    const { label, pill, icon } = await render({ claimStatus: status });

    expect(label).toContain(text);
    expect(pill.classList).toContain(tone);
    expect(icon).toBe(emoji);
  });

  it('renders receipt statuses', async () => {
    const { label, pill } = await render({ receiptStatus: 'needs_info' });

    expect(label).toContain('Needs info');
    expect(pill.classList).toContain('tone-warning');
  });

  it('prefers the receipt status when both are provided', async () => {
    const { label } = await render({ claimStatus: 'ready', receiptStatus: 'failed' });

    expect(label).toContain('Failed');
    expect(label).not.toContain('Ready');
  });

  it.each([{ claimStatus: 'processing' as const }, { receiptStatus: 'processing' as const }])(
    'pulses a live dot instead of an icon while processing (%o)',
    async (inputs) => {
      const { pill, dot, icon } = await render(inputs);

      expect(pill.classList).toContain('live');
      expect(dot).not.toBeNull();
      expect(icon).toBeUndefined();
    },
  );

  it('updates when the status input changes', async () => {
    const { fixture } = await render({ claimStatus: 'submitted' });

    fixture.componentRef.setInput('claimStatus', 'paid');
    await fixture.whenStable();

    expect(fixture.nativeElement.textContent).toContain('Reimbursed');
    expect(fixture.nativeElement.querySelector('.pill').classList).not.toContain('live');
  });
});
