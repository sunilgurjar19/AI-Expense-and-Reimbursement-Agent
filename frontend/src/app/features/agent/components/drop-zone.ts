import { Component, HostListener, computed, inject, input, output, signal } from '@angular/core';

import { PolicyStore } from '../../../core/config/policy.store';

/** Drag & drop / browse / paste area for receipts. */
@Component({
  selector: 'app-drop-zone',
  template: `
    <label class="zone" [class.compact]="compact()" [class.over]="dragging()" [class.disabled]="disabled()"
           (dragover)="onDragOver($event)" (dragleave)="dragging.set(false)" (drop)="onDrop($event)">
      <input type="file" multiple [accept]="accept()" (change)="onPick($event)" [disabled]="disabled()" hidden />

      <div class="art" aria-hidden="true">
        <span class="sheet s1">🧾</span>
        <span class="sheet s2">📄</span>
        <span class="sheet s3">📸</span>
      </div>

      <div class="copy">
        <strong>{{ dragging() ? 'Release to upload ✨' : compact() ? 'Add more receipts' : 'Drop your receipts here' }}</strong>
        <span>
          Drag & drop, <u>browse</u> or paste (Ctrl/⌘ + V) · PDF, JPG, PNG · up to {{ maxMb() }} MB each
        </span>
      </div>

      @if (progress() !== null) {
        <div class="progress" animate.enter="enter-fade-up">
          <div class="bar" [style.width.%]="progress()"></div>
          <span>Uploading… {{ progress() }}%</span>
        </div>
      }
    </label>
  `,
  styles: `
    .zone {
      position: relative; overflow: hidden;
      display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px;
      min-height: 260px; padding: 32px; text-align: center; cursor: pointer;
      border: 2px dashed var(--brand-200); border-radius: var(--radius-lg);
      background:
        radial-gradient(circle at 20% 20%, rgb(139 92 246 / 8%), transparent 40%),
        radial-gradient(circle at 80% 80%, rgb(79 70 229 / 8%), transparent 40%),
        var(--surface);
      transition: all 0.35s var(--ease);
    }
    .zone:hover { border-color: var(--brand-400); box-shadow: var(--shadow); }
    .zone.over {
      border-color: var(--accent-500); border-style: solid; transform: scale(1.01);
      background: var(--gradient-soft); box-shadow: 0 0 0 6px rgb(139 92 246 / 12%);
    }
    .zone.disabled { opacity: 0.5; pointer-events: none; }
    .zone.compact { min-height: 0; flex-direction: row; justify-content: flex-start; padding: 14px 18px; gap: 14px; text-align: left; }

    .art { position: relative; width: 120px; height: 90px; transition: all 0.35s var(--ease); }
    .compact .art { width: 54px; height: 40px; }
    .sheet {
      position: absolute; display: grid; place-items: center;
      width: 56px; height: 68px; border-radius: 10px; font-size: 26px;
      background: #fff; box-shadow: var(--shadow); border: 1px solid var(--border);
      animation: float 3.2s ease-in-out infinite; transition: all 0.35s var(--ease);
    }
    .s1 { left: 0; top: 14px; transform: rotate(-12deg); }
    .s2 { left: 32px; top: 0; z-index: 1; animation-delay: -1s; }
    .s3 { left: 64px; top: 14px; transform: rotate(12deg); animation-delay: -2s; }
    .over .s1 { left: -10px; } .over .s3 { left: 74px; }
    .compact .sheet { width: 28px; height: 34px; font-size: 14px; border-radius: 6px; }
    .compact .s1 { left: 0; top: 6px; } .compact .s2 { left: 13px; top: 0; } .compact .s3 { left: 26px; top: 6px; }

    .copy { display: flex; flex-direction: column; gap: 4px; }
    .copy strong { font-size: 17px; }
    .compact .copy strong { font-size: 14px; }
    .copy span { font-size: 13px; color: var(--text-2); }
    .copy u { color: var(--brand-600); text-decoration: none; font-weight: 600; }

    .progress { position: absolute; left: 0; right: 0; bottom: 0; height: 26px; background: var(--brand-50); }
    .progress .bar { height: 100%; background: var(--gradient); transition: width 0.2s; }
    .progress span { position: absolute; inset: 0; display: grid; place-items: center; font-size: 12px; font-weight: 700; color: var(--brand-700); mix-blend-mode: multiply; }
  `,
})
export class DropZone {
  readonly compact = input(false);
  readonly progress = input<number | null>(null);
  readonly disabled = input(false);
  readonly files = output<File[]>();

  private readonly policy = inject(PolicyStore);
  protected readonly dragging = signal(false);
  protected readonly accept = computed(() =>
    (this.policy.config()?.allowed_extensions ?? ['.pdf', '.png', '.jpg']).join(','),
  );
  protected readonly maxMb = computed(() => this.policy.config()?.max_upload_mb ?? 15);

  protected onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(true);
  }

  protected onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragging.set(false);
    this.emit(Array.from(event.dataTransfer?.files ?? []));
  }

  protected onPick(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.emit(Array.from(input.files ?? []));
    input.value = '';
  }

  @HostListener('document:paste', ['$event'])
  protected onPaste(event: ClipboardEvent): void {
    const target = event.target as HTMLElement | null;
    if (target?.closest('input, textarea')) return; // let text inputs paste normally
    const files = Array.from(event.clipboardData?.files ?? []);
    if (files.length) this.emit(files);
  }

  private emit(files: File[]): void {
    if (!this.disabled() && files.length) this.files.emit(files);
  }
}
