import { Injectable, effect, inject, signal } from '@angular/core';
import { Subject } from 'rxjs';

import { AuthService } from '../auth/auth.service';
import { AppConfigService } from '../config/app-config.service';
import { AppNotification, Claim } from '../models/models';

/** Server-sent events: live claim updates and notifications. */
@Injectable({ providedIn: 'root' })
export class RealtimeService {
  private readonly auth = inject(AuthService);
  private readonly config = inject(AppConfigService);

  private source: EventSource | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | undefined;

  readonly connected = signal(false);
  readonly claimUpdates = new Subject<Claim>();
  readonly notifications = new Subject<AppNotification>();

  constructor() {
    effect(() => (this.auth.token() ? this.connect() : this.disconnect()));
  }

  private connect(): void {
    this.disconnect();
    const url = this.config.api(`/events/stream?access_token=${this.auth.token()}`);
    const source = new EventSource(url);
    this.source = source;

    source.addEventListener('ready', () => this.connected.set(true));
    source.addEventListener('claim.updated', (e) =>
      this.claimUpdates.next(JSON.parse((e as MessageEvent).data) as Claim),
    );
    source.addEventListener('notification', (e) =>
      this.notifications.next(JSON.parse((e as MessageEvent).data) as AppNotification),
    );
    source.onerror = () => {
      this.connected.set(false);
      if (source.readyState === EventSource.CLOSED && this.auth.isAuthenticated()) {
        this.reconnectTimer = setTimeout(() => this.connect(), this.config.value.reconnectDelayMs);
      }
    };
  }

  private disconnect(): void {
    clearTimeout(this.reconnectTimer);
    this.source?.close();
    this.source = null;
    this.connected.set(false);
  }
}
