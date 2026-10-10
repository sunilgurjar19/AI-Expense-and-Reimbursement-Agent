import { HttpClient, HttpErrorResponse, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { TEST_TOKEN, seedSession } from '@testing/fakes';
import type { MockInstance } from 'vitest';

import { ToastService } from '../ui/toast.service';
import { authInterceptor, errorMessage } from './auth.interceptor';
import { AuthService } from './auth.service';

const API = 'http://localhost:8100/api';

describe('authInterceptor', () => {
  let client: HttpClient;
  let http: HttpTestingController;
  let auth: AuthService;
  let toast: MockInstance<ToastService['show']>;
  let navigate: MockInstance<Router['navigate']>;

  function setup(): void {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    client = TestBed.inject(HttpClient);
    http = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    toast = vi.spyOn(TestBed.inject(ToastService), 'show').mockImplementation(() => {});
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  }

  /** Fire a GET and capture the error it fails with (if any). */
  function get(url: string): { error?: HttpErrorResponse } {
    const outcome: { error?: HttpErrorResponse } = {};
    client.get(url).subscribe({ error: (err: HttpErrorResponse) => (outcome.error = err) });
    return outcome;
  }

  afterEach(() => http.verify());

  describe('authorization header', () => {
    it('attaches the bearer token when signed in', () => {
      seedSession();
      setup();

      client.get(`${API}/claims`).subscribe();

      const req = http.expectOne(`${API}/claims`);
      expect(req.request.headers.get('Authorization')).toBe(`Bearer ${TEST_TOKEN}`);
      req.flush([]);
    });

    it('sends no Authorization header when signed out', () => {
      setup();

      client.get(`${API}/auth/demo-users`).subscribe();

      const req = http.expectOne(`${API}/auth/demo-users`);
      expect(req.request.headers.has('Authorization')).toBe(false);
      req.flush([]);
    });
  });

  describe('401 Unauthorized', () => {
    it('signs the user out and explains why when the session has expired', () => {
      seedSession();
      setup();

      const outcome = get(`${API}/claims`);
      http.expectOne(`${API}/claims`).flush({ detail: 'Token expired' }, { status: 401, statusText: 'Unauthorized' });

      expect(auth.isAuthenticated()).toBe(false);
      expect(navigate).toHaveBeenCalledWith(['/login']);
      expect(toast).toHaveBeenCalledWith({
        level: 'warning',
        title: 'Session expired',
        message: 'Please sign in again.',
      });
      // The caller still receives the original error.
      expect(outcome.error?.status).toBe(401);
    });

    it('does not treat rejected credentials on /auth/login as an expired session', () => {
      seedSession();
      setup();

      client.post(`${API}/auth/login`, {}).subscribe({ error: () => {} });
      http.expectOne(`${API}/auth/login`).flush({ detail: 'Invalid' }, { status: 401, statusText: 'Unauthorized' });

      expect(auth.isAuthenticated()).toBe(true);
      expect(toast).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
    });

    it('does nothing extra when nobody is signed in', () => {
      setup();

      const outcome = get(`${API}/claims`);
      http.expectOne(`${API}/claims`).flush(null, { status: 401, statusText: 'Unauthorized' });

      expect(toast).not.toHaveBeenCalled();
      expect(navigate).not.toHaveBeenCalled();
      expect(outcome.error?.status).toBe(401);
    });
  });

  it('warns that the backend is unreachable on network errors (status 0)', () => {
    seedSession();
    setup();

    const outcome = get(`${API}/claims`);
    http.expectOne(`${API}/claims`).error(new ProgressEvent('error'));

    expect(toast).toHaveBeenCalledWith({
      level: 'error',
      title: 'Server unreachable',
      message: 'Is the FastAPI backend running?',
    });
    expect(outcome.error?.status).toBe(0);
    expect(auth.isAuthenticated()).toBe(true);
  });

  it('passes other errors straight through to the caller', () => {
    seedSession();
    setup();

    const outcome = get(`${API}/claims`);
    http.expectOne(`${API}/claims`).flush({ detail: 'Boom' }, { status: 500, statusText: 'Server Error' });

    expect(outcome.error?.status).toBe(500);
    expect(toast).not.toHaveBeenCalled();
    expect(auth.isAuthenticated()).toBe(true);
  });
});

describe('errorMessage', () => {
  const httpError = (error: unknown, status = 400) => new HttpErrorResponse({ error, status });

  it('uses the API "detail" string', () => {
    expect(errorMessage(httpError({ detail: 'Claim is locked' }))).toBe('Claim is locked');
  });

  it('uses the first message of a FastAPI validation error list', () => {
    const error = httpError({ detail: [{ loc: ['body', 'title'], msg: 'Field required' }, { msg: 'Other' }] }, 422);
    expect(errorMessage(error)).toBe('Field required');
  });

  it.each([
    ['an empty validation list', { detail: [] }],
    ['a validation entry without msg', { detail: [{ loc: ['body'] }] }],
    ['a body without detail', { message: 'nope' }],
    ['a non-JSON body', 'Internal Server Error'],
    ['no body at all', null],
  ])('falls back for %s', (_, body) => {
    expect(errorMessage(httpError(body), 'Upload failed')).toBe('Upload failed');
  });

  it('falls back for errors that did not come from HttpClient', () => {
    expect(errorMessage(new Error('kaboom'), 'Upload failed')).toBe('Upload failed');
    expect(errorMessage(undefined, 'Upload failed')).toBe('Upload failed');
  });

  it('defaults the fallback to "Something went wrong"', () => {
    expect(errorMessage(new Error('kaboom'))).toBe('Something went wrong');
  });
});
