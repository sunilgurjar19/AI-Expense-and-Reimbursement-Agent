import { Component, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { PlatformApi } from '../../core/api/platform.api';
import { ClaimSummary } from '../../core/models/models';
import { RealtimeService } from '../../core/realtime/realtime.service';
import { StatusPill } from '../../shared/components/status-pill';
import { MoneyPipe } from '../../shared/pipes/money.pipe';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';

@Component({
  selector: 'app-approvals-list',
  imports: [RouterLink, StatusPill, MoneyPipe, RelativeTimePipe],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Team approvals</h1>
          <p>Claims prepared by the agent and submitted by your team.</p>
        </div>
      </div>

      <section class="summary stagger">
        <div class="card stat"><span>Waiting for you</span><strong>{{ pending().length }}</strong></div>
        <div class="card stat"><span>Pending amount</span><strong>{{ pendingAmount() | money: currency() }}</strong></div>
        <div class="card stat"><span>Decided</span><strong>{{ decided().length }}</strong></div>
      </section>

      <h3 class="section-title">Waiting for your decision</h3>
      @if (pending().length) {
        <div class="list stagger">
          @for (c of pending(); track c.id) {
            <a class="row card card-hover attention" [routerLink]="['/approvals', c.id]">
              <div class="avatar">{{ c.owner_name?.[0] }}</div>
              <div class="main">
                <strong>{{ c.title }}</strong>
                <span class="subtle">{{ c.owner_name }} · {{ c.reference_no }} · submitted {{ c.submitted_at | relativeTime }}</span>
              </div>
              <span class="count">{{ c.receipt_count }} items</span>
              <strong class="amount">{{ c.total_reimbursable | money: c.currency }}</strong>
              <span class="btn btn-primary btn-sm">Review →</span>
            </a>
          }
        </div>
      } @else {
        <div class="card empty">🎉 Inbox zero - nothing waiting for approval.</div>
      }

      @if (decided().length) {
        <h3 class="section-title">Recently decided</h3>
        <div class="list">
          @for (c of decided(); track c.id) {
            <a class="row card card-hover" [routerLink]="['/approvals', c.id]">
              <div class="avatar muted-av">{{ c.owner_name?.[0] }}</div>
              <div class="main">
                <strong>{{ c.title }}</strong>
                <span class="subtle">{{ c.owner_name }} · {{ c.reference_no }}</span>
              </div>
              <app-status-pill [claimStatus]="c.status" />
              <strong class="amount">{{ c.total_reimbursable | money: c.currency }}</strong>
            </a>
          }
        </div>
      }
    </div>
  `,
  styles: `
    .summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 26px; }
    .stat { display: flex; flex-direction: column; gap: 4px; padding: 18px 20px; }
    .stat span { font-size: 13px; font-weight: 600; color: var(--text-2); }
    .stat strong { font-size: 28px; font-weight: 700; }
    .section-title { font-size: 15px; font-weight: 700; margin: 0 0 12px; }
    .list { display: flex; flex-direction: column; gap: 10px; margin-bottom: 28px; }
    .row { display: flex; align-items: center; gap: 16px; padding: 14px 18px; color: inherit; }
    .row.attention { border-left: 4px solid var(--accent-500); }
    .avatar { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 50%; background: var(--gradient); color: #fff; font-weight: 700; }
    .muted-av { background: #cbd5e1; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .count { font-size: 12px; color: var(--text-3); }
    .amount { min-width: 120px; text-align: right; font-size: 16px; }
    .empty { padding: 28px; text-align: center; color: var(--text-2); margin-bottom: 28px; }
  `,
})
export class ApprovalsListPage {
  private readonly api = inject(PlatformApi);

  protected readonly claims = signal<ClaimSummary[]>([]);
  protected readonly pending = computed(() => this.claims().filter((c) => c.status === 'submitted'));
  protected readonly decided = computed(() => this.claims().filter((c) => c.status !== 'submitted'));
  protected readonly pendingAmount = computed(() => this.pending().reduce((s, c) => s + c.total_reimbursable, 0));
  protected readonly currency = computed(() => this.claims()[0]?.currency ?? 'INR');

  constructor() {
    this.load();
    // New submissions arrive as notifications for the manager - refresh on each one.
    inject(RealtimeService)
      .notifications.pipe(takeUntilDestroyed())
      .subscribe(() => this.load());
  }

  private load(): void {
    this.api.approvals().subscribe((claims) => this.claims.set(claims));
  }
}
