import { Component, HostListener, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';

import { Attachment } from '../../core/models/models';


/** Full-screen viewer for receipt images and PDFs, with previous/next and download. */
@Component({
  selector: 'app-attachment-viewer',
  template: `
    @let item = current();
    <div class="overlay" animate.enter="viewer-in" animate.leave="viewer-out" (click)="closed.emit()">
      <div class="viewer" (click)="$event.stopPropagation()" role="dialog" aria-modal="true" [attr.aria-label]="item.name">
        <header>
          <div class="title">
            <strong>{{ item.name }}</strong>
            <span>{{ item.subtitle }} · {{ size(item.sizeBytes) }} · {{ index() + 1 }} of {{ attachments().length }}</span>
          </div>
          <a class="btn btn-ghost btn-sm" [href]="item.viewUrl" target="_blank" rel="noopener">Open in new tab ↗</a>
          <a class="btn btn-primary btn-sm" [href]="item.downloadUrl" download>⬇ Download</a>
          <button class="btn btn-ghost btn-icon" (click)="closed.emit()" aria-label="Close">✕</button>
        </header>

        <div class="stage">
          @if (attachments().length > 1) {
            <button class="nav prev" (click)="step(-1)" aria-label="Previous document">‹</button>
          }
          @if (isImage()) {
            <img [src]="item.viewUrl" [alt]="item.name" />
          } @else {
            <iframe [src]="safeUrl()" [title]="item.name"></iframe>
          }
          @if (attachments().length > 1) {
            <button class="nav next" (click)="step(1)" aria-label="Next document">›</button>
          }
        </div>
      </div>
    </div>
  `,
  styles: `
    .overlay {
      position: fixed; inset: 0; z-index: 400; display: grid; place-items: center; padding: 24px;
      background: rgb(15 23 42 / 70%); backdrop-filter: blur(6px);
    }
    .viewer-in { animation: viewer 0.3s var(--ease) both; }
    .viewer-out { animation: viewer 0.2s ease-in reverse both; }
    @keyframes viewer { from { opacity: 0; transform: scale(0.97); } to { opacity: 1; transform: none; } }
    .viewer {
      width: min(1100px, 100%); height: min(860px, 100%); display: flex; flex-direction: column;
      border-radius: 18px; overflow: hidden; background: var(--surface); box-shadow: var(--shadow-lg);
    }
    header { display: flex; align-items: center; gap: 10px; padding: 14px 18px; border-bottom: 1px solid var(--border); }
    .title { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .title strong { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .title span { font-size: 12px; color: var(--text-3); }
    .stage { position: relative; flex: 1; min-height: 0; display: grid; place-items: center; background: #f1f5f9; }
    img { max-width: 100%; max-height: 100%; object-fit: contain; animation: fade-up 0.3s var(--ease); }
    iframe { width: 100%; height: 100%; border: none; background: #fff; }
    .nav {
      position: absolute; top: 50%; z-index: 1; width: 44px; height: 44px; margin-top: -22px;
      border: none; border-radius: 50%; background: rgb(15 23 42 / 65%); color: #fff;
      font-size: 26px; line-height: 1; cursor: pointer; transition: background 0.2s, transform 0.2s var(--ease);
    }
    .nav:hover { background: rgb(15 23 42 / 85%); transform: scale(1.08); }
    .prev { left: 14px; } .next { right: 14px; }
  `,
})
export class AttachmentViewer {
  readonly attachments = input.required<Attachment[]>();
  readonly startIndex = input(0);
  readonly closed = output<void>();

  private readonly sanitizer = inject(DomSanitizer);
  protected readonly index = signal(0);

  protected readonly current = computed(() => this.attachments()[this.index()] ?? this.attachments()[0]);
  protected readonly isImage = computed(() => this.current().mimeType.startsWith('image/'));
  protected readonly safeUrl = computed<SafeResourceUrl>(() =>
    this.sanitizer.bypassSecurityTrustResourceUrl(this.current().viewUrl),
  );

  constructor() {
    effect(() => {
      const start = this.startIndex();
      untracked(() => this.index.set(start));
    });
  }

  @HostListener('document:keydown', ['$event'])
  protected onKey(event: KeyboardEvent): void {
    if (event.key === 'Escape') this.closed.emit();
    else if (event.key === 'ArrowRight') this.step(1);
    else if (event.key === 'ArrowLeft') this.step(-1);
  }

  protected step(delta: number): void {
    const count = this.attachments().length;
    this.index.update((i) => (i + delta + count) % count);
  }

  protected size(bytes: number): string {
    return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
}
