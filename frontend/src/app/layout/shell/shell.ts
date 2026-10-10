import { Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../../core/auth/auth.service';
import { PolicyStore } from '../../core/config/policy.store';
import { NotificationCenter } from '../../core/realtime/notification-center.service';
import { RealtimeService } from '../../core/realtime/realtime.service';
import { NotificationBell } from './notification-bell';

interface NavItem {
  path: string;
  label: string;
  icon: string;
  managerOnly?: boolean;
}

const NAV: NavItem[] = [
  { path: '/dashboard', label: 'Dashboard', icon: '🏠' },
  { path: '/agent', label: 'New claim', icon: '✨' },
  { path: '/claims', label: 'My claims', icon: '🧾' },
  { path: '/approvals', label: 'Approvals', icon: '✅', managerOnly: true },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
];

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, NotificationBell],
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
})
export class Shell {
  protected readonly auth = inject(AuthService);
  protected readonly realtime = inject(RealtimeService);
  protected readonly policy = inject(PolicyStore);
  protected readonly notifications = inject(NotificationCenter);
  private readonly router = inject(Router);

  protected readonly collapsed = signal(false);
  protected readonly nav = computed(() => NAV.filter((item) => !item.managerOnly || this.auth.isManager()));
  protected readonly initials = computed(() =>
    (this.auth.user()?.name ?? '?')
      .split(' ')
      .map((part) => part[0])
      .slice(0, 2)
      .join(''),
  );

  protected newClaim(): void {
    this.router.navigate(['/agent']);
  }
}
