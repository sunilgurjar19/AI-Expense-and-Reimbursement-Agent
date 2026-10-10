import { HttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationInitStatus } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { TEST_TOKEN, seedSession } from '@testing/fakes';

import { appConfig } from './app.config';
import { routes } from './app.routes';
import { AppConfigService } from './core/config/app-config.service';

describe('appConfig', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    seedSession();
    TestBed.configureTestingModule({ providers: [...appConfig.providers, provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController); // instantiating TestBed runs the app initializers
  });

  afterEach(() => http.verify());

  it('loads the runtime configuration before the app starts', async () => {
    http.expectOne('config/app-config.json').flush({ apiBaseUrl: 'https://api.example.com' });
    await TestBed.inject(ApplicationInitStatus).donePromise;

    expect(TestBed.inject(AppConfigService).api('/claims')).toBe('https://api.example.com/claims');
  });

  it('registers the auth interceptor on HttpClient', () => {
    http.expectOne('config/app-config.json').flush({});

    TestBed.inject(HttpClient).get('/api/claims').subscribe();

    const req = http.expectOne('/api/claims');
    expect(req.request.headers.get('Authorization')).toBe(`Bearer ${TEST_TOKEN}`);
    req.flush([]);
  });

  it('registers the application routes', () => {
    http.expectOne('config/app-config.json').flush({});
    expect(TestBed.inject(Router).config).toEqual(routes);
  });
});
