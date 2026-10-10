import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { debounceTime } from 'rxjs';

import { PlatformApi } from '../../core/api/platform.api';
import { AuthService } from '../../core/auth/auth.service';
import { claimLink } from '../../core/models/display';
import { DashboardSummary } from '../../core/models/models';
import { RealtimeService } from '../../core/realtime/realtime.service';
import { CountUp } from '../../shared/components/count-up';
import { StatusPill } from '../../shared/components/status-pill';
import { MoneyPipe } from '../../shared/pipes/money.pipe';
import { RelativeTimePipe } from '../../shared/pipes/relative-time.pipe';

@Component({
  selector: 'app-dashboard',
  imports: [RouterLink, CountUp, StatusPill, MoneyPipe, RelativeTimePipe],
  templateUrl: './dashboard.html',
  styleUrl: './dashboard.scss',
})
export class DashboardPage {
  private readonly api = inject(PlatformApi);
  protected readonly auth = inject(AuthService);

  protected readonly claimLink = claimLink;
  protected readonly data = signal<DashboardSummary | null>(null);
  protected readonly hovered = signal<string | null>(null);

  protected readonly firstName = computed(() => this.auth.user()?.name.split(' ')[0] ?? '');
  protected readonly categoryMax = computed(() => Math.max(1, ...(this.data()?.by_category ?? []).map((c) => c.total)));
  protected readonly categoryTotal = computed(() =>
    (this.data()?.by_category ?? []).reduce((sum, c) => sum + c.total, 0),
  );

  constructor() {
    this.load();
    // Refresh the numbers when anything changes in the background.
    inject(RealtimeService)
      .claimUpdates.pipe(debounceTime(800), takeUntilDestroyed(inject(DestroyRef)))
      .subscribe(() => this.load());
  }

  protected share(total: number): number {
    return Math.round((100 * total) / Math.max(1, this.categoryTotal()));
  }

  private load(): void {
    this.api.dashboard().subscribe((data) => this.data.set(data));
  }
}
