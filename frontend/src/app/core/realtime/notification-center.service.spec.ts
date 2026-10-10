import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { FakeRealtimeService, injectFakeRealtime, provideFakeRealtime, seedSession } from '@testing/fakes';
import { makeNotification } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { AuthService } from '../auth/auth.service';
import { ToastService } from '../ui/toast.service';
import { NotificationCenter } from './notification-center.service';

const API = 'http://localhost:8100/api';

describe('NotificationCenter', () => {
  let http: HttpTestingController;
  let realtime: FakeRealtimeService;
  let toast: MockInstance<ToastService['show']>;

  function setup(): NotificationCenter {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([]), provideFakeRealtime()],
    });
    http = TestBed.inject(HttpTestingController);
    realtime = injectFakeRealtime();
    toast = vi.spyOn(TestBed.inject(ToastService), 'show').mockImplementation(() => {});
    const center = TestBed.inject(NotificationCenter);
    TestBed.tick(); // run the auth effect
    return center;
  }

  afterEach(() => http.verify());

  it('stays empty and quiet while signed out', () => {
    const center = setup();

    http.expectNone(`${API}/notifications`);
    expect(center.items()).toEqual([]);
    expect(center.unread()).toBe(0);
  });

  describe('when signed in', () => {
    const unread = makeNotification({ id: 'n-1', read: false });
    const read = makeNotification({ id: 'n-2', read: true });
    let center: NotificationCenter;

    beforeEach(() => {
      seedSession();
      center = setup();
      http.expectOne(`${API}/notifications`).flush([unread, read]);
    });

    it('loads the notification list and counts unread items', () => {
      expect(center.items()).toEqual([unread, read]);
      expect(center.unread()).toBe(1);
    });

    it('clears the list when the user signs out', () => {
      TestBed.inject(AuthService).logout(false);
      TestBed.tick();

      expect(center.items()).toEqual([]);
    });

    it('prepends live notifications and pops a toast for each', () => {
      const live = makeNotification({
        id: 'n-3',
        level: 'success',
        title: 'Claim paid',
        message: '₹827 is on its way',
        link: '/claims/c-1',
      });

      realtime.notifications.next(live);

      expect(center.items().map((n) => n.id)).toEqual(['n-3', 'n-1', 'n-2']);
      expect(center.unread()).toBe(2);
      expect(toast).toHaveBeenCalledWith({
        level: 'success',
        title: 'Claim paid',
        message: '₹827 is on its way',
        link: '/claims/c-1',
      });
    });

    it('marks one notification read optimistically and tells the server', () => {
      center.markRead(unread);

      expect(center.unread()).toBe(0);
      expect(center.items().find((n) => n.id === 'n-1')?.read).toBe(true);
      const req = http.expectOne(`${API}/notifications/n-1/read`);
      expect(req.request.method).toBe('POST');
      req.flush(null);
    });

    it('does not call the server for a notification that is already read', () => {
      center.markRead(read);
      http.expectNone(`${API}/notifications/n-2/read`);
    });

    it('marks everything read', () => {
      center.markAllRead();

      expect(center.unread()).toBe(0);
      expect(center.items().every((n) => n.read)).toBe(true);
      http.expectOne(`${API}/notifications/read-all`).flush(null);
    });
  });
});
