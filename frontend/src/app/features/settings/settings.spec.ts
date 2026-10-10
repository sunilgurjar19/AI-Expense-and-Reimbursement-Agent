import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { WritableSignal, provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { seedSession } from '@testing/fakes';
import { makeCategory, makeLlmSettings, makeProvider, makePublicConfig, makeUser } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { PolicyStore } from '../../core/config/policy.store';
import { LlmSettings, PublicConfig } from '../../core/models/models';
import { ToastService } from '../../core/ui/toast.service';
import { SettingsPage } from './settings';

const API = 'http://localhost:8100/api';

describe('SettingsPage', () => {
  let fixture: ComponentFixture<SettingsPage>;
  let http: HttpTestingController;
  let config: WritableSignal<PublicConfig | null>;
  let refreshPolicy: ReturnType<typeof vi.fn>;
  let toast: { success: MockInstance<ToastService['success']>; error: MockInstance<ToastService['error']>; show: MockInstance<ToastService['show']> };

  async function render(
    settings: LlmSettings | 'pending' = makeLlmSettings(),
    publicConfig: PublicConfig | null = makePublicConfig(),
    signedIn = true,
  ) {
    if (signedIn) seedSession(makeUser({ name: 'Asha Verma', email: 'asha@example.com', employee_code: 'EMP-001' }));
    config = signal(publicConfig);
    refreshPolicy = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: PolicyStore, useValue: { config, refresh: refreshPolicy } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    const toasts = TestBed.inject(ToastService);
    toast = {
      success: vi.spyOn(toasts, 'success').mockImplementation(() => {}),
      error: vi.spyOn(toasts, 'error').mockImplementation(() => {}),
      show: vi.spyOn(toasts, 'show').mockImplementation(() => {}),
    };
    fixture = TestBed.createComponent(SettingsPage);
    const req = http.expectOne(`${API}/settings/llm`);
    if (settings !== 'pending') req.flush(settings);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const card = (label: string) =>
    Array.from(el().querySelectorAll<HTMLElement>('.provider')).find((p) => p.querySelector('strong')!.textContent === label)!;
  const cardButton = (label: string, text: string) =>
    Array.from(card(label).querySelectorAll('button')).find((b) => b.textContent!.includes(text)) as HTMLButtonElement;

  describe('AI engine', () => {
    it('shows each provider with the active one tagged and its fallback chain', async () => {
      await render();

      expect(Array.from(el().querySelectorAll('.provider strong')).map((s) => s.textContent)).toEqual([
        'Ollama',
        'Claude',
        'Offline rules',
      ]);
      expect(card('Ollama').classList).toContain('active');
      expect(card('Ollama').querySelector('.active-tag')).not.toBeNull();
      expect(card('Claude').querySelector('.active-tag')).toBeNull();
      expect(el().querySelector('.block .muted strong')!.textContent).toBe('mock');
    });

    it('lists the models configured for a provider', async () => {
      await render();

      const models = Array.from(card('Ollama').querySelectorAll('dl div')).map(
        (d) => `${d.querySelector('dt')!.textContent}=${d.querySelector('dd')!.textContent}`,
      );
      expect(models).toEqual(['vision=gemma3:4b']);
    });

    it('only lets you switch to a configured engine that is not already active', async () => {
      await render();

      expect(cardButton('Ollama', 'Use this engine').disabled).toBe(true); // already active
      expect(cardButton('Claude', 'Use this engine').disabled).toBe(true); // not configured
      expect(cardButton('Offline rules', 'Use this engine').disabled).toBe(false);
    });

    it('renders an empty engine list until the settings arrive', async () => {
      await render('pending');

      expect(el().querySelectorAll('.provider')).toHaveLength(0);
      expect(el().querySelector('.block .muted strong')!.textContent).toBe('none');
    });

    it('says "none" when there is no fallback', async () => {
      await render(makeLlmSettings({ fallback_chain: [] }));
      expect(el().querySelector('.block .muted strong')!.textContent).toBe('none');
    });
  });

  describe('testing a connection', () => {
    it('shows a healthy result and confirms with a toast', async () => {
      await render();
      cardButton('Ollama', 'Test connection').click();
      await fixture.whenStable();

      const req = http.expectOne(`${API}/settings/llm/ollama/test`);
      expect(cardButton('Ollama', 'Test connection').disabled).toBe(true);
      req.flush(makeProvider({ healthy: true, detail: 'gemma3:4b ready' }));
      await fixture.whenStable();

      const health = card('Ollama').querySelector('.health')!;
      expect(health.textContent!.trim()).toBe('gemma3:4b ready');
      expect(health.classList).toContain('ok');
      expect(toast.success).toHaveBeenCalledWith('Ollama is reachable', 'gemma3:4b ready');
      expect(cardButton('Ollama', 'Test connection').disabled).toBe(false);
    });

    it('warns when the provider is not ready', async () => {
      await render();
      cardButton('Ollama', 'Test connection').click();

      http.expectOne(`${API}/settings/llm/ollama/test`).flush(makeProvider({ healthy: false, detail: 'Model not pulled' }));
      await fixture.whenStable();

      expect(card('Ollama').querySelector('.health')!.classList).toContain('bad');
      expect(toast.show).toHaveBeenCalledWith({ level: 'warning', title: 'Ollama not ready', message: 'Model not pulled' });
    });

    it('reports a failed test request', async () => {
      await render();
      cardButton('Ollama', 'Test connection').click();

      http.expectOne(`${API}/settings/llm/ollama/test`).flush({ detail: 'Timed out' }, { status: 504, statusText: 'Timeout' });
      await fixture.whenStable();

      expect(toast.error).toHaveBeenCalledWith('Test failed', 'Timed out');
      expect(cardButton('Ollama', 'Test connection').disabled).toBe(false);
    });
  });

  describe('switching engines', () => {
    it('activates the engine, refreshes the policy and warns about offline mode', async () => {
      await render();
      cardButton('Offline rules', 'Use this engine').click();

      const req = http.expectOne(`${API}/settings/llm`);
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ provider: 'mock' });
      req.flush(makeLlmSettings({ active: 'mock' }));
      await fixture.whenStable();

      expect(card('Offline rules').classList).toContain('active');
      expect(refreshPolicy).toHaveBeenCalled();
      expect(toast.show).toHaveBeenCalledWith(
        expect.objectContaining({ level: 'warning', title: 'Switched to Offline rules' }),
      );
    });

    it('confirms a switch to a real model with a success toast', async () => {
      await render(makeLlmSettings({ active: 'mock', providers: [makeProvider(), makeProvider({ name: 'mock', label: 'Offline rules' })] }));
      cardButton('Ollama', 'Use this engine').click();

      http.expectOne(`${API}/settings/llm`).flush(makeLlmSettings({ active: 'ollama' }));
      await fixture.whenStable();

      expect(toast.success).toHaveBeenCalledWith('Switched to Ollama', 'New receipts and chats will use this engine.');
    });

    it('reports a failed switch', async () => {
      await render();
      cardButton('Offline rules', 'Use this engine').click();

      http.expectOne(`${API}/settings/llm`).flush({ detail: 'Provider unavailable' }, { status: 400, statusText: 'Bad Request' });
      await fixture.whenStable();

      expect(toast.error).toHaveBeenCalledWith('Could not switch', 'Provider unavailable');
      expect(refreshPolicy).not.toHaveBeenCalled();
    });
  });

  describe('expense policy', () => {
    const rows = () =>
      Array.from(el().querySelectorAll('.policy tbody tr')).map((tr) =>
        Array.from(tr.querySelectorAll('td')).map((td) => td.textContent!.trim()),
      );

    it('summarises the policy and lists category limits', async () => {
      await render();

      expect(el().querySelector('.policy')!.closest('.block')!.querySelector('.muted')!.textContent).toContain(
        'Receipts older than 90 days need justification',
      );
      expect(rows()).toEqual([
        ['🚕 Travel', '₹5,000.00', '—'],
        ['🍽️ Meals', '₹2,000.00', '—'],
        ['🏨 Lodging', '₹8,000.00', 'business purpose'],
      ]);
    });

    it('hides the policy until it is loaded', async () => {
      await render(makeLlmSettings(), null);
      expect(el().querySelector('.policy')).toBeNull();
    });

    // Regression: every underscore is humanised, not just the first one of the joined list.
    it('humanises every required field name', async () => {
      await render(
        makeLlmSettings(),
        makePublicConfig({ categories: [makeCategory({ requires: ['business_purpose', 'invoice_number'] })] }),
      );
      expect(rows()[0][2]).toBe('business purpose, invoice number');
    });
  });

  it('omits the profile when nobody is signed in', async () => {
    await render(makeLlmSettings(), makePublicConfig(), false);
    expect(el().querySelector('.profile')).toBeNull();
  });

  it("shows the signed-in user's profile", async () => {
    await render();

    const profile = Object.fromEntries(
      Array.from(el().querySelectorAll('.profile dl div')).map((d) => [d.querySelector('dt')!.textContent, d.querySelector('dd')!.textContent]),
    );
    expect(profile).toEqual(
      expect.objectContaining({ Name: 'Asha Verma', Email: 'asha@example.com', 'Employee code': 'EMP-001', Role: 'employee' }),
    );
    expect(el().querySelector('.profile .avatar')!.textContent).toBe('A');
  });
});
