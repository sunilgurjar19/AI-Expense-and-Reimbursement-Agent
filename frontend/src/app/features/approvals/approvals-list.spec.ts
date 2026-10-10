import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { injectFakeRealtime, provideFakeRealtime } from '@testing/fakes';
import { makeClaimSummary, makeNotification } from '@testing/fixtures';

import { ClaimSummary } from '../../core/models/models';
import { ApprovalsListPage } from './approvals-list';

const APPROVALS_URL = 'http://localhost:8100/api/approvals';

describe('ApprovalsListPage', () => {
  let fixture: ComponentFixture<ApprovalsListPage>;
  let http: HttpTestingController;

  const queue: ClaimSummary[] = [
    makeClaimSummary({
      id: 'c-1',
      title: 'Delhi sales trip',
      status: 'submitted',
      owner_name: 'Asha Verma',
      reference_no: 'EXP-1',
      total_reimbursable: 12_000,
      receipt_count: 4,
      currency: 'USD',
    }),
    makeClaimSummary({ id: 'c-2', title: 'Pune workshop', status: 'submitted', owner_name: 'Ravi Kumar', total_reimbursable: 3_000 }),
    makeClaimSummary({ id: 'c-3', title: 'Team lunch', status: 'approved', owner_name: 'Priya Shah' }),
    makeClaimSummary({ id: 'c-4', title: 'Conference', status: 'rejected', owner_name: 'Asha Verma' }),
  ];

  async function render(list: ClaimSummary[] = queue) {
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
    fixture = TestBed.createComponent(ApprovalsListPage);
    http.expectOne(APPROVALS_URL).flush(list);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const stats = () => Array.from(el().querySelectorAll('.stat strong')).map((s) => s.textContent);
  const rows = (selector: string) => Array.from(el().querySelectorAll<HTMLAnchorElement>(selector));

  it('summarises what is waiting for the manager', async () => {
    await render();
    // Pending amount is shown in the currency of the first claim in the queue.
    expect(stats()).toEqual(['2', '$15,000.00', '2']);
  });

  it('lists submitted claims for review, linking to the approval view', async () => {
    await render();

    const pending = rows('.row.attention');
    expect(pending.map((r) => r.querySelector('.main strong')!.textContent)).toEqual(['Delhi sales trip', 'Pune workshop']);
    expect(pending[0].getAttribute('href')).toBe('/approvals/c-1');
    expect(pending[0].querySelector('.avatar')!.textContent).toBe('A');
    expect(pending[0].querySelector('.count')!.textContent).toBe('4 items');
    expect(pending[0].querySelector('.amount')!.textContent).toBe('$12,000.00');
  });

  it('lists recently decided claims with their outcome', async () => {
    await render();

    const decided = rows('.row:not(.attention)');
    expect(decided.map((r) => r.querySelector('.main strong')!.textContent)).toEqual(['Team lunch', 'Conference']);
    expect(decided[1].querySelector('app-status-pill')!.textContent).toContain('Returned');
  });

  it('renders claims whose owner name is unknown', async () => {
    await render([
      makeClaimSummary({ id: 'c-8', status: 'submitted', owner_name: null }),
      makeClaimSummary({ id: 'c-9', status: 'paid', owner_name: null }),
    ]);

    expect(rows('.row .avatar').map((a) => a.textContent)).toEqual(['', '']);
  });

  it('celebrates an empty inbox and defaults to rupees', async () => {
    await render([]);

    expect(el().querySelector('.empty')!.textContent).toContain('Inbox zero');
    expect(stats()).toEqual(['0', '₹0.00', '0']);
    expect(el().textContent).not.toContain('Recently decided');
  });

  it('refreshes the queue whenever a notification arrives', async () => {
    await render([]);

    injectFakeRealtime().notifications.next(makeNotification({ title: 'New claim submitted' }));
    http.expectOne(APPROVALS_URL).flush(queue);
    await fixture.whenStable();

    expect(rows('.row.attention')).toHaveLength(2);
  });
});
