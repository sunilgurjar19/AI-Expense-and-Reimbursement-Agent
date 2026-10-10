import { HttpClient, HttpInterceptorFn, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { AppConfigService } from './app-config.service';

describe('AppConfigService', () => {
  let service: AppConfigService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(AppConfigService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('starts with built-in defaults before anything is loaded', () => {
    expect(service.value).toEqual({
      apiBaseUrl: 'http://localhost:8100/api',
      appName: 'Expense & Reimbursement Agent',
      toastDurationMs: 5000,
      reconnectDelayMs: 4000,
      quickPrompts: ["What's my total?", 'Is this ready to submit?'],
    });
  });

  it('loads config/app-config.json and merges it over the defaults', async () => {
    const loading = service.load();

    const req = http.expectOne('config/app-config.json');
    expect(req.request.method).toBe('GET');
    req.flush({ apiBaseUrl: 'https://expenses.example.com/api', toastDurationMs: 8000 });
    await loading;

    expect(service.value.apiBaseUrl).toBe('https://expenses.example.com/api');
    expect(service.value.toastDurationMs).toBe(8000);
    // Keys missing from the file keep their defaults.
    expect(service.value.reconnectDelayMs).toBe(4000);
    expect(service.value.appName).toBe('Expense & Reimbursement Agent');
  });

  it('keeps the defaults and warns when the file cannot be loaded', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const loading = service.load();

    http.expectOne('config/app-config.json').flush('Not found', { status: 404, statusText: 'Not Found' });
    await expect(loading).resolves.toBeUndefined();

    expect(service.value.apiBaseUrl).toBe('http://localhost:8100/api');
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('app-config.json not found'));
  });

  it('builds API URLs from the configured base URL', async () => {
    expect(service.api('/claims')).toBe('http://localhost:8100/api/claims');

    const loading = service.load();
    http.expectOne('config/app-config.json').flush({ apiBaseUrl: '/api' });
    await loading;

    expect(service.api('/claims/c-1')).toBe('/api/claims/c-1');
  });
});

describe('AppConfigService (with interceptors registered)', () => {
  it('fetches the config without going through HTTP interceptors', async () => {
    // Interceptors depend on this config, so loading it must bypass them.
    const interceptor = vi.fn<HttpInterceptorFn>((req, next) => next(req));
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withInterceptors([interceptor])), provideHttpClientTesting()],
    });
    const service = TestBed.inject(AppConfigService);
    const http = TestBed.inject(HttpTestingController);

    const loading = service.load();
    http.expectOne('config/app-config.json').flush({});
    await loading;
    expect(interceptor).not.toHaveBeenCalled();

    // Sanity check: a regular HttpClient request does hit the interceptor.
    TestBed.inject(HttpClient).get('/ping').subscribe();
    http.expectOne('/ping').flush({});
    expect(interceptor).toHaveBeenCalledTimes(1);
    http.verify();
  });
});
