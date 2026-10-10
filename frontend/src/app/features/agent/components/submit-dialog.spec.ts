import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { makeClaim } from '@testing/fixtures';
import type { MockInstance } from 'vitest';

import { Claim } from '../../../core/models/models';
import { SubmitDialog } from './submit-dialog';

const SUBMIT_URL = 'http://localhost:8100/api/claims/c-1/submit';

describe('SubmitDialog', () => {
  let fixture: ComponentFixture<SubmitDialog>;
  let http: HttpTestingController;
  let navigate: MockInstance<Router['navigate']>;
  let closed: number;
  let submitted: Claim[];

  const claim = makeClaim({
    id: 'c-1',
    title: 'Mumbai client visit',
    purpose: 'Quarterly review with Acme',
    currency: 'INR',
    total_claimed: 10_000,
    total_reimbursable: 9_200,
    groups: [
      { category: 'travel', label: 'Travel', icon: '🚕', count: 3, total: 2_500 },
      { category: 'lodging', label: 'Lodging', icon: '🏨', count: 1, total: 7_500 },
    ],
  });

  async function render(input: Claim = claim) {
    TestBed.configureTestingModule({
      providers: [provideZonelessChangeDetection(), provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    navigate = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);

    fixture = TestBed.createComponent(SubmitDialog);
    fixture.componentRef.setInput('claim', input);
    closed = 0;
    submitted = [];
    fixture.componentInstance.closed.subscribe(() => closed++);
    fixture.componentInstance.submitted.subscribe((c) => submitted.push(c));
    await fixture.whenStable();
  }

  afterEach(() => http.verify());

  const el = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => el().querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  const button = (label: string) =>
    Array.from(el().querySelectorAll('button')).find((b) => b.textContent!.includes(label)) as HTMLButtonElement;
  const submitButton = () => button('Submit');

  async function agreeAndSubmit() {
    (el().querySelector('input[type=checkbox]') as HTMLInputElement).click();
    await fixture.whenStable();
    submitButton().click();
    await fixture.whenStable();
  }

  describe('review step', () => {
    it('summarises the claim: title, remarks, category lines and payout', async () => {
      await render();

      expect(text('h2')).toBe('Ready to submit?');
      expect(text('.muted')).toBe('Mumbai client visit');
      expect(text('.remarks')).toBe('Remarks: Quarterly review with Acme');
      const lines = Array.from(el().querySelectorAll('.summary .line')).map((line) =>
        Array.from(line.querySelectorAll(':scope > span'))
          .map((span) => span.textContent!.replace(/\s+/g, ' ').trim())
          .join(' | '),
      );
      expect(lines).toEqual([
        '🚕 Travel ×3 | ₹2,500.00',
        '🏨 Lodging ×1 | ₹7,500.00',
        'Policy adjustments | −₹800.00',
        "You'll be reimbursed | ₹9,200.00",
      ]);
    });

    it('omits remarks and policy adjustments when there are none', async () => {
      await render(makeClaim({ purpose: null, total_claimed: 500, total_reimbursable: 500, groups: [] }));

      expect(el().querySelector('.remarks')).toBeNull();
      expect(el().querySelector('.line.adj')).toBeNull();
    });

    it('requires the declaration before the claim can be submitted', async () => {
      await render();
      expect(submitButton().disabled).toBe(true);

      (el().querySelector('input[type=checkbox]') as HTMLInputElement).click();
      await fixture.whenStable();

      expect(submitButton().disabled).toBe(false);
    });

    it.each([
      ['the "Not yet" button', () => button('Not yet').click()],
      ['a click on the backdrop', () => (el().querySelector('.overlay') as HTMLElement).click()],
      ['the Escape key', () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
    ])('closes on %s', async (_, close) => {
      await render();
      close();
      expect(closed).toBe(1);
    });

    it('stays open when clicking inside the dialog', async () => {
      await render();
      (el().querySelector('.dialog') as HTMLElement).click();
      expect(closed).toBe(0);
    });
  });

  describe('submitting', () => {
    it('submits the claim and blocks closing until the server answers', async () => {
      await render();
      await agreeAndSubmit();

      const req = http.expectOne(SUBMIT_URL);
      expect(req.request.method).toBe('POST');
      expect(submitButton().textContent).toContain('Submitting…');
      expect(submitButton().disabled).toBe(true);
      expect(button('Not yet').disabled).toBe(true);

      (el().querySelector('.overlay') as HTMLElement).click();
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(closed).toBe(0);

      req.flush(makeClaim({ id: 'c-1', status: 'submitted', reference_no: 'EXP-2026-0042' }));
    });

    it('celebrates with the reference number and reports the submitted claim', async () => {
      await render();
      await agreeAndSubmit();

      const result = makeClaim({ id: 'c-1', status: 'submitted', reference_no: 'EXP-2026-0042' });
      http.expectOne(SUBMIT_URL).flush(result);
      await fixture.whenStable();

      expect(text('h2')).toBe('Claim submitted!');
      expect(text('.ref')).toBe('EXP-2026-0042');
      expect(el().querySelector('app-confetti')).not.toBeNull();
      expect(submitted).toEqual([result]);
    });

    it('shows the API error and lets the user try again', async () => {
      await render();
      await agreeAndSubmit();

      http
        .expectOne(SUBMIT_URL)
        .flush({ detail: 'Answer the pending questions first' }, { status: 409, statusText: 'Conflict' });
      await fixture.whenStable();

      expect(text('.error')).toBe('⛔ Answer the pending questions first');
      expect(text('h2')).toBe('Ready to submit?');
      expect(submitButton().disabled).toBe(false);
      expect(submitted).toEqual([]);
    });

    it('uses a generic message when the error has no detail', async () => {
      await render();
      await agreeAndSubmit();

      http.expectOne(SUBMIT_URL).flush(null, { status: 500, statusText: 'Server Error' });
      await fixture.whenStable();

      expect(text('.error')).toBe('⛔ Submission failed');
    });
  });

  describe('after submission', () => {
    beforeEach(async () => {
      await render();
      await agreeAndSubmit();
      http.expectOne(SUBMIT_URL).flush(makeClaim({ id: 'c-1', status: 'submitted', reference_no: 'EXP-1' }));
      await fixture.whenStable();
    });

    it('can take the user to the submitted claim', () => {
      button('Track this claim').click();

      expect(closed).toBe(1);
      expect(navigate).toHaveBeenCalledWith(['/claims', 'c-1']);
    });

    it('can start another claim', () => {
      button('Start another claim').click();

      expect(closed).toBe(1);
      expect(navigate).toHaveBeenCalledWith(['/agent']);
    });

    it('no longer closes on Escape', () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
      expect(closed).toBe(0);
    });
  });
});
