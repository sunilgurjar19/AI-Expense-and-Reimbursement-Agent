import { Component, ElementRef, HostListener, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { AppNotification } from '../../core/models/models';
import { NotificationCenter } from '../../core/realtime/notification-center.service';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';

const LEVEL_ICON: Record<AppNotification['level'], string> = {
  info: '🔔',
  success: '🎉',
  warning: '⚠️',
  error: '⛔',
};

@Component({
  selector: 'app-notification-bell',
  imports: [RelativeTimePipe],
  template: `
    <button class="bell" [class.ring]="center.unread() > 0" (click)="open.set(!open())" aria-label="Notifications">
      🔔
      @if (center.unread() > 0) {
        <span class="badge" animate.enter="enter-pop">{{ center.unread() > 9 ? '9+' : center.unread() }}</span>
      }
    </button>

    @if (open()) {
      <div class="panel" animate.enter="enter-fade-up" animate.leave="leave-fade">
        <header>
          <strong>Notifications</strong>
          @if (center.unread() > 0) {
            <button class="link" (click)="center.markAllRead()">Mark all read</button>
          }
        </header>
        <div class="list">
          @for (n of center.items(); track n.id) {
            <button class="item" [class.unread]="!n.read" (click)="select(n)">
              <span class="icon" [class]="'icon ' + n.level">{{ icons[n.level] }}</span>
              <span class="text">
                <strong>{{ n.title }}</strong>
                <span>{{ n.message }}</span>
                <small>{{ n.created_at | relativeTime }}</small>
              </span>
            </button>
          } @empty {
            <div class="empty">You're all caught up ✨</div>
          }
        </div>
      </div>
    }
  `,
  styles: `
    :host { position: relative; }
    .bell {
      position: relative; width: 40px; height: 40px; border-radius: 12px;
      border: 1px solid var(--border); background: var(--surface); cursor: pointer; font-size: 17px;
      transition: transform 0.2s, box-shadow 0.2s;
    }
    .bell:hover { box-shadow: var(--shadow); transform: translateY(-1px); }
    .bell.ring { animation: bell 2.5s ease-in-out infinite; }
    @keyframes bell {
      0%, 85%, 100% { transform: rotate(0); }
      88% { transform: rotate(14deg); } 92% { transform: rotate(-12deg); } 96% { transform: rotate(6deg); }
    }
    .badge {
      position: absolute; top: -6px; right: -6px; min-width: 20px; height: 20px; padding: 0 5px;
      border-radius: 10px; background: #ef4444; color: #fff; font-size: 11px; font-weight: 700;
      display: grid; place-items: center; border: 2px solid var(--bg);
    }
    .panel {
      position: absolute; right: 0; top: 50px; width: 380px; max-height: 480px;
      display: flex; flex-direction: column;
      background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
      box-shadow: var(--shadow-lg); overflow: hidden; z-index: 100;
    }
    header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--border); }
    .link { border: none; background: none; color: var(--brand-600); font-weight: 600; cursor: pointer; font-size: 13px; }
    .list { overflow-y: auto; }
    .item {
      width: 100%; display: flex; gap: 12px; padding: 12px 16px; text-align: left;
      border: none; border-bottom: 1px solid var(--border); background: none; cursor: pointer;
      transition: background 0.15s;
    }
    .item:hover { background: var(--surface-2); }
    .item.unread { background: #f8f7ff; }
    .item.unread strong::after {
      content: ''; display: inline-block; width: 7px; height: 7px; margin-left: 6px;
      border-radius: 50%; background: var(--brand-500); vertical-align: middle;
    }
    .icon { flex-shrink: 0; width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; background: var(--brand-50); }
    .icon.success { background: var(--success-bg); }
    .icon.warning { background: var(--warning-bg); }
    .icon.error { background: var(--danger-bg); }
    .text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .text strong { font-size: 13px; }
    .text span { font-size: 13px; color: var(--text-2); }
    .text small { font-size: 11px; color: var(--text-3); }
    .empty { padding: 32px; text-align: center; color: var(--text-2); }
  `,
})
export class NotificationBell {
  protected readonly center = inject(NotificationCenter);
  private readonly router = inject(Router);
  private readonly host = inject(ElementRef<HTMLElement>);

  protected readonly open = signal(false);
  protected readonly icons = LEVEL_ICON;

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (!this.host.nativeElement.contains(event.target as Node)) this.open.set(false);
  }

  protected select(notification: AppNotification): void {
    this.center.markRead(notification);
    this.open.set(false);
    if (notification.link) this.router.navigateByUrl(notification.link);
  }
}
