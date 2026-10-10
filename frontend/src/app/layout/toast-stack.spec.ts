import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import type { MockInstance } from 'vitest';

import { AppConfigService } from '../core/config/app-config.service';
import { ToastService } from '../core/ui/toast.service';
import { ToastStack } from './toast-stack';

describe('ToastStack', () => {
  let fixture: ComponentFixture<ToastStack>;
  let toasts: ToastService;
  let navigateByUrl: MockInstance<Router['navigateByUrl']>;

  beforeEach(async () => {
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideRouter([]),
        { provide: AppConfigService, useValue: { value: { toastDurationMs: 60_000 } } },
      ],
    });
    toasts = TestBed.inject(ToastService);
    navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture = TestBed.createComponent(ToastStack);
    await fixture.whenStable();
  });

  const el = () => fixture.nativeElement as HTMLElement;
  const rendered = () => Array.from(el().querySelectorAll<HTMLElement>('.toast'));

  async function show(...items: Parameters<ToastService['show']>[0][]) {
    items.forEach((item) => toasts.show(item));
    await fixture.whenStable();
  }

  it('is an accessible live region', () => {
    expect(el().querySelector('.stack')!.getAttribute('aria-live')).toBe('polite');
  });

  it('renders each toast with a level icon, title and optional message', async () => {
    await show(
      { level: 'success', title: 'Saved', message: 'Draft stored' },
      { level: 'error', title: 'Upload failed' },
    );

    const [success, error] = rendered();
    expect(success.classList).toContain('success');
    expect(success.querySelector('.icon')!.textContent).toBe('✅');
    expect(success.querySelector('strong')!.textContent).toBe('Saved');
    expect(success.querySelector('p')!.textContent).toBe('Draft stored');
    expect(error.querySelector('.icon')!.textContent).toBe('⛔');
    expect(error.querySelector('p')).toBeNull();
  });

  it('shows a countdown bar matching the toast duration', async () => {
    await show({ level: 'info', title: 'Heads up', duration: 7000 });
    expect((rendered()[0].querySelector('.timer') as HTMLElement).style.animationDuration).toBe('7000ms');
  });

  it('dismisses a toast from its close button', async () => {
    await show({ level: 'info', title: 'One' }, { level: 'info', title: 'Two' });

    (rendered()[0].querySelector('.close') as HTMLButtonElement).click();
    await fixture.whenStable();

    expect(rendered().map((t) => t.querySelector('strong')!.textContent)).toEqual(['Two']);
    expect(navigateByUrl).not.toHaveBeenCalled();
  });

  it('navigates to the linked page and dismisses when a linked toast is clicked', async () => {
    await show({ level: 'success', title: 'Claim approved', link: '/claims/c-1' });
    expect(rendered()[0].classList).toContain('clickable');

    rendered()[0].click();
    await fixture.whenStable();

    expect(navigateByUrl).toHaveBeenCalledWith('/claims/c-1');
    expect(rendered()).toHaveLength(0);
  });

  it('ignores clicks on toasts without a link', async () => {
    await show({ level: 'info', title: 'Just so you know' });
    expect(rendered()[0].classList).not.toContain('clickable');

    rendered()[0].click();
    await fixture.whenStable();

    expect(navigateByUrl).not.toHaveBeenCalled();
    expect(rendered()).toHaveLength(1);
  });
});
