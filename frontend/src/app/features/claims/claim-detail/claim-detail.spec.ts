import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { TEST_TOKEN, injectFakeRealtime, provideFakeRealtime, seedSession } from '@testing/fakes';
import { makeCategory, makeClaim, makeReceipt } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { PolicyStore } from '../../../core/config/policy.store';
import { Claim } from '../../../core/models/models';
import { ToastService } from '../../../core/ui/toast.service';
import { ClaimDetailPage } from './claim-detail';

const API = 'http://localhost:8100/api';

describe('ClaimDetailPage', () => {
  let fixture: ComponentFixture<ClaimDetailPage>;
  let http: HttpTestingController;
  let navigate: MockInstance<Router['navigate']>;
  let toast: { success: MockInstance<ToastService['success']>; error: MockInstance<ToastService['error']>; show: MockInstance<ToastService['show']> };

  const categories = [makeCategory({ key: 'travel', label: 'Travel', icon: '🚕' }), makeCategory({ key: 'lodging', label: 'Lodging', icon: '🏨' })];

  const submittedClaim = makeClaim({
    id: 'c-1',
    title: 'Delhi sales trip',
    status: 'submitted',
    reference_no: 'EXP-2026-0042',
    purpose: 'Meet the north region distributors',
    total_claimed: 10_000,
    total_reimbursable: 9_000,
    submitted_at: new Date().toISOString(),
    receipts: [
      makeReceipt({
        id: 'r-1',
        file_name: 'taj.jpg',
        mime_type: 'image/jpeg',
        data: { vendor: 'Taj Hotel', category: 'lodging', business_purpose: 'Client meetings', total_amount: 9_000 },
        reimbursable_amount: 8_000,
        flags: [
          { code: 'limit', severity: 'warning', message: 'Capped at lodging limit' },
          { code: 'fx', severity: 'info', message: 'Converted' },
        ],
        justification: 'Only hotel near the venue',
      }),
      makeReceipt({ id: 'r-2', file_name: 'cab.pdf', data: { vendor: 'Uber', category: 'travel', total_amount: 1_000 }, reimbursable_amount: 1_000 }),
      makeReceipt({ id: 'r-3', file_name: 'beer.pdf', excluded: true, data: { vendor: 'Pub' } }),
    ],
    timeline: [
      { status: 'draft', label: 'Claim created', actor: 'Asha Verma', note: null, at: '2026-10-01T09:00:00Z' },
      { status: 'submitted', label: 'Submitted', actor: 'Asha Verma', note: 'Please review', at: '2026-10-02T09:00:00Z' },
    ],
    groups: [
      { category: 'lodging', label: 'Lodging', icon: '🏨', count: 1, total: 8_000 },
      { category: 'travel', label: 'Travel', icon: '🚕', count: 1, total: 1_000 },
    ],
  });

  async function render(response: Claim | 'missing' = submittedClaim, mode: 'owner' | 'approval' = 'owner') {
    seedSession();
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideFakeRealtime(),
        { provide: PolicyStore, useValue: { category: (key: string | null) => categories.find((c) => c.key === key) } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const toasts = TestBed.inject(ToastService);
    toast = {
      success: vi.spyOn(toasts, 'success').mockImplementation(() => {}),
      error: vi.spyOn(toasts, 'error').mockImplementation(() => {}),
      show: vi.spyOn(toasts, 'show').mockImplementation(() => {}),
    };

    fixture = TestBed.createComponent(ClaimDetailPage);
    fixture.componentRef.setInput('id', 'c-1');
    fixture.componentRef.setInput('mode', mode);
    await fixture.whenStable();

    const url = mode === 'approval' ? `${API}/approvals/c-1` : `${API}/claims/c-1`;
    const req = http.expectOne(url);
    if (response === 'missing') req.flush({ detail: 'Claim not found' }, { status: 404, statusText: 'Not Found' });
    else req.flush(response);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => el().querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  const button = (label: string) =>
    Array.from(el().querySelectorAll('button')).find((b) => b.textContent!.includes(label)) as HTMLButtonElement;

  describe('loading', () => {
    it('shows a skeleton while the claim loads', async () => {
      seedSession();
      TestBed.configureTestingModule({
        providers: [provideZonelessChangeDetection(), provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideFakeRealtime(), { provide: PolicyStore, useValue: {} }],
      });
      http = TestBed.inject(HttpTestingController);
      fixture = TestBed.createComponent(ClaimDetailPage);
      fixture.componentRef.setInput('id', 'c-1');
      await fixture.whenStable();

      expect(el().querySelectorAll('.skeleton')).toHaveLength(2);
      http.expectOne(`${API}/claims/c-1`);
    });

    it('sends editable claims back to the agent workspace', async () => {
      await render(makeClaim({ id: 'c-1', status: 'needs_attention' }));
      expect(navigate).toHaveBeenCalledWith(['/agent', 'c-1'], { replaceUrl: true });
    });

    it('explains when the claim cannot be found', async () => {
      await render('missing');
      expect(text('h2')).toBe('😕 Claim not found');
    });
  });

  describe('for the claim owner', () => {
    beforeEach(async () => render());

    it('shows the header: status, reference, remarks and amounts', () => {
      expect(text('h1')).toBe('Delhi sales trip');
      expect(text('app-status-pill')).toContain('Awaiting approval');
      expect(text('.ref')).toBe('EXP-2026-0042');
      expect(text('.head-main .muted')).toBe('Remarks: Meet the north region distributors');
      expect(text('.head-main .subtle')).toContain('2 expenses');
      expect(text('.head-main .subtle')).toContain('submitted just now');
      expect(text('.head-amount strong')).toBe('₹9,000.00');
      expect(text('.head-amount span.subtle:last-of-type')).toBe('of ₹10,000.00 claimed');
      expect(el().querySelector('.back')!.getAttribute('href')).toBe('/claims');
    });

    it('lists active expenses with category, purpose, policy notes and justification', () => {
      const rows = Array.from(el().querySelectorAll('tbody tr'));
      expect(rows).toHaveLength(2); // the excluded receipt is left out

      const hotel = rows[0];
      expect(hotel.querySelector('.cat')!.textContent).toBe('🏨');
      expect(hotel.querySelector('button.link strong')!.textContent).toBe('Taj Hotel');
      expect(hotel.querySelector('small')!.textContent).toBe('Lodging · Client meetings');
      expect(Array.from(hotel.querySelectorAll('.flag')).map((f) => f.textContent)).toEqual(['Capped at lodging limit']);
      expect(hotel.querySelector('.just')!.textContent).toBe('💬 “Only hotel near the venue”');
      expect(Array.from(hotel.querySelectorAll('td.num')).map((td) => td.textContent!.trim())).toEqual(['₹9,000.00', '₹8,000.00']);
      expect(text('tfoot .num')).toBe('₹9,000.00');
    });

    it('offers a CSV export and a zip of all attachments with the access token', () => {
      expect(el().querySelector('.head-actions a')!.getAttribute('href')).toBe(`${API}/claims/c-1/export?access_token=${TEST_TOKEN}`);
      expect(el().querySelector('.att-head a')!.getAttribute('href')).toBe(
        `${API}/claims/c-1/attachments.zip?access_token=${TEST_TOKEN}`,
      );
      expect(text('.att-head .count')).toBe('2');
    });

    it('opens the attachment viewer on the chosen document', async () => {
      Array.from(el().querySelectorAll<HTMLButtonElement>('button.link'))[1].click();
      await fixture.whenStable();

      expect(text('app-attachment-viewer .title strong')).toBe('cab.pdf');

      (el().querySelector('app-attachment-viewer [aria-label=Close]') as HTMLButtonElement).click();
      await fixture.whenStable();
      expect(el().querySelector('app-attachment-viewer')).toBeNull();
    });

    it('shows the status timeline with the pending manager decision', () => {
      const steps = Array.from(el().querySelectorAll('.timeline li'));
      expect(steps.map((li) => li.querySelector('strong')!.textContent)).toEqual(['Claim created', 'Submitted', 'Manager decision']);
      expect(steps.map((li) => li.querySelector('.dot')!.textContent)).toEqual(['📝', '📨', '⏳']);
      expect(steps[1].classList).toContain('current');
      expect(steps[1].querySelector('p')!.textContent).toBe('Please review');
    });

    it('breaks the claim down by category', () => {
      const bars = Array.from(el().querySelectorAll<HTMLElement>('.cat-bar i')).map((i) => i.style.width);
      expect(bars).toEqual(['100%', '12.5%']);
    });

    it('does not show approval controls', () => {
      expect(el().querySelector('.decision')).toBeNull();
    });

    it('celebrates when a live update says the claim was paid', async () => {
      injectFakeRealtime().claimUpdates.next({ ...submittedClaim, status: 'paid' });
      await fixture.whenStable();

      expect(text('app-status-pill')).toContain('Reimbursed');
      expect(el().querySelector('app-confetti')).not.toBeNull();
    });

    it('applies other live status changes without celebrating', async () => {
      injectFakeRealtime().claimUpdates.next({ ...submittedClaim, status: 'approved' });
      await fixture.whenStable();

      expect(text('app-status-pill')).toContain('Approved');
      expect(el().querySelector('app-confetti')).toBeNull();
    });

    it('ignores live updates for other claims', async () => {
      injectFakeRealtime().claimUpdates.next(makeClaim({ id: 'c-999', title: 'Someone else', status: 'paid' }));
      await fixture.whenStable();

      expect(text('h1')).toBe('Delhi sales trip');
    });
  });

  describe('a returned claim', () => {
    beforeEach(async () => render(makeClaim({ id: 'c-1', status: 'rejected' })));

    it('can be reopened for fixing', async () => {
      button('Fix & resubmit').click();

      const req = http.expectOne(`${API}/claims/c-1/reopen`);
      expect(req.request.method).toBe('POST');
      req.flush(makeClaim({ id: 'c-1', status: 'draft' }));

      expect(navigate).toHaveBeenCalledWith(['/agent', 'c-1']);
    });

    it('reports when reopening fails', async () => {
      button('Fix & resubmit').click();
      http.expectOne(`${API}/claims/c-1/reopen`).flush({ detail: 'Too late' }, { status: 409, statusText: 'Conflict' });

      expect(toast.error).toHaveBeenCalledWith('Could not reopen', 'Too late');
    });
  });

  describe('for an approving manager', () => {
    beforeEach(async () => render(submittedClaim, 'approval'));

    const comment = async (value: string) => {
      const textarea = el().querySelector('.decision textarea') as HTMLTextAreaElement;
      textarea.value = value;
      textarea.dispatchEvent(new Event('input'));
      await fixture.whenStable();
    };

    it('loads through the approvals API and links back to the queue', () => {
      expect(el().querySelector('.back')!.getAttribute('href')).toBe('/approvals');
      expect(el().querySelector('.head-actions a')).toBeNull(); // no CSV export for approvers
      expect(el().querySelector('.att-head a')!.getAttribute('href')).toBe(
        `${API}/approvals/c-1/attachments.zip?access_token=${TEST_TOKEN}`,
      );
    });

    it('summarises policy notes to review', () => {
      expect(text('.decision .muted')).toBe('1 item(s) carry policy notes - review them below.');
    });

    it('requires a comment before returning a claim', async () => {
      button('Return').click();

      expect(toast.show).toHaveBeenCalledWith(expect.objectContaining({ level: 'warning', title: 'Add a comment' }));
      http.expectNone(`${API}/approvals/c-1`);
    });

    it('returns the claim with the trimmed comment', async () => {
      await comment('  Please attach the hotel invoice  ');
      button('Return').click();

      const req = http.expectOne(`${API}/approvals/c-1`);
      expect(req.request.body).toEqual({ decision: 'reject', comment: 'Please attach the hotel invoice' });
      req.flush({ ...submittedClaim, status: 'rejected' });
      await fixture.whenStable();

      expect(toast.success).toHaveBeenCalledWith('Claim returned to employee');
      expect(el().querySelector('.decision')).toBeNull();
      expect(el().querySelector('app-confetti')).toBeNull();
    });

    it('approves the claim and celebrates', async () => {
      button('Approve').click();
      await fixture.whenStable();

      const req = http.expectOne(`${API}/approvals/c-1`);
      expect(req.request.body).toEqual({ decision: 'approve', comment: '' });
      expect(button('Approve').disabled).toBe(true);
      req.flush({ ...submittedClaim, status: 'approved' });
      await fixture.whenStable();

      expect(toast.success).toHaveBeenCalledWith('Claim approved');
      expect(el().querySelector('app-confetti')).not.toBeNull();
      expect(text('.timeline li.pending strong')).toBe('Payout');
    });

    it('reports a failed decision and re-enables the buttons', async () => {
      button('Approve').click();
      http.expectOne(`${API}/approvals/c-1`).flush({ detail: 'Already decided' }, { status: 409, statusText: 'Conflict' });
      await fixture.whenStable();

      expect(toast.error).toHaveBeenCalledWith('Action failed', 'Already decided');
      expect(button('Approve').disabled).toBe(false);
    });
  });

  it('tells the approver when the agent found no policy concerns', async () => {
    await render(makeClaim({ id: 'c-1', status: 'submitted', receipts: [makeReceipt()] }), 'approval');
    expect(text('.decision .muted')).toBe('No policy concerns detected by the agent.');
  });

  it('shows an empty attachments state', async () => {
    await render(makeClaim({ id: 'c-1', status: 'paid', receipts: [], groups: [] }));

    expect(text('.attachments .muted')).toBe('No documents attached.');
    expect(el().querySelector('.att-head a')).toBeNull();
  });
});
