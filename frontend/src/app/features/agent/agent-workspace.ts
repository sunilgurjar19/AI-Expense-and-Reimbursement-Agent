import { DatePipe } from '@angular/common';
import { HttpEventType } from '@angular/common/http';
import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';
import { Observable, filter, of, switchMap, tap } from 'rxjs';

import { ClaimsApi } from '../../core/api/claims.api';
import { errorMessage } from '../../core/auth/auth.interceptor';
import { AuthService } from '../../core/auth/auth.service';
import { PolicyStore } from '../../core/config/policy.store';
import { EDITABLE_STATUSES, receiptSubtitle } from '../../core/models/display';
import { Attachment, Claim, Question, Receipt, ReceiptUpdate } from '../../core/models/models';
import { RealtimeService } from '../../core/realtime/realtime.service';
import { ToastService } from '../../core/ui/toast.service';
import { CountUp } from '../../shared/components/count-up';
import { ReadinessRing } from '../../shared/components/readiness-ring';
import { AttachmentViewer } from '../../shared/components/attachment-viewer';
import { StatusPill } from '../../shared/components/status-pill';
import { MoneyPipe } from '../../shared/pipes/money.pipe';
import { ChatPanel } from './components/chat-panel';
import { ClaimJourney } from './components/claim-journey';
import { DropZone } from './components/drop-zone';
import { ReceiptCard } from './components/receipt-card';
import { ReceiptDrawer } from './components/receipt-drawer';
import { SubmitDialog } from './components/submit-dialog';
import {
  createPayload,
  createUnsavedClaim,
  localUserMessage,
  welcomeMessage,
} from './unsaved-claim';

@Component({
  selector: 'app-agent-workspace',
  imports: [
    RouterLink,
    DatePipe,
    ChatPanel,
    ClaimJourney,
    DropZone,
    ReceiptCard,
    ReceiptDrawer,
    SubmitDialog,
    ReadinessRing,
    StatusPill,
    AttachmentViewer,
    CountUp,
    MoneyPipe,
  ],
  templateUrl: './agent-workspace.html',
  styleUrl: './agent-workspace.scss',
})
export class AgentWorkspace {
  /** Claim id from the route; empty means "start a new claim". */
  readonly id = input<string>();

  private readonly api = inject(ClaimsApi);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);
  private readonly auth = inject(AuthService);
  protected readonly policy = inject(PolicyStore);

  protected readonly claim = signal<Claim | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly uploadProgress = signal<number | null>(null);
  protected readonly thinking = signal(false);
  protected readonly answering = signal<string | null>(null);
  protected readonly selectedReceiptId = signal<string | null>(null);
  protected readonly showSubmit = signal(false);
  protected readonly editingTitle = signal(false);
  protected readonly saving = signal(false);
  protected readonly confirmDelete = signal(false);
  protected readonly editingRemarks = signal(false);
  protected readonly savingRemarks = signal(false);

  protected readonly editable = computed(() => {
    const claim = this.claim();
    return !!claim && EDITABLE_STATUSES.includes(claim.status);
  });
  /** True until the claim is first persisted on the server. */
  protected readonly isNew = computed(() => !this.claim()?.id);
  protected readonly messages = computed(() => {
    const claim = this.claim();
    if (!claim) return [];
    if (!this.isNew()) return claim.messages;
    const firstName = this.auth.user()?.name.split(' ')[0] ?? 'there';
    return [welcomeMessage(firstName, this.policy.agentName()), ...claim.messages];
  });
  protected readonly receipts = computed(() => this.claim()?.receipts ?? []);
  protected readonly processingCount = computed(
    () => this.receipts().filter((r) => r.status === 'processing').length,
  );
  protected readonly selectedReceipt = computed(
    () => this.receipts().find((r) => r.id === this.selectedReceiptId()) ?? null,
  );
  /** Every uploaded document, viewable and downloadable at any stage. */
  protected readonly attachments = computed<Attachment[]>(() =>
    this.receipts().map((r) => this.api.attachment(r, receiptSubtitle(r, this.policy))),
  );
  protected readonly viewerIndex = signal<number | null>(null);
  protected readonly attentionCount = computed(
    () =>
      this.receipts().filter((r) => ['needs_info', 'questionable', 'failed'].includes(r.status))
        .length,
  );

  constructor() {
    effect(() => {
      const id = this.id();
      untracked(() => {
        if (!id) this.startNewClaim();
        else if (id !== this.claim()?.id) this.load(id); // skip when we just saved this claim ourselves
      });
    });

    inject(RealtimeService)
      .claimUpdates.pipe(
        filter((update) => update.id === this.claim()?.id),
        takeUntilDestroyed(inject(DestroyRef)),
      )
      .subscribe((update) => this.apply(update));
  }

  // ------------------------------------------------------------ loading

  /** Show an empty workspace without creating anything on the server yet. */
  private startNewClaim(): void {
    this.loadError.set(null);
    this.selectedReceiptId.set(null);
    this.showSubmit.set(false);
    this.confirmDelete.set(false);
    this.claim.set(createUnsavedClaim(this.policy.currency()));
  }

  /** Persist the claim on first real action and move the URL to /agent/:id. */
  private ensureSaved(): Observable<Claim> {
    const claim = this.claim();
    if (claim?.id) return of(claim);
    return this.api.create(createPayload(claim)).pipe(
      tap((created) => {
        this.claim.set(created);
        this.router.navigate(['/agent', created.id], { replaceUrl: true });
      }),
    );
  }

  private load(id: string): void {
    this.api.get(id).subscribe({
      next: (claim) => {
        if (!EDITABLE_STATUSES.includes(claim.status) && !this.showSubmit()) {
          this.router.navigate(['/claims', claim.id], { replaceUrl: true });
          return;
        }
        this.claim.set(claim);
      },
      error: (err) => this.loadError.set(errorMessage(err, 'Claim not found')),
    });
  }

  /** Ignore stale snapshots that arrive out of order (SSE vs HTTP responses). */
  private apply(update: Claim): void {
    const current = this.claim();
    if (!current || update.updated_at >= current.updated_at) this.claim.set(update);
  }

  // ------------------------------------------------------------ actions

  protected upload(files: File[]): void {
    if (!this.claim() || !files.length) return;
    this.uploadProgress.set(0);
    this.ensureSaved()
      .pipe(switchMap((claim) => this.api.upload(claim.id, files)))
      .subscribe({
        next: (event) => {
          if (event.type === HttpEventType.UploadProgress && event.total) {
            this.uploadProgress.set(Math.round((100 * event.loaded) / event.total));
          } else if (event.type === HttpEventType.Response) {
            this.uploadProgress.set(null);
          }
        },
        error: (err) => {
          this.uploadProgress.set(null);
          this.toast.error('Upload failed', errorMessage(err));
        },
      });
  }

  protected answer(event: { question: Question; value: unknown }): void {
    const claim = this.claim();
    if (!claim) return;
    this.answering.set(event.question.id);
    this.api.answer(claim.id, event.question.id, event.value).subscribe({
      next: (updated) => {
        this.answering.set(null);
        this.apply(updated);
      },
      error: (err) => {
        this.answering.set(null);
        this.toast.error("Couldn't use that answer", errorMessage(err));
      },
    });
  }

  protected chat(message: string): void {
    if (!this.claim()) return;
    this.thinking.set(true);
    this.ensureSaved()
      .pipe(
        // Show the user's message immediately while the agent thinks.
        tap((claim) =>
          this.claim.set({ ...claim, messages: [...claim.messages, localUserMessage(message)] }),
        ),
        switchMap((claim) => this.api.chat(claim.id, message)),
      )
      .subscribe({
        next: (updated) => {
          this.thinking.set(false);
          this.claim.set(updated);
        },
        error: (err) => {
          this.thinking.set(false);
          this.toast.error('Agent unavailable', errorMessage(err));
        },
      });
  }

  protected saveReceipt(receipt: Receipt, update: ReceiptUpdate): void {
    this.api.updateReceipt(receipt.claim_id, receipt.id, update).subscribe({
      next: (claim) => {
        this.apply(claim);
        this.toast.success('Receipt updated');
      },
      error: (err) => this.toast.error('Update failed', errorMessage(err)),
    });
  }

  protected removeReceipt(receipt: Receipt): void {
    this.selectedReceiptId.set(null);
    this.api.deleteReceipt(receipt.claim_id, receipt.id).subscribe({
      next: (claim) => this.apply(claim),
      error: (err) => this.toast.error('Delete failed', errorMessage(err)),
    });
  }

  protected retryReceipt(receipt: Receipt): void {
    this.api.retryReceipt(receipt.claim_id, receipt.id).subscribe({
      next: (claim) => this.apply(claim),
      error: (err) => this.toast.error('Retry failed', errorMessage(err)),
    });
  }

  protected renameClaim(title: string): void {
    this.editingTitle.set(false);
    const claim = this.claim();
    if (!claim || !title.trim() || title.trim() === claim.title) return;
    if (this.isNew()) {
      this.claim.set({ ...claim, title: title.trim(), title_is_auto: false });
      return;
    }
    this.api.update(claim.id, { title: title.trim() }).subscribe((updated) => this.apply(updated));
  }

  protected saveRemarks(text: string): void {
    const claim = this.claim();
    const purpose = text.trim();
    if (!claim) return;
    if (purpose === (claim.purpose ?? '')) {
      this.editingRemarks.set(false);
      return;
    }
    if (this.isNew()) {
      this.claim.set({
        ...claim,
        purpose: purpose || null,
        purpose_source: purpose ? 'user' : null,
      });
      this.editingRemarks.set(false);
      return;
    }
    this.savingRemarks.set(true);
    this.api.update(claim.id, { purpose }).subscribe({
      next: (updated) => {
        this.savingRemarks.set(false);
        this.editingRemarks.set(false);
        this.apply(updated);
        this.toast.success('Remarks updated');
      },
      error: (err) => {
        this.savingRemarks.set(false);
        this.toast.error('Could not save remarks', errorMessage(err));
      },
    });
  }

  protected saveDraft(): void {
    const claim = this.claim();
    if (!claim || this.saving()) return;
    this.saving.set(true);
    const save$ = claim.id ? of(claim) : this.api.create(createPayload(claim));
    save$.subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.toast.success(
          'Saved as draft',
          `“${saved.title}” is waiting for you under My claims.`,
        );
        this.router.navigate(['/claims']);
      },
      error: (err) => {
        this.saving.set(false);
        this.toast.error('Could not save draft', errorMessage(err));
      },
    });
  }

  protected deleteClaim(): void {
    const claim = this.claim();
    if (!claim?.id) return;
    this.api.delete(claim.id).subscribe({
      next: () => {
        this.toast.success('Claim deleted', `“${claim.title}” and its receipts were removed.`);
        this.router.navigate(['/claims']);
      },
      error: (err) => {
        this.confirmDelete.set(false);
        this.toast.error('Could not delete claim', errorMessage(err));
      },
    });
  }

  protected submitted(claim: Claim): void {
    this.claim.set(claim);
  }

  protected fileUrl(receipt: Receipt): string {
    return this.api.fileUrl(receipt.claim_id, receipt.id);
  }

  protected downloadUrl(receipt: Receipt): string {
    return this.api.fileUrl(receipt.claim_id, receipt.id, { download: true });
  }

  protected zipUrl(): string {
    return this.api.attachmentsZipUrl(this.claim()?.id ?? '');
  }

  protected viewDocument(receipt: Receipt): void {
    const index = this.attachments().findIndex((a) => a.id === receipt.id);
    if (index >= 0) this.viewerIndex.set(index);
  }

  protected exportUrl(): string {
    return this.api.exportUrl(this.claim()?.id ?? '');
  }
}
