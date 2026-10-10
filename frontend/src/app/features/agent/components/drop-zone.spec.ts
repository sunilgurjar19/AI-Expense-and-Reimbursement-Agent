import { WritableSignal, provideZonelessChangeDetection, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { makePublicConfig } from '@testing/fixtures';

import { PolicyStore } from '../../../core/config/policy.store';
import { PublicConfig } from '../../../core/models/models';
import { DropZone } from './drop-zone';

describe('DropZone', () => {
  let fixture: ComponentFixture<DropZone>;
  let config: WritableSignal<PublicConfig | null>;
  let emitted: File[][];

  const receipt = new File(['%PDF'], 'hotel.pdf', { type: 'application/pdf' });
  const photo = new File(['jpeg'], 'cab.jpg', { type: 'image/jpeg' });

  async function render(inputs: { compact?: boolean; disabled?: boolean; progress?: number | null } = {}) {
    config = signal<PublicConfig | null>(null);
    TestBed.configureTestingModule({
      providers: [provideZonelessChangeDetection(), { provide: PolicyStore, useValue: { config } }],
    });
    fixture = TestBed.createComponent(DropZone);
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    emitted = [];
    fixture.componentInstance.files.subscribe((files) => emitted.push(files));
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const zone = () => el().querySelector('.zone') as HTMLElement;
  const fileInput = () => el().querySelector('input[type=file]') as HTMLInputElement;
  const headline = () => el().querySelector('.copy strong')!.textContent!.trim();

  /** jsdom has no DragEvent/DataTransfer, so attach the payload to a plain event. */
  function dragEvent(type: string, files: File[] = []): Event {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'dataTransfer', { value: { files } });
    return event;
  }

  function pasteEvent(files: File[]): Event {
    const event = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(event, 'clipboardData', { value: { files } });
    return event;
  }

  describe('copy and limits', () => {
    it('invites the user to drop receipts, with default limits before the policy loads', async () => {
      await render();

      expect(headline()).toBe('Drop your receipts here');
      expect(fileInput().accept).toBe('.pdf,.png,.jpg');
      expect(el().querySelector('.copy span')!.textContent).toContain('up to 15 MB each');
    });

    it('uses the allowed file types and size limit from the policy', async () => {
      await render();

      config.set(makePublicConfig({ allowed_extensions: ['.pdf', '.heic'], max_upload_mb: 25 }));
      await fixture.whenStable();

      expect(fileInput().accept).toBe('.pdf,.heic');
      expect(el().querySelector('.copy span')!.textContent).toContain('up to 25 MB each');
    });

    it('has a compact variant for adding more receipts', async () => {
      await render({ compact: true });

      expect(zone().classList).toContain('compact');
      expect(headline()).toBe('Add more receipts');
    });
  });

  describe('drag and drop', () => {
    it('highlights the zone while files are dragged over it', async () => {
      await render();

      const over = dragEvent('dragover');
      zone().dispatchEvent(over);
      await fixture.whenStable();

      expect(over.defaultPrevented).toBe(true); // required for the drop to be allowed
      expect(zone().classList).toContain('over');
      expect(headline()).toBe('Release to upload ✨');

      zone().dispatchEvent(dragEvent('dragleave'));
      await fixture.whenStable();
      expect(zone().classList).not.toContain('over');
    });

    it('emits the dropped files and resets the highlight', async () => {
      await render();
      zone().dispatchEvent(dragEvent('dragover'));

      const drop = dragEvent('drop', [receipt, photo]);
      zone().dispatchEvent(drop);
      await fixture.whenStable();

      expect(drop.defaultPrevented).toBe(true); // stop the browser from opening the file
      expect(emitted).toEqual([[receipt, photo]]);
      expect(zone().classList).not.toContain('over');
    });

    it('ignores drop, pick and paste events that carry no file list at all', async () => {
      await render();

      zone().dispatchEvent(new Event('drop', { bubbles: true, cancelable: true }));
      Object.defineProperty(fileInput(), 'files', { value: null });
      fileInput().dispatchEvent(new Event('change'));
      document.body.dispatchEvent(new Event('paste', { bubbles: true }));

      expect(emitted).toEqual([]);
    });

    it('ignores a drop without files', async () => {
      await render();
      zone().dispatchEvent(dragEvent('drop', []));
      expect(emitted).toEqual([]);
    });
  });

  describe('file picker', () => {
    it('emits the picked files and clears the input so the same file can be picked again', async () => {
      await render();
      const input = fileInput();
      const setValue = vi.fn();
      Object.defineProperty(input, 'files', { value: [photo] });
      Object.defineProperty(input, 'value', { get: () => 'C:\\fakepath\\cab.jpg', set: setValue });

      input.dispatchEvent(new Event('change'));

      expect(emitted).toEqual([[photo]]);
      expect(setValue).toHaveBeenCalledWith('');
    });
  });

  describe('paste', () => {
    it('emits files pasted anywhere on the page', async () => {
      await render();

      document.body.dispatchEvent(pasteEvent([photo]));

      expect(emitted).toEqual([[photo]]);
    });

    it('lets text fields handle their own paste', async () => {
      await render();
      const textField = document.createElement('textarea');
      document.body.appendChild(textField);

      textField.dispatchEvent(pasteEvent([photo]));
      textField.remove();

      expect(emitted).toEqual([]);
    });

    it('ignores pastes without files (plain text)', async () => {
      await render();
      document.body.dispatchEvent(pasteEvent([]));
      expect(emitted).toEqual([]);
    });
  });

  describe('when disabled', () => {
    it('greys out and ignores drops, picks and pastes', async () => {
      await render({ disabled: true });

      expect(zone().classList).toContain('disabled');
      expect(fileInput().disabled).toBe(true);

      zone().dispatchEvent(dragEvent('drop', [receipt]));
      document.body.dispatchEvent(pasteEvent([receipt]));
      Object.defineProperty(fileInput(), 'files', { value: [receipt] });
      fileInput().dispatchEvent(new Event('change'));

      expect(emitted).toEqual([]);
    });
  });

  describe('upload progress', () => {
    it('shows a progress bar while uploading', async () => {
      await render({ progress: 40 });

      expect((el().querySelector('.progress .bar') as HTMLElement).style.width).toBe('40%');
      expect(el().querySelector('.progress span')!.textContent).toBe('Uploading… 40%');
    });

    it('hides the progress bar when idle', async () => {
      await render({ progress: null });
      expect(el().querySelector('.progress')).toBeNull();
    });
  });
});
