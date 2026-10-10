import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, CanActivateFn, Router, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';
import { seedSession } from '@testing/fakes';
import { makeManager, makeUser } from '@testing/fixtures';

import { authGuard, guestGuard, managerGuard } from './auth.guards';

describe('auth guards', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
  });

  /** Run a functional guard in an injection context and describe its outcome as a URL. */
  function run(guard: CanActivateFn): true | string {
    const result = TestBed.runInInjectionContext(() =>
      guard({} as ActivatedRouteSnapshot, {} as RouterStateSnapshot),
    );
    if (result === true) return true;
    expect(result).toBeInstanceOf(UrlTree);
    return TestBed.inject(Router).serializeUrl(result as UrlTree);
  }

  describe('authGuard', () => {
    it('lets a signed-in user through', () => {
      seedSession(makeUser());
      expect(run(authGuard)).toBe(true);
    });

    it('sends a signed-out visitor to /login', () => {
      expect(run(authGuard)).toBe('/login');
    });
  });

  describe('guestGuard', () => {
    it('lets a signed-out visitor see the login page', () => {
      expect(run(guestGuard)).toBe(true);
    });

    it('sends an already signed-in user to the dashboard', () => {
      seedSession(makeUser());
      expect(run(guestGuard)).toBe('/dashboard');
    });
  });

  describe('managerGuard', () => {
    it('lets a manager through', () => {
      seedSession(makeManager());
      expect(run(managerGuard)).toBe(true);
    });

    it('sends an employee back to the dashboard', () => {
      seedSession(makeUser({ role: 'employee' }));
      expect(run(managerGuard)).toBe('/dashboard');
    });

    it('sends a signed-out visitor to the dashboard (where authGuard takes over)', () => {
      expect(run(managerGuard)).toBe('/dashboard');
    });
  });
});
