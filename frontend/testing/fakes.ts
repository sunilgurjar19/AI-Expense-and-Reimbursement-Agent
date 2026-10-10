/** Shared test doubles. */
import { Provider, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import type { AppNotification, Claim, User } from '../src/app/core/models/models';
import { RealtimeService } from '../src/app/core/realtime/realtime.service';
import { makeUser } from './fixtures';

/** Stand-in for the SSE-backed RealtimeService: tests push events through the subjects. */
export class FakeRealtimeService {
  readonly connected = signal(false);
  readonly claimUpdates = new Subject<Claim>();
  readonly notifications = new Subject<AppNotification>();
}

export function provideFakeRealtime(): Provider {
  return { provide: RealtimeService, useClass: FakeRealtimeService };
}

/** Typed access to the fake registered with provideFakeRealtime(). */
export function injectFakeRealtime(): FakeRealtimeService {
  return TestBed.inject(RealtimeService) as unknown as FakeRealtimeService;
}

export const TEST_TOKEN = 'test-token';

/**
 * Persist a signed-in session the way AuthService does, so that a freshly created
 * AuthService starts authenticated. Call before the service is first injected.
 */
export function seedSession(user: User = makeUser(), token = TEST_TOKEN): void {
  localStorage.setItem('era.session', JSON.stringify({ token, user }));
}
