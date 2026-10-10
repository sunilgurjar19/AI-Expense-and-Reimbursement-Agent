import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TEST_TOKEN, seedSession } from '@testing/fakes';
import { makeClaim, makeNotification } from '@testing/fixtures';

import { AuthService } from '../auth/auth.service';
import { AppNotification, Claim } from '../models/models';
import { RealtimeService } from './realtime.service';

/** Minimal scriptable EventSource (jsdom does not implement one). */
class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onerror: ((event: Event) => void) | null = null;
  closed = false;
  private readonly listeners = new Map<string, ((event: Event) => void)[]>();

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  /** Simulate a server-sent event. */
  emit(type: string, data?: unknown): void {
    const event = new MessageEvent(type, { data: JSON.stringify(data ?? {}) });
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  /** Simulate a connection error, leaving the source in the given state. */
  fail(readyState: number): void {
    this.readyState = readyState;
    this.onerror?.(new Event('error'));
  }
}

const STREAM_URL = `http://localhost:8100/api/events/stream?access_token=${TEST_TOKEN}`;
const RECONNECT_DELAY = 4000; // AppConfigService default

describe('RealtimeService', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource);
  });

  function setup(): RealtimeService {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    const service = TestBed.inject(RealtimeService);
    TestBed.tick(); // run the auth effect
    return service;
  }

  const sources = () => FakeEventSource.instances;
  const latest = () => sources().at(-1)!;

  it('does not open a stream while signed out', () => {
    const service = setup();

    expect(sources()).toHaveLength(0);
    expect(service.connected()).toBe(false);
  });

  describe('when signed in', () => {
    beforeEach(() => seedSession());

    it('opens the event stream authenticated with the access token', () => {
      setup();

      expect(sources()).toHaveLength(1);
      expect(latest().url).toBe(STREAM_URL);
    });

    it('is not "connected" until the server says it is ready', () => {
      const service = setup();
      expect(service.connected()).toBe(false);

      latest().emit('ready');

      expect(service.connected()).toBe(true);
    });

    it('publishes live claim updates', () => {
      const service = setup();
      const received: Claim[] = [];
      service.claimUpdates.subscribe((claim) => received.push(claim));
      const claim = makeClaim({ id: 'c-9', status: 'processing' });

      latest().emit('claim.updated', claim);

      expect(received).toEqual([claim]);
    });

    it('publishes notifications', () => {
      const service = setup();
      const received: AppNotification[] = [];
      service.notifications.subscribe((n) => received.push(n));
      const notification = makeNotification({ title: 'Claim paid' });

      latest().emit('notification', notification);

      expect(received).toEqual([notification]);
    });

    it('reconnects after the configured delay when the server closes the stream', () => {
      vi.useFakeTimers();
      const service = setup();
      latest().emit('ready');

      latest().fail(FakeEventSource.CLOSED);
      expect(service.connected()).toBe(false);

      vi.advanceTimersByTime(RECONNECT_DELAY - 1);
      expect(sources()).toHaveLength(1);

      vi.advanceTimersByTime(1);
      expect(sources()).toHaveLength(2);
      expect(latest().url).toBe(STREAM_URL);
      expect(sources()[0].closed).toBe(true);
    });

    it('leaves transient errors to the browser (no manual reconnect while it is retrying)', () => {
      vi.useFakeTimers();
      const service = setup();
      latest().emit('ready');

      latest().fail(FakeEventSource.CONNECTING);
      vi.advanceTimersByTime(RECONNECT_DELAY * 3);

      expect(service.connected()).toBe(false);
      expect(sources()).toHaveLength(1);
    });

    it('closes the stream and cancels a pending reconnect on sign-out', () => {
      vi.useFakeTimers();
      const service = setup();
      const first = latest();
      first.fail(FakeEventSource.CLOSED); // schedules a reconnect

      TestBed.inject(AuthService).logout(false);
      TestBed.tick();
      vi.advanceTimersByTime(RECONNECT_DELAY * 2);

      expect(first.closed).toBe(true);
      expect(sources()).toHaveLength(1);
      expect(service.connected()).toBe(false);
    });
  });
});
