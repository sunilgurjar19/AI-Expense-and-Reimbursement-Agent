import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { AppConfigService } from '../config/app-config.service';
import {
  AppNotification,
  Claim,
  ClaimSummary,
  DashboardSummary,
  LlmSettings,
  ProviderStatus,
  PublicConfig,
} from '../models/models';

/** Dashboard, approvals, notifications, settings and public config endpoints. */
@Injectable({ providedIn: 'root' })
export class PlatformApi {
  private readonly http = inject(HttpClient);
  private readonly config = inject(AppConfigService);

  publicConfig(): Observable<PublicConfig> {
    return this.http.get<PublicConfig>(this.config.api('/config'));
  }

  dashboard(): Observable<DashboardSummary> {
    return this.http.get<DashboardSummary>(this.config.api('/dashboard'));
  }

  // ---------------------------------------------------------- approvals
  approvals(): Observable<ClaimSummary[]> {
    return this.http.get<ClaimSummary[]>(this.config.api('/approvals'));
  }

  approval(id: string): Observable<Claim> {
    return this.http.get<Claim>(this.config.api(`/approvals/${id}`));
  }

  decide(id: string, decision: 'approve' | 'reject', comment: string): Observable<Claim> {
    return this.http.post<Claim>(this.config.api(`/approvals/${id}`), { decision, comment });
  }

  // ------------------------------------------------------ notifications
  notifications(): Observable<AppNotification[]> {
    return this.http.get<AppNotification[]>(this.config.api('/notifications'));
  }

  markRead(id: string): Observable<void> {
    return this.http.post<void>(this.config.api(`/notifications/${id}/read`), {});
  }

  markAllRead(): Observable<void> {
    return this.http.post<void>(this.config.api('/notifications/read-all'), {});
  }

  // ----------------------------------------------------------- settings
  llmSettings(): Observable<LlmSettings> {
    return this.http.get<LlmSettings>(this.config.api('/settings/llm'));
  }

  setProvider(provider: ProviderStatus['name']): Observable<LlmSettings> {
    return this.http.put<LlmSettings>(this.config.api('/settings/llm'), { provider });
  }

  testProvider(provider: ProviderStatus['name']): Observable<ProviderStatus> {
    return this.http.post<ProviderStatus>(this.config.api(`/settings/llm/${provider}/test`), {});
  }
}
