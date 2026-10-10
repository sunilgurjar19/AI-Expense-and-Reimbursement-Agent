import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { injectFakeRealtime, provideFakeRealtime, seedSession } from '@testing/fakes';
import { makeClaim, makeClaimSummary, makeDashboard, makeManager, makeUser } from '@testing/fixtures';

import { DashboardSummary, User } from '../../core/models/models';
import { DashboardPage } from './dashboard';

const DASHBOARD_URL = 'http://localhost:8100/api/dashboard';

describe('DashboardPage', () => {
  let fixture: ComponentFixture<DashboardPage>;
  let http: HttpTestingController;

  function setup(user: User = makeUser({ name: 'Asha Verma' })) {
    seedSession(user);
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
    fixture = TestBed.createComponent(DashboardPage);
  }

  async function render(data: DashboardSummary = makeDashboard(), user?: User) {
    setup(user);
    http.expectOne(DASHBOARD_URL).flush(data);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const kpiLabels = () => Array.from(el().querySelectorAll('.kpi-label')).map((k) => k.textContent);

  it('greets the user by first name and shows placeholders while loading', async () => {
    setup(makeUser({ name: 'Asha Verma' }));
    await fixture.whenStable();

    expect(el().querySelector('h1')!.textContent).toContain('Good to see you, Asha');
    expect(el().querySelectorAll('.kpi .skeleton')).toHaveLength(4);

    http.expectOne(DASHBOARD_URL).flush(makeDashboard());
  });

  it('shows the four headline KPIs for employees', async () => {
    await render(makeDashboard({ receipts_processed: 14 }));

    expect(kpiLabels()).toEqual(['Drafts in progress', 'Ready to submit', 'Awaiting reimbursement', 'Reimbursed']);
    expect(el().querySelector('.kpi-foot')!.textContent).toBe('14 receipts read so far');
  });

  it('adds a pending-approvals KPI for managers', async () => {
    await render(makeDashboard({ pending_approvals: 3 }), makeManager());

    expect(kpiLabels()).toContain('Pending approvals');
    expect(el().querySelector('a.kpi.manager')!.getAttribute('href')).toBe('/approvals');
  });

  it('links to claims with open questions', async () => {
    await render(makeDashboard({ pending_questions: 2 }));
    expect(el().querySelector('.pending')!.textContent).toContain('2 question(s) waiting for you');
  });

  it('hides the questions link when nothing is pending', async () => {
    await render(makeDashboard({ pending_questions: 0 }));
    expect(el().querySelector('.pending')).toBeNull();
  });

  describe('spend by category', () => {
    const data = makeDashboard({
      by_category: [
        { category: 'lodging', label: 'Lodging', icon: '🏨', total: 8_000 },
        { category: 'travel', label: 'Travel', icon: '🚕', total: 2_000 },
      ],
    });

    const bars = () => Array.from(el().querySelectorAll<HTMLElement>('.bar-row'));

    it('draws bars relative to the largest category and totals the spend', async () => {
      await render(data);

      expect(bars().map((b) => b.querySelector<HTMLElement>('.bar')!.style.width)).toEqual(['100%', '25%']);
      expect(bars()[1].querySelector('.bar-value')!.textContent).toBe('₹2K');
      expect(el().querySelector('.panel header .subtle')!.textContent).toContain('₹10,000.00 across all claims');
    });

    it("shows a category's share on hover and dims the others", async () => {
      await render(data);

      bars()[1].dispatchEvent(new Event('mouseenter'));
      await fixture.whenStable();

      expect(bars()[1].querySelector('.tooltip')!.textContent!.replace(/\s+/g, ' ').trim()).toBe('₹2,000.00 · 20% of spend');
      expect(bars()[0].classList).toContain('dim');
      expect(bars()[1].classList).not.toContain('dim');

      bars()[1].dispatchEvent(new Event('mouseleave'));
      await fixture.whenStable();
      expect(el().querySelector('.tooltip')).toBeNull();
    });

    it('explains the chart is empty before the first claim', async () => {
      await render(makeDashboard({ by_category: [] }));
      expect(el().querySelector('.panel .empty')!.textContent).toContain('Your spending breakdown appears');
    });
  });

  describe('recent claims', () => {
    it('lists recent claims linking to the right screen', async () => {
      await render(
        makeDashboard({
          recent: [
            makeClaimSummary({ id: 'c-1', title: 'Goa offsite', status: 'draft' }),
            makeClaimSummary({ id: 'c-2', title: 'Delhi trip', status: 'paid' }),
          ],
        }),
      );

      const rows = Array.from(el().querySelectorAll<HTMLAnchorElement>('.claim-row'));
      expect(rows.map((r) => r.querySelector('strong')!.textContent)).toEqual(['Goa offsite', 'Delhi trip']);
      expect(rows.map((r) => r.getAttribute('href'))).toEqual(['/agent/c-1', '/claims/c-2']);
    });

    it('invites the user to start a claim when there are none', async () => {
      await render(makeDashboard({ recent: [] }));
      expect(el().textContent).toContain('No claims yet');
    });
  });

  it('refreshes (debounced) when claims change in the background', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] });
    await render(makeDashboard({ pending_questions: 0 }));

    injectFakeRealtime().claimUpdates.next(makeClaim());
    vi.advanceTimersByTime(799);
    http.expectNone(DASHBOARD_URL);

    vi.advanceTimersByTime(1);
    http.expectOne(DASHBOARD_URL).flush(makeDashboard({ pending_questions: 4 }));
    await fixture.whenStable();

    expect(el().querySelector('.pending')!.textContent).toContain('4 question(s)');
  });
});
