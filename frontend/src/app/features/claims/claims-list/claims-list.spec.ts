import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { injectFakeRealtime, provideFakeRealtime } from '@testing/fakes';
import { makeClaim, makeClaimSummary } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { ClaimSummary } from '../../../core/models/models';
import { ToastService } from '../../../core/ui/toast.service';
import { ClaimsListPage } from './claims-list';

const CLAIMS_URL = 'http://localhost:8100/api/claims';

describe('ClaimsListPage', () => {
  let fixture: ComponentFixture<ClaimsListPage>;
  let http: HttpTestingController;
  let toastSuccess: MockInstance<ToastService['success']>;
  let toastError: MockInstance<ToastService['error']>;

  const claims: ClaimSummary[] = [
    makeClaimSummary({ id: 'c-1', title: 'Goa offsite', status: 'draft', receipt_count: 0 }),
    makeClaimSummary({ id: 'c-2', title: 'Pune workshop', status: 'needs_attention', pending_questions: 2 }),
    makeClaimSummary({ id: 'c-3', title: 'Delhi sales trip', status: 'submitted', reference_no: 'EXP-2026-0007' }),
    makeClaimSummary({ id: 'c-4', title: 'Chennai visit', status: 'paid', reference_no: 'EXP-2026-0003' }),
    makeClaimSummary({ id: 'c-5', title: 'Team lunch', status: 'rejected', reference_no: 'EXP-2026-0009' }),
  ];

  function setup() {
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideFakeRealtime(),
      ],
    });
    http = TestBed.inject(HttpTestingController);
    toastSuccess = vi.spyOn(TestBed.inject(ToastService), 'success').mockImplementation(() => {});
    toastError = vi.spyOn(TestBed.inject(ToastService), 'error').mockImplementation(() => {});
    fixture = TestBed.createComponent(ClaimsListPage);
  }

  async function render(list: ClaimSummary[] = claims) {
    setup();
    http.expectOne(CLAIMS_URL).flush(list);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const titles = () => Array.from(el().querySelectorAll('.claim h3')).map((h) => h.textContent);
  const tab = (label: string) =>
    Array.from(el().querySelectorAll<HTMLButtonElement>('.tab')).find((t) => t.textContent!.includes(label))!;
  const card = (title: string) =>
    Array.from(el().querySelectorAll<HTMLElement>('.claim-wrap')).find((c) => c.querySelector('h3')!.textContent === title)!;

  async function search(query: string) {
    const input = el().querySelector('.search') as HTMLInputElement;
    input.value = query;
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('shows loading placeholders until the claims arrive', async () => {
    setup();
    await fixture.whenStable();
    expect(el().querySelectorAll('.skeleton')).toHaveLength(3);

    http.expectOne(CLAIMS_URL).flush(claims);
    await fixture.whenStable();

    expect(el().querySelector('.skeleton')).toBeNull();
    expect(titles()).toHaveLength(5);
  });

  it('stops loading and shows the empty state if the request fails', async () => {
    setup();
    http.expectOne(CLAIMS_URL).flush(null, { status: 500, statusText: 'Server Error' });
    await fixture.whenStable();

    expect(el().querySelector('.skeleton')).toBeNull();
    expect(el().querySelector('.empty h3')!.textContent).toBe('No claims here yet');
  });

  describe('a claim card', () => {
    beforeEach(async () => render());

    it('links editable claims to the agent workspace and locked ones to the detail view', () => {
      expect(card('Goa offsite').querySelector('a.claim')!.getAttribute('href')).toBe('/agent/c-1');
      expect(card('Delhi sales trip').querySelector('a.claim')!.getAttribute('href')).toBe('/claims/c-3');
    });

    it('shows status, reference number, receipt count and amount', () => {
      const submitted = card('Delhi sales trip');
      expect(submitted.querySelector('app-status-pill')!.textContent).toContain('Awaiting approval');
      expect(submitted.querySelector('.ref')!.textContent).toBe('EXP-2026-0007');
      expect(submitted.querySelector('.subtle')!.textContent).toContain('1 receipt ·');
      expect(submitted.querySelector('.bottom strong')!.textContent).toBe('₹827.00');
      expect(card('Goa offsite').querySelector('.subtle')!.textContent).toContain('0 receipts ·');
    });

    it('highlights pending questions on claims that need attention', () => {
      expect(card('Pune workshop').querySelector('.ask')!.textContent).toContain('2 question(s) for you');
      expect(card('Delhi sales trip').querySelector('.ask')).toBeNull();
    });

    it('offers delete only for claims that have not been submitted', () => {
      expect(card('Goa offsite').querySelector('.delete')).not.toBeNull();
      expect(card('Pune workshop').querySelector('.delete')).not.toBeNull();
      expect(card('Delhi sales trip').querySelector('.delete')).toBeNull();
      expect(card('Chennai visit').querySelector('.delete')).toBeNull();
    });
  });

  describe('tabs and search', () => {
    beforeEach(async () => render());

    it('counts claims per tab', () => {
      const counts = Array.from(el().querySelectorAll('.tab')).map((t) => t.textContent!.replace(/\s+/g, ' ').trim());
      expect(counts).toEqual(['All 5', 'In progress 2', 'In approval 1', 'Reimbursed 1', 'Returned 1']);
      expect(tab('All').classList).toContain('active');
    });

    it.each([
      ['In progress', ['Goa offsite', 'Pune workshop']],
      ['In approval', ['Delhi sales trip']],
      ['Reimbursed', ['Chennai visit']],
      ['Returned', ['Team lunch']],
    ])('filters to the "%s" tab', async (label, expected) => {
      tab(label).click();
      await fixture.whenStable();

      expect(titles()).toEqual(expected);
      expect(tab(label).classList).toContain('active');
    });

    it('searches titles case-insensitively', async () => {
      await search('  PUNE ');
      expect(titles()).toEqual(['Pune workshop']);
    });

    it('searches reference numbers', async () => {
      await search('exp-2026-0003');
      expect(titles()).toEqual(['Chennai visit']);
    });

    it('combines the search with the active tab', async () => {
      tab('In progress').click();
      await search('trip');

      expect(el().querySelector('.empty h3')!.textContent).toBe('No claims here yet');
    });
  });

  describe('deleting a draft', () => {
    beforeEach(async () => render());

    async function askToDelete(title: string) {
      (card(title).querySelector('.delete') as HTMLButtonElement).click();
      await fixture.whenStable();
    }

    const confirmButton = (title: string) => card(title).querySelector('.btn-danger') as HTMLButtonElement;

    it('asks for confirmation, mentioning the receipts that will be removed', async () => {
      await askToDelete('Pune workshop');
      expect(card('Pune workshop').querySelector('.confirm span')!.textContent).toBe('1 receipt(s) will be removed.');

      await askToDelete('Goa offsite');
      expect(card('Goa offsite').querySelector('.confirm span')!.textContent).toBe('It has no receipts yet.');
    });

    it('can be cancelled', async () => {
      await askToDelete('Goa offsite');

      (card('Goa offsite').querySelector('.btn-ghost') as HTMLButtonElement).click();
      await fixture.whenStable();

      expect(card('Goa offsite').querySelector('.confirm')).toBeNull();
    });

    it('deletes the claim, removes the card and confirms', async () => {
      await askToDelete('Goa offsite');
      confirmButton('Goa offsite').click();
      await fixture.whenStable();

      const req = http.expectOne(`${CLAIMS_URL}/c-1`);
      expect(req.request.method).toBe('DELETE');
      expect(confirmButton('Goa offsite').disabled).toBe(true);
      req.flush(null);
      await fixture.whenStable();

      expect(titles()).not.toContain('Goa offsite');
      expect(toastSuccess).toHaveBeenCalledWith('Draft deleted', '“Goa offsite” was removed.');
    });

    it('keeps the card and reports the error when deletion fails', async () => {
      await askToDelete('Goa offsite');
      confirmButton('Goa offsite').click();

      http.expectOne(`${CLAIMS_URL}/c-1`).flush({ detail: 'Claim is locked' }, { status: 409, statusText: 'Conflict' });
      await fixture.whenStable();

      expect(titles()).toContain('Goa offsite');
      expect(confirmButton('Goa offsite').disabled).toBe(false);
      expect(toastError).toHaveBeenCalledWith('Could not delete', 'Claim is locked');
    });
  });

  it('reloads (debounced) when claims change in the background', async () => {
    // RxJS timers use setInterval + Date; Angular's scheduler (setTimeout/rAF) stays real.
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    await render();
    const realtime = injectFakeRealtime();

    realtime.claimUpdates.next(makeClaim({ id: 'c-2', status: 'ready' }));
    realtime.claimUpdates.next(makeClaim({ id: 'c-2', status: 'ready' }));
    vi.advanceTimersByTime(599);
    http.expectNone(CLAIMS_URL);

    vi.advanceTimersByTime(1);
    http.expectOne(CLAIMS_URL).flush([makeClaimSummary({ id: 'c-2', title: 'Pune workshop', status: 'ready' })]);
    await fixture.whenStable();

    expect(titles()).toEqual(['Pune workshop']);
  });
});
