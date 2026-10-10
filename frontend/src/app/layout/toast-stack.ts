import { Component, inject } from '@angular/core';
import { Router } from '@angular/router';

import { Toast, ToastService } from '../core/ui/toast.service';

const ICONS: Record<Toast['level'], string> = { info: 'ℹ️', success: '✅', warning: '⚠️', error: '⛔' };

@Component({
  selector: 'app-toast-stack',
  template: `
    <div class="stack" aria-live="polite">
      @for (toast of toasts.toasts(); track toast.id) {
        <div class="toast" [class]="'toast ' + toast.level" animate.enter="enter-slide" animate.leave="leave-slide"
             [class.clickable]="!!toast.link" (click)="open(toast)">
          <span class="icon">{{ icons[toast.level] }}</span>
          <div class="body">
            <strong>{{ toast.title }}</strong>
            @if (toast.message) {
              <p>{{ toast.message }}</p>
            }
          </div>
          <button class="close" aria-label="Dismiss" (click)="$event.stopPropagation(); toasts.dismiss(toast.id)">×</button>
          <span class="timer" [style.animation-duration.ms]="toast.duration"></span>
        </div>
      }
    </div>
  `,
  styles: `
    .stack {
      position: fixed; right: 20px; bottom: 20px; z-index: 900;
      display: flex; flex-direction: column; gap: 10px; width: min(380px, calc(100vw - 40px));
    }
    .toast {
      position: relative; overflow: hidden;
      display: flex; gap: 12px; align-items: flex-start;
      padding: 14px 14px 16px; border-radius: 14px;
      background: rgb(255 255 255 / 92%); backdrop-filter: blur(12px);
      border: 1px solid var(--border); box-shadow: var(--shadow-lg);
    }
    .toast.clickable { cursor: pointer; }
    .icon { font-size: 18px; line-height: 1.3; }
    .body { flex: 1; min-width: 0; }
    strong { font-size: 14px; }
    p { margin: 2px 0 0; color: var(--text-2); font-size: 13px; }
    .close {
      border: none; background: none; font-size: 20px; line-height: 1;
      color: var(--text-3); cursor: pointer; padding: 0 2px;
    }
    .close:hover { color: var(--text); }
    .timer {
      position: absolute; left: 0; bottom: 0; height: 3px; width: 100%;
      transform-origin: left; animation: shrink linear forwards;
    }
    .success .timer { background: var(--success); }
    .info .timer { background: var(--brand-500); }
    .warning .timer { background: #f59e0b; }
    .error .timer { background: var(--danger); }
    .success { border-left: 4px solid var(--success); }
    .info { border-left: 4px solid var(--brand-500); }
    .warning { border-left: 4px solid #f59e0b; }
    .error { border-left: 4px solid var(--danger); }
    @keyframes shrink { from { transform: scaleX(1); } to { transform: scaleX(0); } }
  `,
})
export class ToastStack {
  protected readonly toasts = inject(ToastService);
  private readonly router = inject(Router);
  protected readonly icons = ICONS;

  protected open(toast: Toast): void {
    if (toast.link) {
      this.router.navigateByUrl(toast.link);
      this.toasts.dismiss(toast.id);
    }
  }
}
