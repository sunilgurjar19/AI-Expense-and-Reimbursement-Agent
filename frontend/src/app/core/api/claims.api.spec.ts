import { HttpEvent, HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { TEST_TOKEN, seedSession } from '@testing/fakes';
import { makeReceipt } from '@testing/fixtures';
import { Observable } from 'rxjs';

import { Receipt } from '../models/models';
import { ClaimsApi } from './claims.api';

const API = 'http://localhost:8100/api';

describe('ClaimsApi', () => {
  let api: ClaimsApi;
  let http: HttpTestingController;

  beforeEach(() => {
    seedSession(); // file URLs embed the signed-in user's token
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    api = TestBed.inject(ClaimsApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  interface Case {
    name: string;
    call: (api: ClaimsApi) => Observable<unknown>;
    method: string;
    url: string;
    body: unknown;
  }

  const cases: Case[] = [
    { name: 'list', call: (a) => a.list(), method: 'GET', url: '/claims', body: null },
    { name: 'create (empty)', call: (a) => a.create(), method: 'POST', url: '/claims', body: {} },
    {
      name: 'create (with details)',
      call: (a) => a.create({ title: 'Goa offsite', purpose: 'Team event' }),
      method: 'POST',
      url: '/claims',
      body: { title: 'Goa offsite', purpose: 'Team event' },
    },
    { name: 'get', call: (a) => a.get('c-1'), method: 'GET', url: '/claims/c-1', body: null },
    {
      name: 'update',
      call: (a) => a.update('c-1', { title: 'Renamed' }),
      method: 'PATCH',
      url: '/claims/c-1',
      body: { title: 'Renamed' },
    },
    { name: 'delete', call: (a) => a.delete('c-1'), method: 'DELETE', url: '/claims/c-1', body: null },
    {
      name: 'updateReceipt',
      call: (a) => a.updateReceipt('c-1', 'r-2', { vendor: 'Taj', total_amount: 1200 }),
      method: 'PATCH',
      url: '/claims/c-1/receipts/r-2',
      body: { vendor: 'Taj', total_amount: 1200 },
    },
    {
      name: 'retryReceipt',
      call: (a) => a.retryReceipt('c-1', 'r-2'),
      method: 'POST',
      url: '/claims/c-1/receipts/r-2/retry',
      body: {},
    },
    {
      name: 'deleteReceipt',
      call: (a) => a.deleteReceipt('c-1', 'r-2'),
      method: 'DELETE',
      url: '/claims/c-1/receipts/r-2',
      body: null,
    },
    {
      name: 'answer',
      call: (a) => a.answer('c-1', 'q-3', 'keep'),
      method: 'POST',
      url: '/claims/c-1/questions/q-3/answer',
      body: { answer: 'keep' },
    },
    {
      name: 'chat',
      call: (a) => a.chat('c-1', "What's my total?"),
      method: 'POST',
      url: '/claims/c-1/chat',
      body: { message: "What's my total?" },
    },
    { name: 'submit', call: (a) => a.submit('c-1'), method: 'POST', url: '/claims/c-1/submit', body: {} },
    { name: 'reopen', call: (a) => a.reopen('c-1'), method: 'POST', url: '/claims/c-1/reopen', body: {} },
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

  describe('upload', () => {
    const files = [
      new File(['%PDF-1.4'], 'hotel.pdf', { type: 'application/pdf' }),
      new File(['jpeg-bytes'], 'cab.jpg', { type: 'image/jpeg' }),
    ];

    it('posts every file as multipart "files" with progress reporting', () => {
      api.upload('c-1', files).subscribe();

      const req = http.expectOne(`${API}/claims/c-1/receipts`);
      expect(req.request.method).toBe('POST');
      expect(req.request.reportProgress).toBe(true);

      const form = req.request.body as FormData;
      expect(form).toBeInstanceOf(FormData);
      expect((form.getAll('files') as File[]).map((f) => f.name)).toEqual(['hotel.pdf', 'cab.jpg']);
      req.flush([]);
    });

    it('streams upload progress events followed by the response', () => {
      const events: HttpEvent<Receipt[]>[] = [];
      api.upload('c-1', files).subscribe((event) => events.push(event));

      const req = http.expectOne(`${API}/claims/c-1/receipts`);
      req.event({ type: HttpEventType.UploadProgress, loaded: 512, total: 1024 });
      req.flush([makeReceipt()]);

      const types = events.map((e) => e.type);
      expect(types).toContain(HttpEventType.UploadProgress);
      expect(types.at(-1)).toBe(HttpEventType.Response);
    });
  });

  describe('document URLs', () => {
    it('links to the owner endpoint with the access token', () => {
      expect(api.fileUrl('c-1', 'r-2')).toBe(`${API}/claims/c-1/receipts/r-2/file?access_token=${TEST_TOKEN}`);
    });

    it('can force a download', () => {
      expect(api.fileUrl('c-1', 'r-2', { download: true })).toBe(
        `${API}/claims/c-1/receipts/r-2/file?access_token=${TEST_TOKEN}&download=true`,
      );
    });

    it('uses the approver-scoped endpoint in approval mode', () => {
      expect(api.fileUrl('c-1', 'r-2', { approval: true, download: true })).toBe(
        `${API}/approvals/c-1/receipts/r-2/file?access_token=${TEST_TOKEN}&download=true`,
      );
    });

    it('builds the attachments zip URL for owners and approvers', () => {
      expect(api.attachmentsZipUrl('c-1')).toBe(`${API}/claims/c-1/attachments.zip?access_token=${TEST_TOKEN}`);
      expect(api.attachmentsZipUrl('c-1', true)).toBe(
        `${API}/approvals/c-1/attachments.zip?access_token=${TEST_TOKEN}`,
      );
    });

    it('builds the export URL', () => {
      expect(api.exportUrl('c-1')).toBe(`${API}/claims/c-1/export?access_token=${TEST_TOKEN}`);
    });
  });

  describe('attachment', () => {
    const receipt = makeReceipt({
      id: 'r-2',
      claim_id: 'c-1',
      file_name: 'taj.jpg',
      mime_type: 'image/jpeg',
      size_bytes: 2_400_000,
    });

    it('describes a receipt document for the attachment viewer', () => {
      expect(api.attachment(receipt, 'Taj · Lodging')).toEqual({
        id: 'r-2',
        name: 'taj.jpg',
        mimeType: 'image/jpeg',
        sizeBytes: 2_400_000,
        subtitle: 'Taj · Lodging',
        viewUrl: `${API}/claims/c-1/receipts/r-2/file?access_token=${TEST_TOKEN}`,
        downloadUrl: `${API}/claims/c-1/receipts/r-2/file?access_token=${TEST_TOKEN}&download=true`,
      });
    });

    it('points at the approval endpoints when opened by an approver', () => {
      const attachment = api.attachment(receipt, 'Taj', true);
      expect(attachment.viewUrl).toContain(`${API}/approvals/c-1/`);
      expect(attachment.downloadUrl).toContain(`${API}/approvals/c-1/`);
    });
  });
});
