import { provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { makePublicConfig, makeReceipt } from '@testing/fixtures';

import { PolicyStore } from '../../../core/config/policy.store';
import { Receipt, ReceiptUpdate } from '../../../core/models/models';
import { ReceiptDrawer } from './receipt-drawer';

describe('ReceiptDrawer', () => {
  let fixture: ComponentFixture<ReceiptDrawer>;
  let saved: ReceiptUpdate[];
  const events = { closed: vi.fn(), removed: vi.fn(), retried: vi.fn(), viewed: vi.fn() };

  async function render(receipt: Receipt = makeReceipt(), inputs: { editable?: boolean } = {}) {
    const config = makePublicConfig();
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        { provide: PolicyStore, useValue: { config: signal(config), categories: signal(config.categories) } },
      ],
    });
    Object.values(events).forEach((fn) => fn.mockReset());
    fixture = TestBed.createComponent(ReceiptDrawer);
    fixture.componentRef.setInput('receipt', receipt);
    fixture.componentRef.setInput('fileUrl', '/files/r-1');
    fixture.componentRef.setInput('downloadUrl', '/files/r-1?download=true');
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    saved = [];
    const component = fixture.componentInstance;
    component.save.subscribe((update) => saved.push(update));
    component.closed.subscribe(events.closed);
    component.remove.subscribe(events.removed);
    component.retry.subscribe(events.retried);
    component.view.subscribe(events.viewed);
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => el().querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim();
  const field = <T extends HTMLElement = HTMLInputElement>(name: string) =>
    el().querySelector(`[name="${name}"]`) as unknown as T;
  /** Inputs rendered in a loop bind `name` to NgModel only, so find them by their visible label. */
  const fieldByLabel = (label: string) =>
    Array.from(el().querySelectorAll('.field'))
      .find((f) => f.querySelector('label')!.textContent!.trim() === label)!
      .querySelector('input') as HTMLInputElement;
  const button = (label: string) =>
    Array.from(el().querySelectorAll('button')).find((b) => b.textContent!.includes(label)) as HTMLButtonElement;
  const saveButton = () => button('Save changes');

  async function edit(nameOrInput: string | HTMLInputElement, value: string) {
    const input = typeof nameOrInput === 'string' ? field(nameOrInput) : nameOrInput;
    input.value = value;
    input.dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  async function choose(name: string, optionText: string) {
    const select = field<HTMLSelectElement>(name);
    select.selectedIndex = Array.from(select.options).findIndex((o) => o.textContent!.includes(optionText));
    select.dispatchEvent(new Event('change'));
    await fixture.whenStable();
  }

  describe('header and document', () => {
    it('names the receipt and shows the file details', async () => {
      await render(makeReceipt({ size_bytes: 51_200 }));

      expect(text('h3')).toBe('Uber');
      expect(text('.sub .subtle')).toBe('uber.pdf · 50 KB');
      expect(text('app-status-pill')).toContain('Complete');
    });

    it('shows the merchant as printed and the detected language for regional bills', async () => {
      await render(makeReceipt({ data: { vendor: 'Sharma Sweets', vendor_local: 'शर्मा स्वीट्स', language: 'hi' } }));

      expect(text('.printed')).toContain('As printed:');
      expect(text('.printed strong')).toBe('शर्मा स्वीट्स');
      expect(text('.printed .lang')).toBe('🌐 hi');
    });

    it('omits the "as printed" line for plain English receipts', async () => {
      await render(makeReceipt({ data: { vendor_local: null, language: null } }));
      expect(el().querySelector('.printed')).toBeNull();
    });

    it('previews PDFs in a frame and images inline', async () => {
      await render(makeReceipt({ mime_type: 'application/pdf' }));
      expect(el().querySelector('iframe')!.getAttribute('src')).toBe('/files/r-1');

      fixture.componentRef.setInput('receipt', makeReceipt({ mime_type: 'image/png', file_name: 'bill.png' }));
      await fixture.whenStable();

      expect(el().querySelector('.preview img')!.getAttribute('src')).toBe('/files/r-1');
      expect(el().querySelector('iframe')).toBeNull();
    });

    it('links to the full-size viewer, the download and a new tab', async () => {
      await render();

      button('View full size').click();
      expect(events.viewed).toHaveBeenCalledTimes(1);
      const [download, newTab] = Array.from(el().querySelectorAll('.doc-bar a'));
      expect(download.getAttribute('href')).toBe('/files/r-1?download=true');
      expect(newTab.getAttribute('href')).toBe('/files/r-1');
      expect(newTab.getAttribute('target')).toBe('_blank');
    });

    it('lists policy flags and processing errors', async () => {
      await render(
        makeReceipt({
          error: 'Low quality scan',
          flags: [
            { code: 'limit', severity: 'error', message: 'Over the limit' },
            { code: 'old', severity: 'warning', message: 'Older than 90 days' },
            { code: 'fx', severity: 'info', message: 'Converted from USD' },
          ],
        }),
      );

      const flags = Array.from(el().querySelectorAll('.flags .flag')).map((f) => f.textContent!.trim());
      expect(flags).toEqual(['⛔ Low quality scan', '⛔ Over the limit', '⚠️ Older than 90 days', 'ℹ️ Converted from USD']);
    });

    it('shows claimed vs reimbursable amounts', async () => {
      await render(makeReceipt({ amount_in_base: 9_000, reimbursable_amount: 8_000 }));

      const [claimed, reimbursable] = Array.from(el().querySelectorAll('.amount-box strong')).map((s) => s.textContent);
      expect(claimed).toBe('₹9,000.00');
      expect(reimbursable).toBe('₹8,000.00');
    });

    it('shows line items and who read the document', async () => {
      await render(
        makeReceipt({
          data: {
            line_items: [
              { description: 'Paneer tikka', amount: 450, quantity: 2, unit_price: 225 },
              { description: 'Service charge', amount: 50, quantity: null, unit_price: null },
            ],
          },
          extraction_source: 'claude',
          extraction_notes: 'Verified twice',
        }),
      );

      const lines = Array.from(el().querySelectorAll('.lines .line')).map((line) =>
        Array.from(line.querySelectorAll(':scope > span'))
          .map((span) => span.textContent!.replace(/\s+/g, ' ').trim())
          .join(' | '),
      );
      expect(lines).toEqual(['Paneer tikka 2 × ₹225.00 | ₹450.00', 'Service charge | ₹50.00']);
      expect(text('.source')).toBe('Read by claude · Verified twice');
    });
  });

  describe('editing extracted details', () => {
    it('seeds the form from the receipt', async () => {
      await render();

      expect(field('vendor').value).toBe('Uber');
      expect(field('total_amount').value).toBe('827');
      expect(fieldByLabel('City').value).toBe('Mumbai');
      expect(fieldByLabel('Invoice #').value).toBe('INV-42');
      expect(field<HTMLSelectElement>('category').selectedOptions[0].textContent).toContain('Travel');
    });

    it('keeps Save disabled until something changes', async () => {
      await render();
      expect(saveButton().disabled).toBe(true);

      await edit('vendor', 'Uber India');

      expect(saveButton().disabled).toBe(false);
    });

    it('sends only the fields the user changed', async () => {
      await render();
      await edit('vendor', 'Uber India');
      await edit('total_amount', '900');
      await choose('category', 'Meals');

      saveButton().click();

      expect(saved).toEqual([{ vendor: 'Uber India', total_amount: 900, category: 'meals' }]);
    });

    it('treats a value changed back to the original as unchanged', async () => {
      await render();
      await edit('vendor', 'Something else');
      await edit('vendor', 'Uber');

      expect(saveButton().disabled).toBe(true);
    });

    it('ignores fields that were cleared (only non-empty changes are sent)', async () => {
      await render();
      await edit(fieldByLabel('Invoice #'), '');

      expect(saveButton().disabled).toBe(true);
      el().querySelector('form')!.dispatchEvent(new Event('submit'));
      expect(saved).toEqual([]);
    });

    it('can add a justification for the approver', async () => {
      await render();
      await edit('justification', 'Only hotel near the client site');

      saveButton().click();

      expect(saved).toEqual([{ justification: 'Only hotel near the client site' }]);
    });

    it('offers the policy currencies and categories', async () => {
      await render();

      const currencies = Array.from(field<HTMLSelectElement>('currency').options).map((o) => o.textContent!.trim());
      const categories = Array.from(field<HTMLSelectElement>('category').options).map((o) => o.textContent!.trim());
      expect(currencies).toEqual(['Select', 'INR', 'USD']);
      expect(categories).toEqual(['Select', '🚕 Travel', '🍽️ Meals', '🏨 Lodging']);
    });

    it('marks a business purpose copied from the claim remarks', async () => {
      await render(makeReceipt({ purpose_inherited: true }));
      expect(text('.inherited')).toBe('from claim remarks');
    });

    it('shows AI confidence per field, flagging low confidence', async () => {
      await render(makeReceipt({ confidence: { vendor: 0.97, total_amount: 0.42 } }));

      const bars = Array.from(el().querySelectorAll<HTMLElement>('.conf'));
      expect(bars.map((b) => b.title)).toEqual(['AI confidence 97%', 'AI confidence 42%']);
      expect(bars.map((b) => b.classList.contains('low'))).toEqual([false, true]);
      expect(bars[0].querySelector('i')!.style.width).toBe('97%');
    });

    it('re-seeds the form when a different receipt is opened', async () => {
      await render();
      await edit('vendor', 'Unsaved edit');

      fixture.componentRef.setInput('receipt', makeReceipt({ id: 'r-2', data: { vendor: 'IndiGo' } }));
      await fixture.whenStable();

      expect(field('vendor').value).toBe('IndiGo');
      expect(saveButton().disabled).toBe(true);
    });
  });

  describe('actions', () => {
    it('asks for confirmation before deleting', async () => {
      await render();

      button('Delete').click();
      await fixture.whenStable();
      expect(text('.confirm')).toBe('Delete this receipt?');
      expect(events.removed).not.toHaveBeenCalled();

      button('Yes, delete').click();
      expect(events.removed).toHaveBeenCalledTimes(1);
    });

    it('can cancel the delete confirmation', async () => {
      await render();
      button('Delete').click();
      await fixture.whenStable();

      button('Cancel').click();
      await fixture.whenStable();

      expect(el().querySelector('.confirm')).toBeNull();
      expect(button('Save changes')).toBeDefined();
    });

    it('toggles exclusion from the claim', async () => {
      await render(makeReceipt({ excluded: false }));
      button('Exclude').click();
      expect(saved).toEqual([{ excluded: true }]);

      fixture.componentRef.setInput('receipt', makeReceipt({ excluded: true }));
      await fixture.whenStable();
      button('Include').click();

      expect(saved).toEqual([{ excluded: true }, { excluded: false }]);
    });

    it('offers "Retry" for failed receipts and "Re-read" otherwise', async () => {
      await render(makeReceipt({ status: 'failed' }));
      button('Retry').click();
      expect(events.retried).toHaveBeenCalledTimes(1);

      fixture.componentRef.setInput('receipt', makeReceipt({ status: 'complete' }));
      await fixture.whenStable();

      expect(button('Retry')).toBeUndefined();
      expect(button('Re-read').disabled).toBe(false);
    });

    it.each([
      ['the close button', () => (el().querySelector('[aria-label=Close]') as HTMLElement).click()],
      ['the backdrop', () => (el().querySelector('.backdrop') as HTMLElement).click()],
      ['Escape', () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
    ])('closes via %s', async (_, close) => {
      await render();
      close();
      expect(events.closed).toHaveBeenCalledTimes(1);
    });
  });

  describe('read-only states', () => {
    it('locks the form and hides actions on a submitted claim', async () => {
      await render(makeReceipt(), { editable: false });

      expect(el().querySelector('fieldset')!.disabled).toBe(true);
      expect(el().querySelector('footer')).toBeNull();
    });

    it('locks the form and the re-read button while the receipt is processing', async () => {
      await render(makeReceipt({ status: 'processing', stage: 'extracting' }));

      expect(el().querySelector('fieldset')!.disabled).toBe(true);
      expect(button('Re-read').disabled).toBe(true);
    });
  });
});
