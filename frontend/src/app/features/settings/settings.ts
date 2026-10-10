import { Component, inject, signal } from '@angular/core';

import { PlatformApi } from '../../core/api/platform.api';
import { errorMessage } from '../../core/auth/auth.interceptor';
import { AuthService } from '../../core/auth/auth.service';
import { PolicyStore } from '../../core/config/policy.store';
import { LlmSettings, ProviderStatus } from '../../core/models/models';
import { ToastService } from '../../core/ui/toast.service';
import { MoneyPipe } from '../../shared/pipes/money.pipe';

const PROVIDER_ART: Record<ProviderStatus['name'], { icon: string; blurb: string }> = {
  ollama: { icon: '🦙', blurb: 'Runs locally on your machine. Private, free, needs a vision model (e.g. gemma3).' },
  claude: { icon: '✳️', blurb: "Anthropic's Claude - best accuracy on messy photos and multi-page PDFs." },
  mock: { icon: '🧮', blurb: 'Offline rules engine. Reads PDF text layers only - great for demos without a model.' },
};

@Component({
  selector: 'app-settings',
  imports: [MoneyPipe],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Settings</h1>
          <p>AI engine, expense policy and your profile. Defaults live in <code>backend/config/*.yaml</code>.</p>
        </div>
      </div>

      <section class="block">
        <h3>AI engine</h3>
        <p class="muted">Choose which model reads receipts and powers the chat. If it fails, the agent falls back to:
          <strong>{{ settings()?.fallback_chain?.join(' → ') || 'none' }}</strong>.</p>

        <div class="providers stagger">
          @for (p of settings()?.providers ?? []; track p.name) {
            <div class="provider card" [class.active]="settings()?.active === p.name">
              <div class="p-head">
                <span class="p-icon">{{ art[p.name].icon }}</span>
                <div>
                  <strong>{{ p.label }}</strong>
                  <span class="health" [class.ok]="health()[p.name]?.healthy === true" [class.bad]="health()[p.name]?.healthy === false">
                    {{ health()[p.name]?.detail ?? p.detail }}
                  </span>
                </div>
                @if (settings()?.active === p.name) { <span class="active-tag">Active</span> }
              </div>
              <p class="blurb">{{ art[p.name].blurb }}</p>
              <dl>
                @for (m of modelEntries(p); track m[0]) {
                  <div><dt>{{ m[0] }}</dt><dd>{{ m[1] }}</dd></div>
                }
              </dl>
              <div class="p-actions">
                <button class="btn btn-ghost btn-sm" [disabled]="testing() === p.name" (click)="test(p)">
                  @if (testing() === p.name) { <span class="spinner"></span> } Test connection
                </button>
                <button class="btn btn-primary btn-sm" [disabled]="settings()?.active === p.name || !p.configured" (click)="activate(p)">
                  Use this engine
                </button>
              </div>
            </div>
          }
        </div>
      </section>

      @if (policy.config(); as cfg) {
        <section class="block">
          <h3>Expense policy</h3>
          <p class="muted">
            Receipts older than {{ cfg.policy.max_receipt_age_days }} days need justification ·
            base currency {{ cfg.currency }} · non-reimbursable: {{ cfg.policy.blocked_keywords.slice(0, 5).join(', ') }}…
          </p>
          <div class="card policy">
            <table>
              <thead><tr><th>Category</th><th class="num">Limit per item</th><th>Also requires</th></tr></thead>
              <tbody>
                @for (c of cfg.categories; track c.key) {
                  <tr>
                    <td>{{ c.icon }} {{ c.label }}</td>
                    <td class="num">{{ c.limit_per_item | money: cfg.currency }}</td>
                    <td>{{ c.requires.length ? c.requires.join(', ').replaceAll('_', ' ') : '—' }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      }

      @if (auth.user(); as u) {
        <section class="block">
          <h3>Profile</h3>
          <div class="card profile">
            <div class="avatar">{{ u.name[0] }}</div>
            <dl>
              <div><dt>Name</dt><dd>{{ u.name }}</dd></div>
              <div><dt>Email</dt><dd>{{ u.email }}</dd></div>
              <div><dt>Employee code</dt><dd>{{ u.employee_code }}</dd></div>
              <div><dt>Department</dt><dd>{{ u.department }}</dd></div>
              <div><dt>Cost center</dt><dd>{{ u.cost_center }}</dd></div>
              <div><dt>Role</dt><dd>{{ u.role }}</dd></div>
            </dl>
          </div>
        </section>
      }
    </div>
  `,
  styles: `
    code { padding: 1px 6px; border-radius: 6px; background: var(--brand-50); color: var(--brand-700); font-size: 12px; }
    .block { margin-bottom: 30px; }
    .block h3 { font-size: 17px; font-weight: 700; }
    .block > .muted { margin: 4px 0 14px; }
    .providers { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
    .provider { display: flex; flex-direction: column; gap: 12px; padding: 20px; transition: all 0.3s var(--ease); }
    .provider.active { border-color: var(--brand-500); box-shadow: 0 0 0 4px rgb(99 102 241 / 12%), var(--shadow); }
    .p-head { display: flex; gap: 12px; align-items: flex-start; }
    .p-head > div { flex: 1; display: flex; flex-direction: column; }
    .p-icon { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 12px; background: var(--brand-50); font-size: 22px; }
    .health { font-size: 12px; color: var(--text-3); }
    .health.ok { color: var(--success); } .health.bad { color: var(--danger); }
    .active-tag { padding: 3px 10px; border-radius: 999px; background: var(--gradient); color: #fff; font-size: 11px; font-weight: 700; animation: pop-in 0.4s var(--spring); }
    .blurb { margin: 0; font-size: 13px; color: var(--text-2); }
    dl { margin: 0; display: grid; gap: 6px; }
    dl div { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
    dt { color: var(--text-3); text-transform: capitalize; }
    dd { margin: 0; font-weight: 600; font-family: ui-monospace, monospace; font-size: 12px; }
    .p-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: auto; }
    .policy { overflow: hidden; }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 10px 16px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
    th { font-size: 12px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }
    tr:last-child td { border-bottom: none; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .profile { display: flex; gap: 20px; padding: 20px; align-items: flex-start; }
    .profile dl { flex: 1; grid-template-columns: repeat(2, 1fr); gap: 12px 32px; }
    .profile dd { font-family: inherit; font-size: 13px; }
    .avatar { display: grid; place-items: center; width: 64px; height: 64px; border-radius: 50%; background: var(--gradient); color: #fff; font-size: 26px; font-weight: 800; }
  `,
})
export class SettingsPage {
  private readonly api = inject(PlatformApi);
  private readonly toast = inject(ToastService);
  protected readonly policy = inject(PolicyStore);
  protected readonly auth = inject(AuthService);

  protected readonly art = PROVIDER_ART;
  protected readonly settings = signal<LlmSettings | null>(null);
  protected readonly health = signal<Partial<Record<ProviderStatus['name'], ProviderStatus>>>({});
  protected readonly testing = signal<string | null>(null);

  constructor() {
    this.api.llmSettings().subscribe((s) => this.settings.set(s));
  }

  protected modelEntries(p: ProviderStatus): [string, string][] {
    return Object.entries(p.models);
  }

  protected test(p: ProviderStatus): void {
    this.testing.set(p.name);
    this.api.testProvider(p.name).subscribe({
      next: (status) => {
        this.testing.set(null);
        this.health.update((h) => ({ ...h, [p.name]: status }));
        if (status.healthy) {
          this.toast.success(`${p.label} is reachable`, status.detail);
        } else {
          this.toast.show({ level: 'warning', title: `${p.label} not ready`, message: status.detail });
        }
      },
      error: (err) => {
        this.testing.set(null);
        this.toast.error('Test failed', errorMessage(err));
      },
    });
  }

  protected activate(p: ProviderStatus): void {
    this.api.setProvider(p.name).subscribe({
      next: (s) => {
        this.settings.set(s);
        this.policy.refresh();
        if (p.name === 'mock') {
          this.toast.show({
            level: 'warning',
            title: `Switched to ${p.label}`,
            message: 'Photos and scanned receipts cannot be read in this mode - only PDFs with a text layer.',
          });
        } else {
          this.toast.success(`Switched to ${p.label}`, 'New receipts and chats will use this engine.');
        }
      },
      error: (err) => this.toast.error('Could not switch', errorMessage(err)),
    });
  }
}
