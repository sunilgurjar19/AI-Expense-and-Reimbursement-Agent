import { Component, computed, input } from '@angular/core';

import { CLAIM_STATUS, RECEIPT_STATUS, StatusMeta } from '../../core/models/display';
import { ClaimStatus, ReceiptStatus } from '../../core/models/models';

@Component({
  selector: 'app-status-pill',
  template: `
    <span [class]="'pill tone-' + meta().tone" [class.live]="live()">
      @if (live()) {
        <span class="dot"></span>
      } @else {
        <span class="icon">{{ meta().icon }}</span>
      }
      {{ meta().label }}
    </span>
  `,
  styles: `
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 26px;
      padding: 0 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      white-space: nowrap;
      transition: background 0.3s, color 0.3s;
    }
    .icon { font-size: 11px; }
    .tone-neutral { background: #f1f5f9; color: #475569; }
    .tone-brand { background: var(--brand-50); color: var(--brand-700); }
    .tone-info { background: var(--info-bg); color: var(--info); }
    .tone-warning { background: var(--warning-bg); color: var(--warning); }
    .tone-success { background: var(--success-bg); color: var(--success); }
    .tone-danger { background: var(--danger-bg); color: var(--danger); }
    .dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      animation: pulse-ring 1.2s infinite;
    }
  `,
})
export class StatusPill {
  readonly claimStatus = input<ClaimStatus>();
  readonly receiptStatus = input<ReceiptStatus>();

  protected readonly meta = computed<StatusMeta>(() => {
    const receipt = this.receiptStatus();
    if (receipt) return RECEIPT_STATUS[receipt];
    return CLAIM_STATUS[this.claimStatus() ?? 'draft'];
  });

  protected readonly live = computed(
    () => this.claimStatus() === 'processing' || this.receiptStatus() === 'processing',
  );
}
