import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { makeUser } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { AuthService } from '../../../core/auth/auth.service';
import { DemoUser } from '../../../core/models/models';
import { ToastService } from '../../../core/ui/toast.service';
import { LoginPage } from './login';

const API = 'http://localhost:8100/api';

describe('LoginPage', () => {
  let fixture: ComponentFixture<LoginPage>;
  let http: HttpTestingController;
  let navigate: MockInstance<Router['navigate']>;
  let toastSuccess: MockInstance<ToastService['success']>;

  const demoUsers: DemoUser[] = [
    { username: 'employee', password: 'employee123', name: 'Asha Verma', role: 'employee' },
    { username: 'manager', password: 'manager123', name: 'Meera Iyer', role: 'manager' },
  ];

  async function render(demo: DemoUser[] | 'error' = demoUsers) {
    TestBed.configureTestingModule({
      providers: [provideZonelessChangeDetection(), provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    toastSuccess = vi.spyOn(TestBed.inject(ToastService), 'success').mockImplementation(() => {});
    fixture = TestBed.createComponent(LoginPage);

    const req = http.expectOne(`${API}/auth/demo-users`);
    if (demo === 'error') req.flush(null, { status: 500, statusText: 'Server Error' });
    else req.flush(demo);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const username = () => el().querySelector('#username') as HTMLInputElement;
  const password = () => el().querySelector('#password') as HTMLInputElement;
  const submitButton = () => el().querySelector('button[type=submit]') as HTMLButtonElement;
  const demoButtons = () => Array.from(el().querySelectorAll<HTMLButtonElement>('.demo-user'));

  async function type(input: HTMLInputElement, value: string) {
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  async function signIn(user = 'employee', pass = 'employee123') {
    await type(username(), user);
    await type(password(), pass);
    submitButton().click();
    await fixture.whenStable();
  }

  it('explains the product flow', async () => {
    await render();
    const steps = Array.from(el().querySelectorAll('.flow li strong')).map((s) => s.textContent);
    expect(steps).toEqual(['Drop a pile of bills', 'AI reads & sorts', 'Policy & duplicates', 'Ready to submit']);
  });

  describe('demo accounts', () => {
    it('lists the demo accounts with their role', async () => {
      await render();

      expect(demoButtons().map((b) => b.querySelector('strong')!.textContent)).toEqual(['Asha Verma', 'Meera Iyer']);
      expect(demoButtons()[1].querySelector('.demo-avatar')!.classList).toContain('manager');
      expect(demoButtons()[0].querySelector('small')!.textContent).toBe('employee / employee123');
    });

    it('fills in the credentials when a demo account is picked', async () => {
      await render();

      demoButtons()[1].click();
      await fixture.whenStable();

      expect(username().value).toBe('manager');
      expect(password().value).toBe('manager123');
      expect(demoButtons()[1].classList).toContain('selected');
    });

    it('hides the demo section when the accounts cannot be loaded', async () => {
      await render('error');
      expect(el().querySelector('.demo')).toBeNull();
    });
  });

  describe('signing in', () => {
    it('keeps the button disabled until both fields are filled', async () => {
      await render();
      expect(submitButton().disabled).toBe(true);

      await type(username(), 'employee');
      expect(submitButton().disabled).toBe(true);

      await type(password(), 'employee123');
      expect(submitButton().disabled).toBe(false);
    });

    it('signs in with the trimmed username, welcomes the user and opens the dashboard', async () => {
      await render();
      await signIn('  employee  ', 'employee123');

      const req = http.expectOne(`${API}/auth/login`);
      expect(req.request.body).toEqual({ username: 'employee', password: 'employee123' });
      expect(submitButton().textContent).toContain('Signing in…');
      expect(submitButton().disabled).toBe(true);

      req.flush({ access_token: 'jwt', token_type: 'bearer', user: makeUser({ name: 'Asha Verma' }) });

      expect(TestBed.inject(AuthService).isAuthenticated()).toBe(true);
      expect(toastSuccess).toHaveBeenCalledWith('Welcome back, Asha!', 'You are signed in.');
      expect(navigate).toHaveBeenCalledWith(['/dashboard']);
    });

    it('shows the server error and lets the user try again', async () => {
      await render();
      await signIn('employee', 'wrong');

      http
        .expectOne(`${API}/auth/login`)
        .flush({ detail: 'Invalid username or password' }, { status: 401, statusText: 'Unauthorized' });
      await fixture.whenStable();

      expect(el().querySelector('.error')!.textContent).toContain('Invalid username or password');
      expect(el().querySelector('form')!.classList).toContain('shake');
      expect(submitButton().disabled).toBe(false);
      expect(navigate).not.toHaveBeenCalled();
    });

    it('falls back to a generic error message', async () => {
      await render();
      await signIn();

      http.expectOne(`${API}/auth/login`).error(new ProgressEvent('error'));
      await fixture.whenStable();

      expect(el().querySelector('.error')!.textContent).toContain('Unable to sign in');
    });

    it('clears a previous error when a demo account is picked', async () => {
      await render();
      await signIn('employee', 'wrong');
      http.expectOne(`${API}/auth/login`).flush({ detail: 'Invalid' }, { status: 401, statusText: 'Unauthorized' });
      await fixture.whenStable();

      demoButtons()[0].click();
      await fixture.whenStable();

      expect(el().querySelector('.error')).toBeNull();
    });

    it('ignores repeated submits while a sign-in is in flight', async () => {
      await render();
      await signIn();

      el().querySelector('form')!.dispatchEvent(new Event('submit'));

      http.expectOne(`${API}/auth/login`).flush({ access_token: 'jwt', token_type: 'bearer', user: makeUser() });
    });
  });

  it('can reveal the password', async () => {
    await render();
    const reveal = el().querySelector('.reveal') as HTMLButtonElement;
    expect(password().type).toBe('password');

    reveal.click();
    await fixture.whenStable();

    expect(password().type).toBe('text');
    expect(reveal.getAttribute('aria-label')).toBe('Hide password');
  });
});
