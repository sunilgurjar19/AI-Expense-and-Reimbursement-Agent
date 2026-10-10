import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { makeManager, makeUser } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { DemoUser, LoginResponse } from '../models/models';
import { AuthService } from './auth.service';

const API = 'http://localhost:8100/api';
const STORAGE_KEY = 'era.session';

describe('AuthService', () => {
  let http: HttpTestingController;
  let navigate: MockInstance<Router['navigate']>;

  function setup(): AuthService {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    return TestBed.inject(AuthService);
  }

  afterEach(() => http.verify());

  describe('without a stored session', () => {
    it('starts signed out', () => {
      const auth = setup();

      expect(auth.isAuthenticated()).toBe(false);
      expect(auth.user()).toBeNull();
      expect(auth.token()).toBeNull();
      expect(auth.isManager()).toBe(false);
    });
  });

  describe('restoring a session', () => {
    it('restores the user and token persisted in localStorage', () => {
      const user = makeUser();
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: 'jwt-123', user }));

      const auth = setup();

      expect(auth.isAuthenticated()).toBe(true);
      expect(auth.user()).toEqual(user);
      expect(auth.token()).toBe('jwt-123');
    });

    it('ignores a corrupted stored session instead of crashing', () => {
      localStorage.setItem(STORAGE_KEY, '{not valid json');

      const auth = setup();

      expect(auth.isAuthenticated()).toBe(false);
    });
  });

  describe('login', () => {
    const response: LoginResponse = { access_token: 'jwt-abc', token_type: 'bearer', user: makeUser() };

    it('posts the credentials to /auth/login', () => {
      const auth = setup();

      auth.login('employee', 'employee123').subscribe();

      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({ username: 'employee', password: 'employee123' });
      req.flush(response);
    });

    it('stores the session in memory and in localStorage on success', () => {
      const auth = setup();
      let result: LoginResponse | undefined;

      auth.login('employee', 'employee123').subscribe((res) => (result = res));
      http.expectOne(`${API}/auth/login`).flush(response);

      expect(result).toEqual(response);
      expect(auth.isAuthenticated()).toBe(true);
      expect(auth.token()).toBe('jwt-abc');
      expect(auth.user()).toEqual(response.user);
      expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual({ token: 'jwt-abc', user: response.user });
    });

    it('stays signed out and stores nothing when the credentials are rejected', () => {
      const auth = setup();
      const error = vi.fn();

      auth.login('employee', 'wrong').subscribe({ error });
      http
        .expectOne(`${API}/auth/login`)
        .flush({ detail: 'Invalid username or password' }, { status: 401, statusText: 'Unauthorized' });

      expect(error).toHaveBeenCalled();
      expect(auth.isAuthenticated()).toBe(false);
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });
  });

  describe('isManager', () => {
    it('is true only for users with the manager role', () => {
      const auth = setup();

      auth.login('manager', 'manager123').subscribe();
      http.expectOne(`${API}/auth/login`).flush({ access_token: 't', token_type: 'bearer', user: makeManager() });

      expect(auth.isManager()).toBe(true);
    });

    it('is false for employees', () => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: 't', user: makeUser({ role: 'employee' }) }));
      expect(setup().isManager()).toBe(false);
    });
  });

  describe('logout', () => {
    beforeEach(() => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ token: 'jwt-123', user: makeUser() }));
    });

    it('clears the session everywhere and returns to the login page', () => {
      const auth = setup();

      auth.logout();

      expect(auth.isAuthenticated()).toBe(false);
      expect(auth.user()).toBeNull();
      expect(auth.token()).toBeNull();
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
      expect(navigate).toHaveBeenCalledWith(['/login']);
    });

    it('can clear the session without navigating', () => {
      const auth = setup();

      auth.logout(false);

      expect(auth.isAuthenticated()).toBe(false);
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  it('loads the demo accounts shown on the login page', () => {
    const auth = setup();
    const users: DemoUser[] = [{ username: 'employee', password: 'employee123', name: 'Asha', role: 'employee' }];
    let result: DemoUser[] | undefined;

    auth.demoUsers().subscribe((list) => (result = list));
    const req = http.expectOne(`${API}/auth/demo-users`);
    expect(req.request.method).toBe('GET');
    req.flush(users);

    expect(result).toEqual(users);
  });
});
