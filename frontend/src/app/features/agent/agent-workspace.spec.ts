import { HttpEventType, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { FakeRealtimeService, TEST_TOKEN, injectFakeRealtime, provideFakeRealtime, seedSession } from '@testing/fakes';
import { makeCategory, makeClaim, makePublicConfig, makeQuestion, makeReceipt, makeUser } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { PolicyStore } from '../../core/config/policy.store';
import { Claim, PublicConfig } from '../../core/models/models';
import { ToastService } from '../../core/ui/toast.service';
import { AgentWorkspace } from './agent-workspace';

const API = 'http://localhost:8100/api';

describe('AgentWorkspace', () => {
  let fixture: ComponentFixture<AgentWorkspace>;
  let http: HttpTestingController;
  let realtime: FakeRealtimeService;
  let navigate: MockInstance<Router['navigate']>;
  let toast: { success: MockInstance<ToastService['success']>; error: MockInstance<ToastService['error']> };

  const categories = [makeCategory({ key: 'travel', label: 'Travel', icon: '🚕' })];
  const pdf = new File(['%PDF'], 'hotel.pdf', { type: 'application/pdf' });

  function setup(config: PublicConfig = makePublicConfig({ llm_provider: 'ollama' }), signedIn = true) {
    if (signedIn) seedSession(makeUser({ name: 'Asha Verma' }));
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        provideFakeRealtime(),
        {
          provide: PolicyStore,
          useValue: {
            currency: signal('INR'),
            agentName: signal('Rika'),
            config: signal(config),
            categories: signal(categories),
            category: (key: string | null | undefined) => categories.find((c) => c.key === key),
          },
        },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    realtime = injectFakeRealtime();
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    const toasts = TestBed.inject(ToastService);
    toast = {
      success: vi.spyOn(toasts, 'success').mockImplementation(() => {}),
      error: vi.spyOn(toasts, 'error').mockImplementation(() => {}),
    };
    fixture = TestBed.createComponent(AgentWorkspace);
  }

  /** Open "/agent" - a brand-new, unsaved claim. */
  async function renderNew(config?: PublicConfig) {
    setup(config);
    await fixture.whenStable();
  }

  /** Open "/agent/:id" and answer the GET with `claim`. */
  async function renderExisting(claim: Claim, config?: PublicConfig) {
    setup(config);
    fixture.componentRef.setInput('id', claim.id);
    await fixture.whenStable();
    http.expectOne(`${API}/claims/${claim.id}`).flush(claim);
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string, root: ParentNode = el()) =>
    root.querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  const button = (label: string, root: ParentNode = el()) =>
    Array.from(root.querySelectorAll('button')).find((b) => b.textContent!.includes(label)) as HTMLButtonElement;
  const bubbles = () => Array.from(el().querySelectorAll('app-chat-panel .bubble div')).map((b) => b.textContent);
  const chatStatus = () => text('app-chat-panel .status');
  const drawer = () => el().querySelector('app-receipt-drawer') as HTMLElement;

  async function settle() {
    await fixture.whenStable();
  }

  async function dropFiles(files: File[]) {
    const drop = new Event('drop', { bubbles: true, cancelable: true });
    Object.defineProperty(drop, 'dataTransfer', { value: { files } });
    el().querySelector('app-drop-zone .zone')!.dispatchEvent(drop);
    await settle();
  }

  async function sendChat(message: string) {
    const input = el().querySelector('app-chat-panel input[name=draft]') as HTMLInputElement;
    input.value = message;
    input.dispatchEvent(new Event('input'));
    await settle();
    (el().querySelector('app-chat-panel button.send') as HTMLButtonElement).click();
    await settle();
  }

  async function type(field: HTMLInputElement | HTMLTextAreaElement, value: string) {
    field.value = value;
    field.dispatchEvent(new Event('input'));
    await settle();
  }

  async function renameTo(title: string) {
    (el().querySelector('h1') as HTMLElement).click();
    await settle();
    const input = el().querySelector('.title-input') as HTMLInputElement;
    input.value = title;
    input.dispatchEvent(new Event('blur'));
    await settle();
  }

  describe('a new, unsaved claim', () => {
    it('starts locally with a personal welcome and nothing saved on the server', async () => {
      await renderNew();

      expect(text('h1')).toContain('New expense claim');
      expect(text('.unsaved')).toBe('● Not saved yet');
      expect(bubbles()[0]).toMatch(/^Hi Asha! .*I'm Rika\./);
      expect(button('Submit claim').disabled).toBe(true);
      expect(button('Delete draft')).toBeUndefined();
      expect(el().querySelectorAll('.tip')).toHaveLength(3);
      expect(text('.ring-title')).toBe("Let's get started");
    });

    it('creates the claim on the first upload, moves to its URL and uploads with progress', async () => {
      await renderNew();
      await dropFiles([pdf]);

      const create = http.expectOne(`${API}/claims`);
      expect(create.request.method).toBe('POST');
      expect(create.request.body).toEqual({}); // auto title and no remarks yet
      create.flush(makeClaim({ id: 'c-new', status: 'draft', title: 'New expense claim', title_is_auto: true }));
      expect(navigate).toHaveBeenCalledWith(['/agent', 'c-new'], { replaceUrl: true });

      const upload = http.expectOne(`${API}/claims/c-new/receipts`);
      expect((upload.request.body as FormData).getAll('files').map((f) => (f as File).name)).toEqual(['hotel.pdf']);
      upload.event({ type: HttpEventType.UploadProgress, loaded: 50, total: 100 });
      await settle();
      expect(text('app-drop-zone .progress span')).toBe('Uploading… 50%');

      upload.flush([makeReceipt({ claim_id: 'c-new', status: 'processing' })]);
      await settle();
      expect(el().querySelector('app-drop-zone .progress')).toBeNull();
    });

    it('does not re-fetch the claim it just created when the URL picks up the new id', async () => {
      await renderNew();
      await dropFiles([pdf]);
      http.expectOne(`${API}/claims`).flush(makeClaim({ id: 'c-new', status: 'draft' }));
      http.expectOne(`${API}/claims/c-new/receipts`).flush([]);

      // The router would now bind id="c-new" to the still-mounted workspace.
      fixture.componentRef.setInput('id', 'c-new');
      await settle();

      http.expectNone(`${API}/claims/c-new`);
    });

    it('falls back to a generic greeting when the user name is unknown', async () => {
      setup(undefined, false);
      await settle();
      expect(bubbles()[0]).toMatch(/^Hi there! /);
    });

    it('reports a failed upload and clears the progress bar', async () => {
      await renderNew();
      await dropFiles([pdf]);

      http.expectOne(`${API}/claims`).flush({ detail: 'Backend offline' }, { status: 503, statusText: 'Unavailable' });
      await settle();

      expect(toast.error).toHaveBeenCalledWith('Upload failed', 'Backend offline');
      expect(el().querySelector('app-drop-zone .progress')).toBeNull();
    });

    it('creates the claim on the first chat message and shows the message right away', async () => {
      await renderNew();
      await sendChat('Is the hotel within policy?');

      http.expectOne(`${API}/claims`).flush(makeClaim({ id: 'c-new', status: 'draft', messages: [] }));
      await settle();
      expect(bubbles()).toEqual(['Is the hotel within policy?']);
      expect(chatStatus()).toBe('Thinking…');

      const chat = http.expectOne(`${API}/claims/c-new/chat`);
      expect(chat.request.body).toEqual({ message: 'Is the hotel within policy?' });
      chat.flush(
        makeClaim({
          id: 'c-new',
          status: 'draft',
          messages: [
            { id: 'm-1', role: 'user', text: 'Is the hotel within policy?', created_at: new Date().toISOString(), meta: {} },
            { id: 'm-2', role: 'agent', text: 'Yes - it is under the **lodging limit**.', created_at: new Date().toISOString(), meta: {} },
          ],
        }),
      );
      await settle();

      expect(bubbles()).toEqual(['Is the hotel within policy?', 'Yes - it is under the lodging limit.']);
      expect(chatStatus()).toBe('Your reimbursement assistant');
    });

    it('renames the claim locally and sends the title when saved as a draft', async () => {
      await renderNew();
      await renameTo('  Goa offsite ');
      expect(text('h1')).toContain('Goa offsite');

      button('Save as draft').click();
      const create = http.expectOne(`${API}/claims`);
      expect(create.request.body).toEqual({ title: 'Goa offsite' });
      create.flush(makeClaim({ id: 'c-new', title: 'Goa offsite', status: 'draft' }));

      expect(toast.success).toHaveBeenCalledWith('Saved as draft', '“Goa offsite” is waiting for you under My claims.');
      expect(navigate).toHaveBeenCalledWith(['/claims']);
    });

    it('cancels renaming with Escape', async () => {
      await renderNew();
      (el().querySelector('h1') as HTMLElement).click();
      await settle();

      el().querySelector('.title-input')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      await settle();

      expect(el().querySelector('.title-input')).toBeNull();
      expect(text('h1')).toContain('New expense claim');
    });

    it('keeps remarks written by the user locally until the claim is saved', async () => {
      await renderNew();
      button('Write it yourself').click();
      await settle();

      (el().querySelector('.remarks textarea') as HTMLTextAreaElement).value = 'Client visit to Pune';
      (el().querySelector('.remarks-actions .btn-primary') as HTMLButtonElement).click();
      await settle();

      expect(text('.remarks-text')).toBe('Client visit to Pune');
      expect(text('.meta .purpose')).toBe('📝 Client visit to Pune');
    });

    it('reports when the draft cannot be saved', async () => {
      await renderNew();
      button('Save as draft').click();

      http.expectOne(`${API}/claims`).flush({ detail: 'Database locked' }, { status: 500, statusText: 'Server Error' });
      await settle();

      expect(toast.error).toHaveBeenCalledWith('Could not save draft', 'Database locked');
      expect(button('Save as draft').disabled).toBe(false);
    });

    it('warns when the offline engine is active', async () => {
      await renderNew(makePublicConfig({ llm_provider: 'mock' }));
      expect(text('.engine-warning')).toContain('Offline engine active.');
    });
  });

  describe('an existing claim', () => {
    const receipt = makeReceipt({ id: 'r-1', claim_id: 'c-1', file_name: 'uber.pdf' });
    const readyClaim = makeClaim({
      id: 'c-1',
      title: 'Mumbai client visit',
      status: 'ready',
      readiness: 100,
      purpose: 'Quarterly review',
      purpose_source: 'agent',
      receipts: [receipt],
      checklist: [
        { key: 'uploaded', label: 'Receipts uploaded', done: true },
        { key: 'purpose', label: 'Purpose / remarks added', done: false },
      ],
      groups: [{ category: 'travel', label: 'Travel', icon: '🚕', count: 1, total: 827 }],
    });

    it('shows the claim, its receipts and readiness', async () => {
      await renderExisting(readyClaim);

      expect(text('h1')).toContain('Mumbai client visit');
      expect(text('.meta app-status-pill')).toContain('Ready to submit');
      expect(text('.meta')).toContain('1 file');
      expect(el().querySelectorAll('app-receipt-card')).toHaveLength(1);
      expect(text('.ring-title')).toBe('All set! 🎉');
      expect(Array.from(el().querySelectorAll('.checklist li')).map((li) => li.classList.contains('done'))).toEqual([true, false]);
      expect(text('.group strong')).toBe('₹827.00');
      expect(text('.ai-tag')).toBe('✨ by Rika');
      expect(button('Submit claim').disabled).toBe(false);
      expect(button('Submit claim').classList).toContain('glow');
    });

    it('links exports and downloads with the access token', async () => {
      await renderExisting(readyClaim);

      const hrefs = Array.from(el().querySelectorAll('a[download]')).map((a) => a.getAttribute('href'));
      expect(hrefs).toContain(`${API}/claims/c-1/export?access_token=${TEST_TOKEN}`);
      expect(hrefs).toContain(`${API}/claims/c-1/attachments.zip?access_token=${TEST_TOKEN}`);
    });

    it('sends locked claims to the read-only detail view', async () => {
      await renderExisting(makeClaim({ id: 'c-1', status: 'submitted' }));

      expect(navigate).toHaveBeenCalledWith(['/claims', 'c-1'], { replaceUrl: true });
      expect(text('.center-state p')).toBe('Preparing your workspace…');
    });

    it('explains when the claim cannot be loaded', async () => {
      setup();
      fixture.componentRef.setInput('id', 'c-404');
      await settle();

      http.expectOne(`${API}/claims/c-404`).flush({ detail: 'Claim not found' }, { status: 404, statusText: 'Not Found' });
      await settle();

      expect(text('.center-state h2')).toBe('Claim not found');
    });

    it('applies live updates for this claim but ignores stale snapshots and other claims', async () => {
      await renderExisting(makeClaim({ id: 'c-1', title: 'Original', status: 'processing', updated_at: '2026-10-01T10:00:00Z' }));

      realtime.claimUpdates.next(makeClaim({ id: 'c-1', title: 'Fresh', status: 'ready', updated_at: '2026-10-01T10:05:00Z' }));
      await settle();
      expect(text('h1')).toContain('Fresh');

      realtime.claimUpdates.next(makeClaim({ id: 'c-1', title: 'Stale', updated_at: '2026-10-01T10:01:00Z' }));
      realtime.claimUpdates.next(makeClaim({ id: 'c-2', title: 'Other claim', updated_at: '2026-10-01T11:00:00Z' }));
      await settle();
      expect(text('h1')).toContain('Fresh');
    });

    it('counts receipts that are processing or need attention', async () => {
      await renderExisting(
        makeClaim({
          id: 'c-1',
          status: 'processing',
          receipts: [
            makeReceipt({ id: 'r-1', status: 'processing', stage: 'reading' }),
            makeReceipt({ id: 'r-2', status: 'needs_info' }),
            makeReceipt({ id: 'r-3', status: 'failed' }),
          ],
        }),
      );

      expect(text('.chip.brand')).toBe('1 processing');
      expect(text('.chip.warn')).toBe('⚠ 2 need attention');
      expect(chatStatus()).toBe('Reading 1 receipt…');
    });

    describe('answering agent questions', () => {
      const question = makeQuestion({
        id: 'q-1',
        type: 'choice',
        options: [
          { value: 'keep', label: 'Keep both' },
          { value: 'exclude', label: 'Remove' },
        ],
      });
      const needsAnswer = makeClaim({ id: 'c-1', status: 'needs_attention', questions: [question], updated_at: '2026-10-01T10:00:00Z' });

      it('posts the answer and applies the updated claim', async () => {
        await renderExisting(needsAnswer);
        (el().querySelector('app-question-card .choices button') as HTMLButtonElement).click();
        await settle();

        const req = http.expectOne(`${API}/claims/c-1/questions/q-1/answer`);
        expect(req.request.body).toEqual({ answer: 'keep' });
        expect(el().querySelector('app-question-card .q')!.classList).toContain('busy');

        req.flush(makeClaim({ id: 'c-1', status: 'ready', questions: [], updated_at: '2026-10-01T10:01:00Z' }));
        await settle();

        expect(el().querySelector('app-question-card')).toBeNull();
        expect(text('.meta app-status-pill')).toContain('Ready to submit');
      });

      it('reports a rejected answer', async () => {
        await renderExisting(needsAnswer);
        (el().querySelector('app-question-card .choices button') as HTMLButtonElement).click();

        http
          .expectOne(`${API}/claims/c-1/questions/q-1/answer`)
          .flush({ detail: 'This question was already answered' }, { status: 400, statusText: 'Bad Request' });
        await settle();

        expect(toast.error).toHaveBeenCalledWith("Couldn't use that answer", 'This question was already answered');
        expect(el().querySelector('app-question-card .q')!.classList).not.toContain('busy');
      });
    });

    it('reports when the agent cannot answer a chat message', async () => {
      await renderExisting(readyClaim);
      await sendChat('Hello?');

      http.expectOne(`${API}/claims/c-1/chat`).flush(null, { status: 502, statusText: 'Bad Gateway' });
      await settle();

      expect(toast.error).toHaveBeenCalledWith('Agent unavailable', 'Something went wrong');
      expect(chatStatus()).toBe('Your reimbursement assistant');
    });

    it('uploads more receipts straight to the existing claim', async () => {
      await renderExisting(readyClaim);
      await dropFiles([pdf]);

      http.expectOne(`${API}/claims/c-1/receipts`).flush([makeReceipt()]);
    });

    describe('the receipt drawer', () => {
      async function openDrawer() {
        await renderExisting(readyClaim);
        (el().querySelector('app-receipt-card article') as HTMLElement).click();
        await settle();
      }

      it('opens the selected receipt', async () => {
        await openDrawer();
        expect(text('h3', drawer())).toBe('Uber');
      });

      it('saves edits and confirms', async () => {
        await openDrawer();
        await type(drawer().querySelector('[name=vendor]') as HTMLInputElement, 'Uber India');
        button('Save changes', drawer()).click();

        const req = http.expectOne(`${API}/claims/c-1/receipts/r-1`);
        expect(req.request.method).toBe('PATCH');
        expect(req.request.body).toEqual({ vendor: 'Uber India' });
        req.flush({ ...readyClaim, updated_at: '2026-10-02T00:00:00Z' });

        expect(toast.success).toHaveBeenCalledWith('Receipt updated');
      });

      it('reports a failed save', async () => {
        await openDrawer();
        await type(drawer().querySelector('[name=vendor]') as HTMLInputElement, 'Uber India');
        button('Save changes', drawer()).click();

        http.expectOne(`${API}/claims/c-1/receipts/r-1`).flush({ detail: 'Invalid date' }, { status: 422, statusText: 'Unprocessable' });

        expect(toast.error).toHaveBeenCalledWith('Update failed', 'Invalid date');
      });

      it('deletes the receipt and closes the drawer', async () => {
        await openDrawer();
        button('Delete', drawer()).click();
        await settle();
        button('Yes, delete', drawer()).click();
        await settle();

        expect(drawer()).toBeNull();
        const req = http.expectOne(`${API}/claims/c-1/receipts/r-1`);
        expect(req.request.method).toBe('DELETE');
        req.flush({ ...readyClaim, receipts: [], updated_at: '2026-10-02T00:00:00Z' });
        await settle();

        expect(el().querySelectorAll('app-receipt-card')).toHaveLength(0);
      });

      it('asks the agent to read the receipt again', async () => {
        await openDrawer();
        button('Re-read', drawer()).click();

        const req = http.expectOne(`${API}/claims/c-1/receipts/r-1/retry`);
        expect(req.request.method).toBe('POST');
        req.flush(readyClaim);
      });

      it('reports failed deletes and retries', async () => {
        await openDrawer();
        button('Re-read', drawer()).click();
        http.expectOne(`${API}/claims/c-1/receipts/r-1/retry`).flush(null, { status: 500, statusText: 'Error' });
        expect(toast.error).toHaveBeenCalledWith('Retry failed', 'Something went wrong');

        button('Delete', drawer()).click();
        await settle();
        button('Yes, delete', drawer()).click();
        http.expectOne(`${API}/claims/c-1/receipts/r-1`).flush(null, { status: 500, statusText: 'Error' });
        expect(toast.error).toHaveBeenCalledWith('Delete failed', 'Something went wrong');
      });

      it('hands over to the full-screen viewer', async () => {
        await openDrawer();
        button('View full size', drawer()).click();
        await settle();

        expect(drawer()).toBeNull();
        expect(text('app-attachment-viewer .title strong')).toBe('uber.pdf');
      });
    });

    it('opens the document viewer from a receipt card', async () => {
      await renderExisting(readyClaim);
      (el().querySelector('app-receipt-card button.doc-btn') as HTMLButtonElement).click();
      await settle();

      expect(text('app-attachment-viewer .title strong')).toBe('uber.pdf');
      expect(drawer()).toBeNull();
    });

    describe('renaming', () => {
      it('saves a new title through the API', async () => {
        await renderExisting(readyClaim);
        await renameTo('Mumbai Q4 review');

        const req = http.expectOne(`${API}/claims/c-1`);
        expect(req.request.method).toBe('PATCH');
        expect(req.request.body).toEqual({ title: 'Mumbai Q4 review' });
        req.flush({ ...readyClaim, title: 'Mumbai Q4 review', updated_at: '2026-10-02T00:00:00Z' });
        await settle();

        expect(text('h1')).toContain('Mumbai Q4 review');
      });

      it.each([['an unchanged title', 'Mumbai client visit'], ['a blank title', '   ']])('ignores %s', async (_, title) => {
        await renderExisting(readyClaim);
        await renameTo(title);

        http.expectNone(`${API}/claims/c-1`);
        expect(text('h1')).toContain('Mumbai client visit');
      });
    });

    describe('remarks', () => {
      async function editRemarks(value: string) {
        button('Edit remarks').click();
        await settle();
        const textarea = el().querySelector('.remarks textarea') as HTMLTextAreaElement;
        expect(textarea.value).toBe('Quarterly review');
        textarea.value = value;
        (el().querySelector('.remarks-actions .btn-primary') as HTMLButtonElement).click();
        await settle();
      }

      it('saves edited remarks through the API', async () => {
        await renderExisting(readyClaim);
        await editRemarks('Quarterly business review with Acme');

        const req = http.expectOne(`${API}/claims/c-1`);
        expect(req.request.body).toEqual({ purpose: 'Quarterly business review with Acme' });
        expect((el().querySelector('.remarks-actions .btn-primary') as HTMLButtonElement).disabled).toBe(true);
        req.flush({ ...readyClaim, purpose: 'Quarterly business review with Acme', purpose_source: 'user', updated_at: '2026-10-02T00:00:00Z' });
        await settle();

        expect(toast.success).toHaveBeenCalledWith('Remarks updated');
        expect(text('.remarks-text')).toBe('Quarterly business review with Acme');
        expect(el().querySelector('.ai-tag')).toBeNull();
      });

      it('just closes the editor when nothing changed', async () => {
        await renderExisting(readyClaim);
        await editRemarks('  Quarterly review  ');

        http.expectNone(`${API}/claims/c-1`);
        expect(el().querySelector('.remarks textarea')).toBeNull();
      });

      it('keeps the editor open and reports a failed save', async () => {
        await renderExisting(readyClaim);
        await editRemarks('New remarks');

        http.expectOne(`${API}/claims/c-1`).flush({ detail: 'Too long' }, { status: 422, statusText: 'Unprocessable' });
        await settle();

        expect(toast.error).toHaveBeenCalledWith('Could not save remarks', 'Too long');
        expect(el().querySelector('.remarks textarea')).not.toBeNull();
      });

      it('shows a spinner while the agent infers the purpose', async () => {
        await renderExisting({ ...readyClaim, purpose: null, purpose_inferring: true });
        expect(text('.inferring')).toBe('Working out what these expenses were for…');
      });
    });

    describe('deleting the draft', () => {
      async function confirmDelete() {
        button('Delete draft').click();
        await settle();
        expect(text('.confirm-delete span')).toBe('Delete this claim and its 1 receipt(s)?');
        button('Delete', el().querySelector('.confirm-delete')!).click();
      }

      it('deletes after confirmation and returns to the claims list', async () => {
        await renderExisting(readyClaim);
        await confirmDelete();

        const req = http.expectOne(`${API}/claims/c-1`);
        expect(req.request.method).toBe('DELETE');
        req.flush(null);

        expect(toast.success).toHaveBeenCalledWith('Claim deleted', '“Mumbai client visit” and its receipts were removed.');
        expect(navigate).toHaveBeenCalledWith(['/claims']);
      });

      it('can be cancelled', async () => {
        await renderExisting(readyClaim);
        button('Delete draft').click();
        await settle();

        button('Cancel', el().querySelector('.confirm-delete')!).click();
        await settle();

        expect(el().querySelector('.confirm-delete')).toBeNull();
      });

      it('reports a failed delete', async () => {
        await renderExisting(readyClaim);
        await confirmDelete();

        http.expectOne(`${API}/claims/c-1`).flush({ detail: 'Locked' }, { status: 409, statusText: 'Conflict' });
        await settle();

        expect(toast.error).toHaveBeenCalledWith('Could not delete claim', 'Locked');
        expect(el().querySelector('.confirm-delete')).toBeNull();
      });
    });

    it('saves an existing draft without creating a new claim', async () => {
      await renderExisting(readyClaim);
      button('Save as draft').click();

      expect(toast.success).toHaveBeenCalledWith('Saved as draft', '“Mumbai client visit” is waiting for you under My claims.');
      expect(navigate).toHaveBeenCalledWith(['/claims']);
    });

    it('submits through the dialog and locks the workspace afterwards', async () => {
      await renderExisting(readyClaim);
      button('Submit claim').click();
      await settle();

      const dialog = el().querySelector('app-submit-dialog')!;
      (dialog.querySelector('input[type=checkbox]') as HTMLInputElement).click();
      await settle();
      button('Submit claim', dialog).click();
      http
        .expectOne(`${API}/claims/c-1/submit`)
        .flush({ ...readyClaim, status: 'submitted', reference_no: 'EXP-2026-0042', updated_at: '2026-10-02T00:00:00Z' });
      await settle();

      expect(text('.ref', dialog)).toBe('EXP-2026-0042');
      expect(text('.meta app-status-pill')).toContain('Awaiting approval');
      expect(button('Save as draft')).toBeUndefined();
      expect((el().querySelector('app-chat-panel input[name=draft]') as HTMLInputElement).placeholder).toBe('This claim is locked');

      button('Start another claim', dialog).click();
      await settle();
      expect(el().querySelector('app-submit-dialog')).toBeNull();
      expect(navigate).toHaveBeenCalledWith(['/agent']);
    });

    it('keeps Submit disabled until the claim is ready', async () => {
      await renderExisting({ ...readyClaim, status: 'needs_attention' });
      expect(button('Submit claim').disabled).toBe(true);
    });
  });
});
