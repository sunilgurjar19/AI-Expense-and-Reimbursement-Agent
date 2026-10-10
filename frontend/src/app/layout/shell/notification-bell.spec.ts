import { computed, provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { makeNotification } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { AppNotification } from '../../core/models/models';
import { NotificationCenter } from '../../core/realtime/notification-center.service';
import { NotificationBell } from './notification-bell';

/** Test double with the same reactive surface as NotificationCenter. */
class FakeNotificationCenter {
  readonly items = signal<AppNotification[]>([]);
  readonly unread = computed(() => this.items().filter((n) => !n.read).length);
  readonly markRead = vi.fn();
  readonly markAllRead = vi.fn();
}

describe('NotificationBell', () => {
  let fixture: ComponentFixture<NotificationBell>;
  let center: FakeNotificationCenter;
  let navigateByUrl: MockInstance<Router['navigateByUrl']>;

  async function render(items: AppNotification[] = []) {
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideRouter([]),
        { provide: NotificationCenter, useClass: FakeNotificationCenter },
      ],
    });
    center = TestBed.inject(NotificationCenter) as unknown as FakeNotificationCenter;
    center.items.set(items);
    navigateByUrl = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
    fixture = TestBed.createComponent(NotificationBell); // TestBed attaches it to the document
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const bell = () => el().querySelector('.bell') as HTMLButtonElement;
  const badge = () => el().querySelector('.badge')?.textContent?.trim();
  const panel = () => el().querySelector('.panel');
  const items = () => Array.from(el().querySelectorAll<HTMLButtonElement>('.item'));

  async function openPanel() {
    bell().click();
    await fixture.whenStable();
  }

  const unread = (id: string, overrides: Partial<AppNotification> = {}) =>
    makeNotification({ id, read: false, ...overrides });

  describe('bell', () => {
    it('shows no badge when everything is read', async () => {
      await render([makeNotification({ read: true })]);

      expect(badge()).toBeUndefined();
      expect(bell().classList).not.toContain('ring');
    });

    it('shows the unread count and rings', async () => {
      await render([unread('n-1'), unread('n-2'), makeNotification({ id: 'n-3', read: true })]);

      expect(badge()).toBe('2');
      expect(bell().classList).toContain('ring');
    });

    it('caps the badge at 9+', async () => {
      await render(Array.from({ length: 12 }, (_, i) => unread(`n-${i}`)));
      expect(badge()).toBe('9+');
    });

    it('toggles the panel', async () => {
      await render();
      expect(panel()).toBeNull();

      await openPanel();
      expect(panel()).not.toBeNull();

      await openPanel();
      expect(panel()).toBeNull();
    });
  });

  describe('panel', () => {
    it('lists notifications, highlighting unread ones', async () => {
      await render([
        unread('n-1', { level: 'success', title: 'Claim paid', message: '₹827 sent' }),
        makeNotification({ id: 'n-2', read: true, level: 'warning', title: 'Receipt rejected' }),
      ]);
      await openPanel();

      const [first, second] = items();
      expect(first.classList).toContain('unread');
      expect(first.querySelector('strong')!.textContent).toBe('Claim paid');
      expect(first.querySelector('.text span')!.textContent).toBe('₹827 sent');
      expect(first.querySelector('.icon')!.textContent).toBe('🎉');
      expect(second.classList).not.toContain('unread');
      expect(second.querySelector('.icon')!.textContent).toBe('⚠️');
    });

    it('shows when the notification arrived', async () => {
      await render([unread('n-1', { created_at: new Date(Date.now() - 5 * 60_000).toISOString() })]);
      await openPanel();

      expect(items()[0].querySelector('small')!.textContent).toBe('5 minutes ago');
    });

    it('shows an empty state', async () => {
      await render([]);
      await openPanel();

      expect(el().querySelector('.empty')!.textContent).toContain("You're all caught up");
    });

    it('marks everything read', async () => {
      await render([unread('n-1')]);
      await openPanel();

      (el().querySelector('.link') as HTMLButtonElement).click();

      expect(center.markAllRead).toHaveBeenCalledTimes(1);
    });

    it('hides "Mark all read" when nothing is unread', async () => {
      await render([makeNotification({ read: true })]);
      await openPanel();

      expect(el().querySelector('.link')).toBeNull();
    });

    it('opens a notification: marks it read, closes the panel and follows its link', async () => {
      const notification = unread('n-1', { link: '/claims/c-9' });
      await render([notification]);
      await openPanel();

      items()[0].click();
      await fixture.whenStable();

      expect(center.markRead).toHaveBeenCalledWith(notification);
      expect(navigateByUrl).toHaveBeenCalledWith('/claims/c-9');
      expect(panel()).toBeNull();
    });

    it('does not navigate for notifications without a link', async () => {
      await render([unread('n-1', { link: null })]);
      await openPanel();

      items()[0].click();

      expect(center.markRead).toHaveBeenCalled();
      expect(navigateByUrl).not.toHaveBeenCalled();
    });

    it('closes when clicking elsewhere on the page, but not inside the panel', async () => {
      await render([unread('n-1')]);
      await openPanel();

      (el().querySelector('header') as HTMLElement).click();
      await fixture.whenStable();
      expect(panel()).not.toBeNull();

      document.body.click();
      await fixture.whenStable();
      expect(panel()).toBeNull();
    });
  });
});
