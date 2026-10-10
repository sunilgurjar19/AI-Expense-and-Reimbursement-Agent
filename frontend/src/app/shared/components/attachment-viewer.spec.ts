import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { Attachment } from '../../core/models/models';
import { AttachmentViewer } from './attachment-viewer';

describe('AttachmentViewer', () => {
  let fixture: ComponentFixture<AttachmentViewer>;
  let closed: number;

  const attachment = (id: string, overrides: Partial<Attachment> = {}): Attachment => ({
    id,
    name: `${id}.pdf`,
    mimeType: 'application/pdf',
    sizeBytes: 48_000,
    subtitle: 'Uber · Travel',
    viewUrl: `/files/${id}`,
    downloadUrl: `/files/${id}?download=true`,
    ...overrides,
  });

  const docs = [
    attachment('a', { name: 'hotel.jpg', mimeType: 'image/jpeg', sizeBytes: 2_400_000, subtitle: 'Taj · Lodging' }),
    attachment('b', { name: 'flight.pdf' }),
    attachment('c', { name: 'cab.pdf', sizeBytes: 200 }),
  ];

  async function render(attachments: Attachment[] = docs, startIndex = 0) {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
    fixture = TestBed.createComponent(AttachmentViewer);
    fixture.componentRef.setInput('attachments', attachments);
    fixture.componentRef.setInput('startIndex', startIndex);
    closed = 0;
    fixture.componentInstance.closed.subscribe(() => closed++);
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const title = () => el().querySelector('.title strong')!.textContent;
  const details = () => el().querySelector('.title span')!.textContent;
  const press = async (key: string) => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key }));
    await fixture.whenStable();
  };

  it('shows the selected document with its details and position', async () => {
    await render();

    expect(title()).toBe('hotel.jpg');
    expect(details()).toBe('Taj · Lodging · 2.3 MB · 1 of 3');
    expect(el().querySelector('[role=dialog]')!.getAttribute('aria-label')).toBe('hotel.jpg');
  });

  it('renders images inline and other documents in a frame', async () => {
    await render();
    expect(el().querySelector('.stage img')!.getAttribute('src')).toBe('/files/a');

    (el().querySelector('.nav.next') as HTMLButtonElement).click();
    await fixture.whenStable();

    expect(el().querySelector('.stage img')).toBeNull();
    expect(el().querySelector('iframe')!.getAttribute('src')).toBe('/files/b');
  });

  it('links to the document in a new tab and as a download', async () => {
    await render();

    const [open, download] = Array.from(el().querySelectorAll('header a'));
    expect(open.getAttribute('href')).toBe('/files/a');
    expect(open.getAttribute('target')).toBe('_blank');
    expect(download.getAttribute('href')).toBe('/files/a?download=true');
    expect(download.hasAttribute('download')).toBe(true);
  });

  it('starts at the requested document', async () => {
    await render(docs, 1);
    expect(title()).toBe('flight.pdf');
  });

  it('falls back to the first document if the index is out of range', async () => {
    await render(docs, 7);
    expect(title()).toBe('hotel.jpg');
  });

  it('follows later changes to the start index', async () => {
    await render(docs, 0);

    fixture.componentRef.setInput('startIndex', 2);
    await fixture.whenStable();

    expect(title()).toBe('cab.pdf');
  });

  it('pages forward and backward, wrapping around', async () => {
    await render();
    const next = el().querySelector('.nav.next') as HTMLButtonElement;
    const prev = el().querySelector('.nav.prev') as HTMLButtonElement;

    prev.click();
    await fixture.whenStable();
    expect(title()).toBe('cab.pdf');

    next.click();
    next.click();
    await fixture.whenStable();
    expect(title()).toBe('flight.pdf');
  });

  it('supports keyboard navigation and Escape to close', async () => {
    await render();

    await press('ArrowRight');
    expect(title()).toBe('flight.pdf');
    await press('ArrowLeft');
    await press('ArrowLeft');
    expect(title()).toBe('cab.pdf');

    await press('Enter'); // unrelated keys are ignored
    expect(title()).toBe('cab.pdf');
    expect(closed).toBe(0);

    await press('Escape');
    expect(closed).toBe(1);
  });

  it('hides paging controls for a single document', async () => {
    await render([docs[1]]);

    expect(el().querySelector('.nav')).toBeNull();
    expect(details()).toContain('1 of 1');
  });

  it.each([
    [2_400_000, '2.3 MB'],
    [1024 * 1024, '1.0 MB'],
    [48_000, '47 KB'],
    [200, '1 KB'],
  ])('formats %i bytes as %s', async (sizeBytes, expected) => {
    await render([attachment('x', { sizeBytes })]);
    expect(details()).toContain(expected);
  });

  it('closes from the close button or a click on the backdrop', async () => {
    await render();

    (el().querySelector('[aria-label=Close]') as HTMLButtonElement).click();
    (el().querySelector('.overlay') as HTMLElement).click();

    expect(closed).toBe(2);
  });

  it('stays open when clicking inside the viewer', async () => {
    await render();
    (el().querySelector('.viewer') as HTMLElement).click();
    expect(closed).toBe(0);
  });
});
