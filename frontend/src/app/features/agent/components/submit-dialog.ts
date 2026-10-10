import { Component, HostListener, inject, input, output, signal } from '@angular/core';
import { Router } from '@angular/router';

import { ClaimsApi } from '../../../core/api/claims.api';
import { errorMessage } from '../../../core/auth/auth.interceptor';
import { Claim } from '../../../core/models/models';
import { Confetti } from '../../../shared/components/confetti';
import { MoneyPipe } from '../../../shared/pipes/money.pipe';

type Phase = 'review' | 'submitting' | 'done';

@Component({
  selector: 'app-submit-dialog',
  imports: [MoneyPipe, Confetti],
  template: `
    <div class="overlay" animate.enter="fade" (click)="phase() !== 'submitting' && closed.emit()">
      <div class="dialog" animate.enter="enter-pop" (click)="$event.stopPropagation()" role="dialog" aria-modal="true">
        @switch (phase()) {
          @case ('done') {
            <div class="done">
              <div class="burst">🎉</div>
              <h2>Claim submitted!</h2>
              <p class="muted">Your reference number</p>
              <div class="ref">{{ result()?.reference_no }}</div>
              <ol class="next">
                <li class="ok">✓ Submitted to finance system</li>
                <li class="now">⏳ Waiting for manager approval</li>
                <li>💸 Payout to your salary account</li>
              </ol>
              <p class="subtle">We'll notify you at every step.</p>
              <div class="actions">
                <button class="btn btn-ghost" (click)="go(['/agent'])">Start another claim</button>
                <button class="btn btn-primary" (click)="go(['/claims', result()!.id])">Track this claim →</button>
              </div>
            </div>
          }
          @default {
            <h2>Ready to submit?</h2>
            <p class="muted">{{ claim().title }}</p>
            @if (claim().purpose) {
              <p class="remarks"><strong>Remarks:</strong> {{ claim().purpose }}</p>
            }

            <div class="summary">
              @for (g of claim().groups; track g.category) {
                <div class="line"><span>{{ g.icon }} {{ g.label }} <small>×{{ g.count }}</small></span><span>{{ g.total | money: claim().currency }}</span></div>
              }
              @if (claim().total_claimed !== claim().total_reimbursable) {
                <div class="line adj"><span>Policy adjustments</span>
                  <span>−{{ claim().total_claimed - claim().total_reimbursable | money: claim().currency }}</span></div>
              }
              <div class="line total"><span>You'll be reimbursed</span><span>{{ claim().total_reimbursable | money: claim().currency }}</span></div>
            </div>

            <label class="declare">
              <input type="checkbox" [checked]="agreed()" (change)="agreed.set(!agreed())" />
              I confirm these expenses were incurred for business and haven't been claimed before.
            </label>

            @if (error()) {
              <p class="error">⛔ {{ error() }}</p>
            }

            <div class="actions">
              <button class="btn btn-ghost" [disabled]="phase() === 'submitting'" (click)="closed.emit()">Not yet</button>
              <button class="btn btn-primary" [disabled]="!agreed() || phase() === 'submitting'" (click)="submit()">
                @if (phase() === 'submitting') { <span class="spinner"></span> Submitting… } @else { 🚀 Submit claim }
              </button>
            </div>
          }
        }
      </div>
    </div>
    @if (phase() === 'done') {
      <app-confetti />
    }
  `,
  styles: `
    .overlay { position: fixed; inset: 0; z-index: 300; display: grid; place-items: center; padding: 20px;
      background: rgb(15 23 42 / 45%); backdrop-filter: blur(4px); }
    .fade { animation: fade-up 0.3s ease both; }
    .dialog { width: min(500px, 100%); padding: 28px; border-radius: 22px; background: var(--surface); box-shadow: var(--shadow-lg); }
    h2 { font-size: 22px; font-weight: 800; }
    .muted { margin: 4px 0 18px; }
    .remarks { margin: -8px 0 16px; padding: 10px 12px; border-radius: 10px; background: var(--surface-2); font-size: 13px; color: var(--text-2); }
    .summary { border: 1px solid var(--border); border-radius: 14px; overflow: hidden; }
    .line { display: flex; justify-content: space-between; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 14px; }
    .line small { color: var(--text-3); }
    .line.adj { color: var(--warning); }
    .line.total { border-bottom: none; background: var(--gradient-soft); font-weight: 800; font-size: 16px; }
    .declare { display: flex; gap: 10px; align-items: flex-start; margin: 18px 0 4px; font-size: 13px; color: var(--text-2); cursor: pointer; }
    .declare input { margin-top: 3px; accent-color: var(--brand-600); }
    .error { color: var(--danger); font-size: 13px; }
    .actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
    .done { text-align: center; }
    .burst { font-size: 64px; animation: pop-in 0.6s var(--spring) both, float 3s 0.6s ease-in-out infinite; }
    .ref { display: inline-block; margin: 6px 0 18px; padding: 10px 20px; border-radius: 12px; font-size: 22px; font-weight: 800;
      letter-spacing: 0.04em; background: var(--gradient-soft); border: 1px dashed var(--brand-400); color: var(--brand-700);
      animation: pop-in 0.5s 0.25s var(--spring) both; }
    .next { list-style: none; padding: 0; margin: 0 auto 12px; max-width: 300px; text-align: left; display: flex; flex-direction: column; gap: 8px; }
    .next li { padding: 8px 12px; border-radius: 10px; background: var(--surface-2); font-size: 13px; color: var(--text-2);
      animation: fade-up 0.4s var(--ease) both; }
    .next li:nth-child(1) { animation-delay: 0.4s; } .next li:nth-child(2) { animation-delay: 0.55s; } .next li:nth-child(3) { animation-delay: 0.7s; }
    .next .ok { background: var(--success-bg); color: var(--success); font-weight: 600; }
    .next .now { background: var(--info-bg); color: var(--info); font-weight: 600; }
    .done .actions { justify-content: center; }
  `,
})
export class SubmitDialog {
  readonly claim = input.required<Claim>();
  readonly closed = output<void>();
  readonly submitted = output<Claim>();

  private readonly api = inject(ClaimsApi);
  private readonly router = inject(Router);

  protected readonly phase = signal<Phase>('review');
  protected readonly agreed = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly result = signal<Claim | null>(null);

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    if (this.phase() === 'review') this.closed.emit();
  }

  protected submit(): void {
    this.phase.set('submitting');
    this.error.set(null);
    this.api.submit(this.claim().id).subscribe({
      next: (claim) => {
        this.result.set(claim);
        this.phase.set('done');
        this.submitted.emit(claim);
      },
      error: (err) => {
        this.phase.set('review');
        this.error.set(errorMessage(err, 'Submission failed'));
      },
    });
  }

  protected go(commands: string[]): void {
    this.closed.emit();
    this.router.navigate(commands);
  }
}
