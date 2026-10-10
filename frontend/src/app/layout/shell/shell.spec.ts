import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { computed, provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { injectFakeRealtime, provideFakeRealtime, seedSession } from '@testing/fakes';
import { makeManager, makePublicConfig, makeUser } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { PolicyStore } from '../../core/config/policy.store';
import { AppNotification, PublicConfig, User } from '../../core/models/models';
import { NotificationCenter } from '../../core/realtime/notification-center.service';
import { Shell } from './shell';

describe('Shell', () => {
  let fixture: ComponentFixture<Shell>;
  let navigate: MockInstance<Router['navigate']>;

  async function render(user: User = makeUser({ name: 'Asha Verma', department: 'Sales' }), config: PublicConfig | null = makePublicConfig()) {
    seedSession(user);
    const items = signal<AppNotification[]>([]);
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideFakeRealtime(),
        { provide: PolicyStore, useValue: { config: signal(config) } },
        {
          provide: NotificationCenter,
          useValue: { items, unread: computed(() => items().filter((n) => !n.read).length), markRead: vi.fn(), markAllRead: vi.fn() },
        },
      ],
    });
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture = TestBed.createComponent(Shell);
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => el().querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  const navLabels = () => Array.from(el().querySelectorAll('.nav-item .label')).map((l) => l.textContent);

  it('shows the employee navigation without approvals', async () => {
    await render();

    expect(navLabels()).toEqual(['Dashboard', 'New claim', 'My claims', 'Settings']);
    expect(Array.from(el().querySelectorAll('.nav-item')).map((a) => a.getAttribute('href'))).toEqual([
      '/dashboard',
      '/agent',
      '/claims',
      '/settings',
    ]);
  });

  it('adds approvals for managers', async () => {
    await render(makeManager());
    expect(navLabels()).toEqual(['Dashboard', 'New claim', 'My claims', 'Approvals', 'Settings']);
  });

  it('greets the user and shows their initials, role and department', async () => {
    await render(makeUser({ name: 'Asha Verma', department: 'Sales' }));

    expect(text('.greeting')).toContain('Hello, Asha Verma');
    expect(text('.user .avatar')).toBe('AV');
    expect(text('.who span')).toBe('Employee · Sales');
  });

  it('labels managers as such', async () => {
    await render(makeManager({ department: 'Finance' }));
    expect(text('.who span')).toBe('Manager · Finance');
  });

  it('uses at most two initials', async () => {
    await render(makeUser({ name: 'Mary Ann Jane Smith' }));
    expect(text('.user .avatar')).toBe('MA');
  });

  it('shows the company and the live connection status with the active engine', async () => {
    await render(makeUser(), makePublicConfig({ company: 'Acme Corp', llm_provider: 'claude' }));

    expect(text('.brand-text span')).toBe('Acme Corp');
    expect(text('.engine .label')).toBe('Connecting… · claude');

    injectFakeRealtime().connected.set(true);
    await fixture.whenStable();

    expect(text('.engine .label')).toBe('Live · claude');
    expect(el().querySelector('.engine-dot')!.classList).toContain('on');
  });

  it('falls back gracefully before the public config loads', async () => {
    await render(makeUser(), null);

    expect(text('.brand-text span')).toBe('Reimbursements');
    expect(text('.engine .label')).toBe('Connecting… · …');
  });

  it('starts a new claim from the primary button', async () => {
    await render();
    (el().querySelector('.new-claim') as HTMLButtonElement).click();
    expect(navigate).toHaveBeenCalledWith(['/agent']);
  });

  it('collapses and expands the sidebar', async () => {
    await render();
    const toggle = el().querySelector('.collapse') as HTMLButtonElement;
    expect(toggle.getAttribute('aria-label')).toBe('Collapse');

    toggle.click();
    await fixture.whenStable();

    expect(el().querySelector('.shell')!.classList).toContain('collapsed');
    expect(toggle.getAttribute('aria-label')).toBe('Expand');
  });

  it('signs the user out', async () => {
    await render();

    (Array.from(el().querySelectorAll('button')).find((b) => b.textContent!.includes('Sign out')) as HTMLButtonElement).click();

    expect(localStorage.getItem('era.session')).toBeNull();
    expect(navigate).toHaveBeenCalledWith(['/login']);
  });

  it('hosts the notification bell and the routed page', async () => {
    await render();

    expect(el().querySelector('app-notification-bell')).not.toBeNull();
    expect(el().querySelector('main router-outlet')).not.toBeNull();
  });
});
