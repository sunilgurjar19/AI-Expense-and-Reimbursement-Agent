import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { Observable } from 'rxjs';

import { PlatformApi } from './platform.api';

const API = 'http://localhost:8100/api';

describe('PlatformApi', () => {
  let api: PlatformApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(PlatformApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  interface Case {
    name: string;
    call: (api: PlatformApi) => Observable<unknown>;
    method: string;
    url: string;
    body: unknown;
  }

  const cases: Case[] = [
    { name: 'publicConfig', call: (a) => a.publicConfig(), method: 'GET', url: '/config', body: null },
    { name: 'dashboard', call: (a) => a.dashboard(), method: 'GET', url: '/dashboard', body: null },
    { name: 'approvals', call: (a) => a.approvals(), method: 'GET', url: '/approvals', body: null },
    { name: 'approval', call: (a) => a.approval('c-1'), method: 'GET', url: '/approvals/c-1', body: null },
    {
      name: 'decide (approve)',
      call: (a) => a.decide('c-1', 'approve', 'Looks good'),
      method: 'POST',
      url: '/approvals/c-1',
      body: { decision: 'approve', comment: 'Looks good' },
    },
    {
      name: 'decide (reject)',
      call: (a) => a.decide('c-1', 'reject', 'Missing hotel bill'),
      method: 'POST',
      url: '/approvals/c-1',
      body: { decision: 'reject', comment: 'Missing hotel bill' },
    },
    { name: 'notifications', call: (a) => a.notifications(), method: 'GET', url: '/notifications', body: null },
    {
      name: 'markRead',
      call: (a) => a.markRead('n-7'),
      method: 'POST',
      url: '/notifications/n-7/read',
      body: {},
    },
    {
      name: 'markAllRead',
      call: (a) => a.markAllRead(),
      method: 'POST',
      url: '/notifications/read-all',
      body: {},
    },
    { name: 'llmSettings', call: (a) => a.llmSettings(), method: 'GET', url: '/settings/llm', body: null },
    {
      name: 'setProvider',
      call: (a) => a.setProvider('claude'),
      method: 'PUT',
      url: '/settings/llm',
      body: { provider: 'claude' },
    },
    {
      name: 'testProvider',
      call: (a) => a.testProvider('ollama'),
      method: 'POST',
      url: '/settings/llm/ollama/test',
      body: {},
    },
  ];

  it.each(cases)('$name → $method $url', ({ call, method, url, body }) => {
    let response: unknown;
    call(api).subscribe((res) => (response = res));

    const req = http.expectOne(`${API}${url}`);
    expect(req.request.method).toBe(method);
    expect(req.request.body).toEqual(body);

    req.flush({ ok: true });
    expect(response).toEqual({ ok: true });
  });
});
