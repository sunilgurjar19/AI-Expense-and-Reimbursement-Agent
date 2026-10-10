import { DatePipe } from '@angular/common';
import { Component, computed, input, output } from '@angular/core';

import { PIPELINE } from '../../../core/models/display';
import { CategoryRule, Receipt } from '../../../core/models/models';
import { StatusPill } from '../../../shared/components/status-pill';
import { MoneyPipe } from '../../../shared/pipes/money.pipe';

@Component({
  selector: 'app-receipt-card',
  imports: [DatePipe, StatusPill, MoneyPipe],
  templateUrl: './receipt-card.html',
  styleUrl: './receipt-card.scss',
})
export class ReceiptCard {
  readonly receipt = input.required<Receipt>();
  readonly currency = input('INR');
  readonly fileUrl = input.required<string>();
  readonly downloadUrl = input.required<string>();
  readonly category = input<CategoryRule | undefined>();
  readonly open = output<void>();
  /** View the original document in the attachment viewer. */
  readonly view = output<void>();

  protected readonly pipeline = PIPELINE;

  protected readonly isImage = computed(() => this.receipt().mime_type.startsWith('image/'));
  protected readonly processing = computed(() => this.receipt().status === 'processing');
  protected readonly stageIndex = computed(() => {
    const stage = this.receipt().stage;
    return stage === 'failed' ? -1 : PIPELINE.findIndex((s) => s.stage === stage);
  });
  protected readonly stageLabel = computed(() => PIPELINE[this.stageIndex()]?.label ?? 'Failed');
  protected readonly topFlags = computed(() =>
    this.receipt()
      .flags.filter((f) => f.severity !== 'info')
      .slice(0, 2),
  );
  protected readonly capped = computed(() => {
    const r = this.receipt();
    return r.reimbursable_amount !== null && r.amount_in_base !== null && r.reimbursable_amount < r.amount_in_base;
  });
}
