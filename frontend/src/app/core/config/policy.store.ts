import { Injectable, computed, effect, inject, signal } from '@angular/core';

import { PlatformApi } from '../api/platform.api';
import { AuthService } from '../auth/auth.service';
import { CategoryRule, PublicConfig } from '../models/models';

/** Caches the backend's public config (categories, currency, policy). */
@Injectable({ providedIn: 'root' })
export class PolicyStore {
  private readonly api = inject(PlatformApi);

  readonly config = signal<PublicConfig | null>(null);
  readonly currency = computed(() => this.config()?.currency ?? 'INR');
  readonly agentName = computed(() => this.config()?.agent_name ?? 'Agent');
  readonly categories = computed(() => this.config()?.categories ?? []);
  private readonly byKey = computed(
    () => new Map<string, CategoryRule>(this.categories().map((c) => [c.key, c])),
  );

  constructor() {
    const auth = inject(AuthService);
    effect(() => {
      if (auth.isAuthenticated()) this.refresh();
    });
  }

  refresh(): void {
    this.api.publicConfig().subscribe((config) => this.config.set(config));
  }

  category(key: string | null | undefined): CategoryRule | undefined {
    return key ? this.byKey().get(key) : undefined;
  }
}
