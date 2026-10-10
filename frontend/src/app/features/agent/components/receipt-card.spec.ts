import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { makeCategory, makeReceipt } from '@testing/fixtures';

import { CategoryRule, Receipt } from '../../../core/models/models';
import { ReceiptCard } from './receipt-card';

describe('ReceiptCard', () => {
  let fixture: ComponentFixture<ReceiptCard>;
  const opened = vi.fn();
  const viewed = vi.fn();

  beforeEach(() => {
    opened.mockReset();
    viewed.mockReset();
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(receipt: Receipt, category?: CategoryRule, currency = 'INR') {
    fixture = TestBed.createComponent(ReceiptCard);
    fixture.componentRef.setInput('receipt', receipt);
    fixture.componentRef.setInput('fileUrl', '/files/r-1');
    fixture.componentRef.setInput('downloadUrl', '/files/r-1?download=true');
    fixture.componentRef.setInput('category', category);
    fixture.componentRef.setInput('currency', currency);
    fixture.componentInstance.open.subscribe(opened);
    fixture.componentInstance.view.subscribe(viewed);
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const text = (selector: string) => el().querySelector(selector)?.textContent?.trim().replace(/\s+/g, ' ');
  const card = () => el().querySelector('article') as HTMLElement;

  describe('while the agent is processing it', () => {
    const processing = makeReceipt({ status: 'processing', stage: 'categorising', progress: 60 });

    it('shows a scanning overlay with the current pipeline stage', async () => {
      await render(processing);

      expect(el().querySelector('.thumb')!.classList).toContain('scanning');
      expect(text('.scan-label')).toBe('Categorising…');
    });

    it('marks finished, current and upcoming pipeline steps', async () => {
      await render(processing);

      const steps = Array.from(el().querySelectorAll('.pipeline .step'));
      expect(steps).toHaveLength(8);
      expect(steps.filter((s) => s.classList.contains('done'))).toHaveLength(4);
      expect(steps.findIndex((s) => s.classList.contains('now'))).toBe(4);
    });

    it('shows upload progress and the file name instead of extracted details', async () => {
      await render(processing);

      expect((el().querySelector('.progress .bar') as HTMLElement).style.width).toBe('60%');
      expect(text('.file')).toBe('uber.pdf');
      expect(el().querySelector('.amount')).toBeNull();
    });

    it('labels a failed stage as "Failed"', async () => {
      await render(makeReceipt({ status: 'processing', stage: 'failed' }));

      expect(text('.scan-label')).toBe('Failed…');
      expect(el().querySelectorAll('.pipeline .step.done')).toHaveLength(0);
    });
  });

  describe('once processed', () => {
    it('shows merchant, category, date and amount', async () => {
      await render(makeReceipt(), makeCategory({ label: 'Travel', icon: '🚕' }));

      expect(text('.vendor strong')).toBe('Uber');
      expect(text('.vendor small')).toBe('Travel · 01 Oct 2026');
      expect(text('.cat-icon')).toBe('🚕');
      expect(text('.amount strong')).toBe('₹827.00');
      expect(el().querySelector('.thumb')!.classList).not.toContain('scanning');
    });

    it('falls back to the file name, "Uncategorised" and "no date" when details are missing', async () => {
      await render(makeReceipt({ data: { vendor: null, date: null } }));

      expect(text('.vendor strong')).toBe('uber.pdf');
      expect(text('.vendor small')).toBe('Uncategorised · no date');
      expect(text('.cat-icon')).toBe('🧾');
    });

    it('asks for the amount when it could not be read', async () => {
      await render(makeReceipt({ data: { total_amount: null } }));
      expect(text('.amount .missing')).toBe('Amount needed');
    });

    it('shows foreign-currency amounts with the converted base amount', async () => {
      await render(makeReceipt({ data: { total_amount: 120, currency: 'USD' }, amount_in_base: 10_020 }));

      expect(text('.amount strong')).toBe('$120.00');
      expect(text('.amount small')).toBe('≈ ₹10,020.00');
    });

    it('does not show a conversion for base-currency receipts', async () => {
      await render(makeReceipt());
      expect(el().querySelector('.amount small')).toBeNull();
    });

    it('flags a reimbursement capped by policy', async () => {
      await render(makeReceipt({ amount_in_base: 9000, reimbursable_amount: 8000 }));
      expect(text('.capped')).toBe('pays ₹8,000.00');
    });

    it('does not flag an uncapped receipt', async () => {
      await render(makeReceipt({ amount_in_base: 9000, reimbursable_amount: 9000 }));
      expect(el().querySelector('.capped')).toBeNull();
    });

    it('shows the error for a failed receipt', async () => {
      await render(makeReceipt({ status: 'failed', error: 'Could not read the document' }));

      expect(card().classList).toContain('failed');
      expect(text('.error')).toBe('⛔ Could not read the document');
    });

    it('shows at most two warning/error flags, skipping informational ones', async () => {
      await render(
        makeReceipt({
          status: 'questionable',
          flags: [
            { code: 'converted', severity: 'info', message: 'Converted from USD' },
            { code: 'old', severity: 'warning', message: 'Older than 90 days' },
            { code: 'limit', severity: 'error', message: 'Over the meal limit' },
            { code: 'weekend', severity: 'warning', message: 'Weekend expense' },
          ],
        }),
      );

      const flags = Array.from(el().querySelectorAll('.flag')).map((f) => f.textContent!.trim());
      expect(flags).toEqual(['Older than 90 days', 'Over the meal limit']);
      expect(card().classList).toContain('attention');
    });

    it('lists missing fields when there are no flags', async () => {
      await render(makeReceipt({ status: 'needs_info', missing_fields: ['date', 'business_purpose'] }));
      expect(text('.flag.warning')).toBe('Missing: date, business_purpose');
    });

    it('dims excluded receipts', async () => {
      await render(makeReceipt({ excluded: true, status: 'excluded' }));
      expect(card().classList).toContain('excluded');
    });
  });

  describe('thumbnail', () => {
    it('previews images', async () => {
      await render(makeReceipt({ mime_type: 'image/jpeg', file_name: 'cafe.jpg' }));

      const img = el().querySelector('.thumb img') as HTMLImageElement;
      expect(img.getAttribute('src')).toBe('/files/r-1');
      expect(img.alt).toBe('cafe.jpg');
    });

    it('shows a PDF badge for documents', async () => {
      await render(makeReceipt({ mime_type: 'application/pdf' }));

      expect(el().querySelector('.thumb img')).toBeNull();
      expect(text('.pdf')).toBe('PDF');
    });
  });

  describe('interactions', () => {
    beforeEach(async () => render(makeReceipt()));

    it('opens the receipt when the card is clicked', () => {
      card().click();
      expect(opened).toHaveBeenCalledTimes(1);
    });

    it('opens the receipt with the Enter key', () => {
      card().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));
      expect(opened).toHaveBeenCalledTimes(1);
    });

    it('views the original document without opening the editor', () => {
      (el().querySelector('button.doc-btn') as HTMLButtonElement).click();

      expect(viewed).toHaveBeenCalledTimes(1);
      expect(opened).not.toHaveBeenCalled();
    });

    it('offers a direct download link that does not open the editor', () => {
      const link = el().querySelector('a.doc-btn') as HTMLAnchorElement;
      expect(link.getAttribute('href')).toBe('/files/r-1?download=true');
      expect(link.hasAttribute('download')).toBe(true);

      link.addEventListener('click', (event) => event.preventDefault()); // jsdom cannot navigate
      link.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
      expect(opened).not.toHaveBeenCalled();
    });
  });
});
