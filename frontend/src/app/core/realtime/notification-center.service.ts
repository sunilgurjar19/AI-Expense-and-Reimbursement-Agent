import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { PlatformApi } from '../api/platform.api';
import { AuthService } from '../auth/auth.service';
import { AppNotification } from '../models/models';
import { ToastService } from '../ui/toast.service';
import { RealtimeService } from './realtime.service';

@Injectable({ providedIn: 'root' })
export class NotificationCenter {
  private readonly api = inject(PlatformApi);
  private readonly toast = inject(ToastService);

  readonly items = signal<AppNotification[]>([]);
  readonly unread = computed(() => this.items().filter((n) => !n.read).length);

  constructor() {
    const auth = inject(AuthService);
    effect(() => (auth.isAuthenticated() ? this.refresh() : this.items.set([])));

    inject(RealtimeService)
      .notifications.pipe(takeUntilDestroyed())
      .subscribe((notification) => {
        this.items.update((list) => [notification, ...list]);
        this.toast.show({
          level: notification.level,
          title: notification.title,
          message: notification.message,
          link: notification.link,
        });
      });
  }

  refresh(): void {
    this.api.notifications().subscribe((list) => this.items.set(list));
  }

  markRead(notification: AppNotification): void {
    if (notification.read) return;
    this.items.update((list) => list.map((n) => (n.id === notification.id ? { ...n, read: true } : n)));
    this.api.markRead(notification.id).subscribe();
  }

  markAllRead(): void {
    this.items.update((list) => list.map((n) => ({ ...n, read: true })));
    this.api.markAllRead().subscribe();
  }
}
