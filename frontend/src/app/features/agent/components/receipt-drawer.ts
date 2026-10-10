import { Component, HostListener, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { PolicyStore } from '../../../core/config/policy.store';
import { FIELD_LABELS } from '../../../core/models/display';
import { Receipt, ReceiptUpdate } from '../../../core/models/models';
import { StatusPill } from '../../../shared/components/status-pill';
import { MoneyPipe } from '../../../shared/pipes/money.pipe';

type FormValue = Required<Omit<ReceiptUpdate, 'excluded'>>;

const TEXT_FIELDS = ['vendor', 'invoice_number', 'location', 'payment_method'] as const;

@Component({
  selector: 'app-receipt-drawer',
  imports: [FormsModule, NgTemplateOutlet, StatusPill, MoneyPipe],
  templateUrl: './receipt-drawer.html',
  styleUrl: './receipt-drawer.scss',
})
export class ReceiptDrawer {
  readonly receipt = input.required<Receipt>();
  readonly fileUrl = input.required<string>();
  readonly downloadUrl = input.required<string>();
  readonly editable = input(true);
  readonly currency = input('INR');

  readonly closed = output<void>();
  readonly save = output<ReceiptUpdate>();
  readonly remove = output<void>();
  readonly retry = output<void>();
  readonly view = output<void>();

  protected readonly policy = inject(PolicyStore);
  private readonly sanitizer = inject(DomSanitizer);

  protected readonly labels = FIELD_LABELS;
  protected readonly textFields = TEXT_FIELDS;
  protected readonly form = signal<FormValue>(toForm(null));
  protected readonly confirmDelete = signal(false);

  protected readonly isImage = computed(() => this.receipt().mime_type.startsWith('image/'));
  protected readonly pdfUrl = computed<SafeResourceUrl>(() =>
    this.sanitizer.bypassSecurityTrustResourceUrl(this.fileUrl()),
  );
  protected readonly dirty = computed(() => Object.keys(this.changes()).length > 0);
  private readonly receiptId = computed(() => this.receipt().id);

  constructor() {
    // Re-seed the form when a different receipt is opened or it finishes processing.
    effect(() => {
      this.receiptId();
      this.receipt().stage;
      untracked(() => this.form.set(toForm(this.receipt())));
    });
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.closed.emit();
  }

  protected set<K extends keyof FormValue>(key: K, value: FormValue[K]): void {
    this.form.update((f) => ({ ...f, [key]: value }));
  }

  protected confidence(field: string): number | null {
    const value = this.receipt().confidence[field];
    return value === undefined ? null : Math.round(value * 100);
  }

  protected submit(): void {
    if (this.dirty()) this.save.emit(this.changes());
  }

  protected toggleExcluded(): void {
    this.save.emit({ excluded: !this.receipt().excluded });
  }

  /** Only send fields the user actually changed. */
  private changes(): ReceiptUpdate {
    const original = toForm(this.receipt());
    const current = this.form();
    const diff: Record<string, unknown> = {};
    for (const key of Object.keys(current) as (keyof FormValue)[]) {
      const value = current[key] === '' ? null : current[key];
      if (value !== original[key] && value !== null) diff[key] = value;
    }
    return diff as ReceiptUpdate;
  }
}

function toForm(r: Receipt | null): FormValue {
  const d = r?.data;
  return {
    vendor: d?.vendor ?? null,
    date: d?.date ?? null,
    total_amount: d?.total_amount ?? null,
    currency: d?.currency ?? null,
    tax_amount: d?.tax_amount ?? null,
    category: d?.category ?? null,
    payment_method: d?.payment_method ?? null,
    invoice_number: d?.invoice_number ?? null,
    location: d?.location ?? null,
    description: d?.description ?? null,
    business_purpose: d?.business_purpose ?? null,
    attendees: d?.attendees ?? null,
    justification: r?.justification ?? null,
  };
}
