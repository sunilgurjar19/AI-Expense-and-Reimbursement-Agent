import { Injectable, inject, signal } from '@angular/core';

import { AppConfigService } from '../config/app-config.service';

export interface Toast {
  id: number;
  level: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message?: string;
  link?: string | null;
  duration: number;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly config = inject(AppConfigService);
  private nextId = 1;

  readonly toasts = signal<Toast[]>([]);

  show(toast: Omit<Toast, 'id' | 'duration'> & { duration?: number }): void {
    const item: Toast = { duration: this.config.value.toastDurationMs, ...toast, id: this.nextId++ };
    this.toasts.update((list) => [...list.slice(-3), item]);
    setTimeout(() => this.dismiss(item.id), item.duration);
  }

  success(title: string, message?: string): void {
    this.show({ level: 'success', title, message });
  }

  error(title: string, message?: string): void {
    this.show({ level: 'error', title, message });
  }

  dismiss(id: number): void {
    this.toasts.update((list) => list.filter((t) => t.id !== id));
  }
}
