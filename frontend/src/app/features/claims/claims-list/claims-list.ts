import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { debounceTime } from 'rxjs';

import { ClaimsApi } from '../../../core/api/claims.api';
import { errorMessage } from '../../../core/auth/auth.interceptor';
import { EDITABLE_STATUSES, claimLink } from '../../../core/models/display';
import { ClaimStatus, ClaimSummary } from '../../../core/models/models';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { ToastService } from '../../../core/ui/toast.service';
import { StatusPill } from '../../../shared/components/status-pill';
import { MoneyPipe } from '../../../shared/pipes/money.pipe';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';

interface Tab {
  key: string;
  label: string;
  statuses: ClaimStatus[] | null;
}

const TABS: Tab[] = [
  { key: 'all', label: 'All', statuses: null },
  { key: 'open', label: 'In progress', statuses: EDITABLE_STATUSES },
  { key: 'review', label: 'In approval', statuses: ['submitted', 'approved'] },
  { key: 'paid', label: 'Reimbursed', statuses: ['paid'] },
  { key: 'returned', label: 'Returned', statuses: ['rejected'] },
];

@Component({
  selector: 'app-claims-list',
  imports: [RouterLink, StatusPill, MoneyPipe, RelativeTimePipe],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>My claims</h1>
          <p>Every claim, from first receipt to payout.</p>
        </div>
        <a routerLink="/agent" class="btn btn-primary">✨ New claim</a>
      </div>

      <div class="toolbar">
        <div class="tabs">
          @for (t of tabs; track t.key) {
            <button class="tab" [class.active]="tab() === t.key" (click)="tab.set(t.key)">
              {{ t.label }} <span class="count">{{ count(t) }}</span>
            </button>
          }
        </div>
        <input class="input search" placeholder="🔍 Search claims…" [value]="query()" (input)="query.set($any($event.target).value)" />
      </div>

      @if (loading()) {
        <div class="grid">
          @for (i of [1, 2, 3]; track i) { <div class="card skeleton" style="height: 170px"></div> }
        </div>
      } @else if (filtered().length) {
        <div class="grid stagger">
          @for (c of filtered(); track c.id) {
            <div class="claim-wrap" animate.leave="leave-fade">
            <a class="claim card card-hover" [routerLink]="link(c)">
              <div class="top">
                <app-status-pill [claimStatus]="c.status" />
                @if (c.reference_no) { <span class="ref">{{ c.reference_no }}</span> }
              </div>
              <h3>{{ c.title }}</h3>
              <p class="subtle">{{ c.receipt_count }} receipt{{ c.receipt_count === 1 ? '' : 's' }} · updated {{ c.updated_at | relativeTime }}</p>
              <div class="bottom">
                <div class="progress"><i [style.width.%]="c.readiness"></i></div>
                <strong>{{ c.total_reimbursable | money: c.currency }}</strong>
              </div>
              @if (c.pending_questions && c.status === 'needs_attention') {
                <span class="ask">💬 {{ c.pending_questions }} question(s) for you</span>
              }
            </a>
            @if (isDeletable(c)) {
              @if (confirmingId() === c.id) {
                <div class="confirm" animate.enter="enter-fade-up">
                  <strong>Delete this draft?</strong>
                  <span>{{ c.receipt_count ? c.receipt_count + ' receipt(s) will be removed.' : 'It has no receipts yet.' }}</span>
                  <div class="confirm-actions">
                    <button class="btn btn-ghost btn-sm" (click)="confirmingId.set(null)">Cancel</button>
                    <button class="btn btn-danger btn-sm" [disabled]="deletingId() === c.id" (click)="remove(c)">
                      @if (deletingId() === c.id) { <span class="spinner"></span> } Delete
                    </button>
                  </div>
                </div>
              } @else {
                <button class="delete" title="Delete this draft" (click)="confirmingId.set(c.id)">🗑 Delete</button>
              }
            }
            </div>
          }
        </div>
      } @else {
        <div class="empty card">
          <span>🗂️</span>
          <h3>No claims here yet</h3>
          <p class="muted">Start a claim and drop your receipts - the agent does the rest.</p>
          <a routerLink="/agent" class="btn btn-primary">Start a claim</a>
        </div>
      }
    </div>
  `,
  styles: `
    .toolbar { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }
    .tabs { display: flex; gap: 4px; padding: 4px; border-radius: 12px; background: var(--surface); border: 1px solid var(--border); }
    .tab {
      height: 34px; padding: 0 14px; border: none; border-radius: 9px; background: none; cursor: pointer;
      font-weight: 600; color: var(--text-2); transition: all 0.2s var(--ease);
    }
    .tab:hover { color: var(--text); }
    .tab.active { background: var(--gradient); color: #fff; box-shadow: 0 6px 14px -6px rgb(79 70 229 / 60%); }
    .count { margin-left: 4px; padding: 1px 7px; border-radius: 999px; background: rgb(0 0 0 / 6%); font-size: 11px; }
    .tab.active .count { background: rgb(255 255 255 / 25%); }
    .search { width: 280px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
    .claim-wrap { position: relative; }
    .claim { display: flex; flex-direction: column; gap: 8px; height: 100%; padding: 18px; color: inherit; }
    .top { display: flex; justify-content: space-between; align-items: center; min-height: 30px; }
    .delete {
      position: absolute; top: 16px; right: 16px; height: 28px; padding: 0 10px; border-radius: 999px;
      border: 1px solid var(--border); background: var(--surface); color: var(--text-2); cursor: pointer;
      font-size: 12px; font-weight: 600; transition: all 0.2s var(--ease);
    }
    .delete:hover { background: var(--danger-bg); border-color: #fecaca; color: var(--danger); transform: translateY(-1px); }
    .confirm {
      position: absolute; inset: 0; z-index: 2; border-radius: var(--radius);
      display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px;
      background: rgb(255 255 255 / 94%); backdrop-filter: blur(3px); border: 1px solid #fecaca; text-align: center;
    }
    .confirm strong { color: var(--danger); }
    .confirm span { font-size: 13px; color: var(--text-2); }
    .confirm-actions { display: flex; gap: 8px; margin-top: 10px; }
    .ref { font-size: 12px; font-weight: 700; color: var(--brand-700); font-family: ui-monospace, monospace; }
    h3 { font-size: 16px; font-weight: 700; }
    .subtle { margin: 0; }
    .bottom { display: flex; align-items: center; gap: 14px; margin-top: 6px; }
    .progress { flex: 1; height: 6px; border-radius: 6px; background: var(--brand-100); overflow: hidden; }
    .progress i { display: block; height: 100%; border-radius: 6px; background: var(--brand-600); transition: width 0.8s var(--ease); }
    .bottom strong { font-size: 17px; font-weight: 800; }
    .ask { align-self: flex-start; padding: 4px 10px; border-radius: 999px; background: var(--warning-bg); color: var(--warning); font-size: 12px; font-weight: 600; }
    .empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 56px; text-align: center; }
    .empty span { font-size: 44px; animation: float 3s ease-in-out infinite; }
    .empty p { margin: 0 0 8px; }
  `,
})
export class ClaimsListPage {
  private readonly api = inject(ClaimsApi);
  private readonly toast = inject(ToastService);

  protected readonly tabs = TABS;
  protected readonly link = claimLink;
  protected readonly claims = signal<ClaimSummary[]>([]);
  protected readonly loading = signal(true);
  protected readonly tab = signal('all');
  protected readonly query = signal('');
  protected readonly confirmingId = signal<string | null>(null);
  protected readonly deletingId = signal<string | null>(null);

  protected readonly filtered = computed(() => {
    const tab = TABS.find((t) => t.key === this.tab());
    const q = this.query().trim().toLowerCase();
    return this.claims().filter(
      (c) =>
        (!tab?.statuses || tab.statuses.includes(c.status)) &&
        (!q || c.title.toLowerCase().includes(q) || (c.reference_no ?? '').toLowerCase().includes(q)),
    );
  });

  constructor() {
    this.load();
    inject(RealtimeService)
      .claimUpdates.pipe(debounceTime(600), takeUntilDestroyed(inject(DestroyRef)))
      .subscribe(() => this.load());
  }

  protected count(tab: Tab): number {
    return tab.statuses ? this.claims().filter((c) => tab.statuses!.includes(c.status)).length : this.claims().length;
  }

  /** Anything not yet submitted can be deleted. */
  protected isDeletable(claim: ClaimSummary): boolean {
    return EDITABLE_STATUSES.includes(claim.status);
  }

  protected remove(claim: ClaimSummary): void {
    this.deletingId.set(claim.id);
    this.api.delete(claim.id).subscribe({
      next: () => {
        this.deletingId.set(null);
        this.confirmingId.set(null);
        this.claims.update((list) => list.filter((c) => c.id !== claim.id));
        this.toast.success('Draft deleted', `“${claim.title}” was removed.`);
      },
      error: (err) => {
        this.deletingId.set(null);
        this.toast.error('Could not delete', errorMessage(err));
      },
    });
  }

  private load(): void {
    this.api.list().subscribe({
      next: (claims) => {
        this.claims.set(claims);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }
}
