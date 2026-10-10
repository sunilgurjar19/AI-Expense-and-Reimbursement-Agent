import { HttpBackend, HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

/** Runtime configuration loaded from /config/app-config.json (editable without a rebuild). */
export interface AppConfig {
  apiBaseUrl: string;
  appName: string;
  toastDurationMs: number;
  reconnectDelayMs: number;
  quickPrompts: string[];
}

const DEFAULTS: AppConfig = {
  apiBaseUrl: 'http://localhost:8100/api',
  appName: 'Expense & Reimbursement Agent',
  toastDurationMs: 5000,
  reconnectDelayMs: 4000,
  quickPrompts: ["What's my total?", 'Is this ready to submit?'],
};

@Injectable({ providedIn: 'root' })
export class AppConfigService {
  // HttpBackend bypasses interceptors, which depend on this config.
  private readonly http = new HttpClient(inject(HttpBackend));
  private config: AppConfig = DEFAULTS;

  async load(): Promise<void> {
    try {
      const loaded = await firstValueFrom(this.http.get<Partial<AppConfig>>('config/app-config.json'));
      this.config = { ...DEFAULTS, ...loaded };
    } catch {
      console.warn('app-config.json not found - using defaults');
    }
  }

  get value(): AppConfig {
    return this.config;
  }

  api(path: string): string {
    return `${this.config.apiBaseUrl}${path}`;
  }
}
