import { DatePipe } from '@angular/common';
import { Component, DestroyRef, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { filter } from 'rxjs';

import { ClaimsApi } from '../../../core/api/claims.api';
import { PlatformApi } from '../../../core/api/platform.api';
import { errorMessage } from '../../../core/auth/auth.interceptor';
import { PolicyStore } from '../../../core/config/policy.store';
import { EDITABLE_STATUSES, receiptSubtitle } from '../../../core/models/display';
import { Attachment, Claim } from '../../../core/models/models';
import { RealtimeService } from '../../../core/realtime/realtime.service';
import { ToastService } from '../../../core/ui/toast.service';
import { AttachmentViewer } from '../../../shared/components/attachment-viewer';
import { Confetti } from '../../../shared/components/confetti';
import { StatusPill } from '../../../shared/components/status-pill';
import { MoneyPipe } from '../../../shared/pipes/money.pipe';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';

const TIMELINE_ICON: Partial<Record<string, string>> = {
  draft: '📝',
  submitted: '📨',
  manager_review: '👀',
  approved: '✅',
  finance_processing: '🏦',
  paid: '💸',
  rejected: '↩️',
  reopened: '🔁',
};

@Component({
  selector: 'app-claim-detail',
  imports: [RouterLink, FormsModule, DatePipe, StatusPill, MoneyPipe, RelativeTimePipe, Confetti, AttachmentViewer],
  templateUrl: './claim-detail.html',
  styleUrl: './claim-detail.scss',
})
export class ClaimDetailPage {
  readonly id = input.required<string>();
  /** 'approval' when opened by a manager from the approvals queue (route data). */
  readonly mode = input<'owner' | 'approval'>('owner');

  private readonly claimsApi = inject(ClaimsApi);
  private readonly platformApi = inject(PlatformApi);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  protected readonly policy = inject(PolicyStore);

  protected readonly claim = signal<Claim | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly comment = signal('');
  protected readonly deciding = signal(false);
  protected readonly celebrate = signal(false);
  protected readonly viewerIndex = signal<number | null>(null);

  protected readonly isApproval = computed(() => this.mode() === 'approval');
  protected readonly canDecide = computed(() => this.isApproval() && this.claim()?.status === 'submitted');
  protected readonly timelineIcon = TIMELINE_ICON;
  protected readonly flagged = computed(() =>
    (this.claim()?.receipts ?? []).filter((r) => !r.excluded && r.flags.some((f) => f.severity !== 'info')),
  );
  protected readonly activeReceipts = computed(() => (this.claim()?.receipts ?? []).filter((r) => !r.excluded));
  protected readonly attachments = computed<Attachment[]>(() =>
    this.activeReceipts().map((r) =>
      this.claimsApi.attachment(r, receiptSubtitle(r, this.policy), this.isApproval()),
    ),
  );

  constructor() {
    effect(() => {
      const id = this.id();
      untracked(() => this.load(id));
    });

    inject(RealtimeService)
      .claimUpdates.pipe(
        filter((c) => c.id === this.claim()?.id),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe((c) => {
        if (c.status === 'paid' && this.claim()?.status !== 'paid') this.celebrate.set(true);
        this.claim.set(c);
      });
  }

  private load(id: string): void {
    const request = this.isApproval() ? this.platformApi.approval(id) : this.claimsApi.get(id);
    request.subscribe({
      next: (claim) => {
        if (!this.isApproval() && EDITABLE_STATUSES.includes(claim.status)) {
          this.router.navigate(['/agent', claim.id], { replaceUrl: true });
          return;
        }
        this.claim.set(claim);
      },
      error: (err) => this.error.set(errorMessage(err, 'Claim not found')),
    });
  }

  protected decide(decision: 'approve' | 'reject'): void {
    const claim = this.claim();
    if (!claim) return;
    if (decision === 'reject' && !this.comment().trim()) {
      this.toast.show({ level: 'warning', title: 'Add a comment', message: 'Tell the employee what to fix.' });
      return;
    }
    this.deciding.set(true);
    this.platformApi.decide(claim.id, decision, this.comment().trim()).subscribe({
      next: (updated) => {
        this.deciding.set(false);
        this.claim.set(updated);
        if (decision === 'approve') this.celebrate.set(true);
        this.toast.success(decision === 'approve' ? 'Claim approved' : 'Claim returned to employee');
      },
      error: (err) => {
        this.deciding.set(false);
        this.toast.error('Action failed', errorMessage(err));
      },
    });
  }

  protected reopen(): void {
    const claim = this.claim();
    if (!claim) return;
    this.claimsApi.reopen(claim.id).subscribe({
      next: () => this.router.navigate(['/agent', claim.id]),
      error: (err) => this.toast.error('Could not reopen', errorMessage(err)),
    });
  }

  protected exportUrl(): string {
    return this.claimsApi.exportUrl(this.claim()?.id ?? '');
  }

  protected zipUrl(): string {
    return this.claimsApi.attachmentsZipUrl(this.claim()?.id ?? '', this.isApproval());
  }

  protected openAttachment(receiptId: string): void {
    const index = this.attachments().findIndex((a) => a.id === receiptId);
    if (index >= 0) this.viewerIndex.set(index);
  }

  protected maxGroup(): number {
    return Math.max(1, ...(this.claim()?.groups ?? []).map((g) => g.total));
  }
}
