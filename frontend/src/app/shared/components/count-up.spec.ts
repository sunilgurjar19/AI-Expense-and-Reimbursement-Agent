import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CountUp } from './count-up';

describe('CountUp', () => {
  const START = 1_000;
  let fixture: ComponentFixture<CountUp>;
  let frames: Map<number, FrameRequestCallback>;
  let cancelFrame: ReturnType<typeof vi.fn>;

  /** Run every queued animation-frame callback as if the browser painted at `time`. */
  async function paintAt(time: number) {
    const callbacks = [...frames.values()];
    frames.clear();
    callbacks.forEach((callback) => callback(time));
    await fixture.whenStable();
  }

  beforeEach(() => {
    frames = new Map();
    let nextId = 1;
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.set(nextId, callback);
      return nextId++;
    });
    cancelFrame = vi.fn((id: number) => frames.delete(id));
    vi.stubGlobal('cancelAnimationFrame', cancelFrame);
    vi.spyOn(performance, 'now').mockReturnValue(START);
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(inputs: { value?: number; currency?: string | null; compact?: boolean; duration?: number }) {
    fixture = TestBed.createComponent(CountUp);
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    await fixture.whenStable();
  }

  const shown = () => (fixture.nativeElement as HTMLElement).textContent;

  it('eases from zero up to the target value over the duration', async () => {
    await render({ value: 1000, duration: 900 });

    await paintAt(START);
    expect(shown()).toBe('0');

    await paintAt(START + 450); // halfway in time, ease-out cubic is 87.5% of the way
    expect(shown()).toBe('875');

    await paintAt(START + 900);
    expect(shown()).toBe('1,000');
  });

  it('stops requesting frames once the animation completes', async () => {
    await render({ value: 50, duration: 100 });

    await paintAt(START + 100);

    expect(frames.size).toBe(0);
  });

  it('uses Indian digit grouping for plain numbers', async () => {
    await render({ value: 123_456 });
    await paintAt(START + 10_000);
    expect(shown()).toBe('1,23,456');
  });

  it('formats as money when a currency is given', async () => {
    await render({ value: 2_500, currency: 'INR' });
    await paintAt(START + 10_000);
    expect(shown()).toBe('₹2,500.00');
  });

  it('supports compact money formatting', async () => {
    await render({ value: 250_000, currency: 'INR', compact: true });
    await paintAt(START + 10_000);
    expect(shown()).toBe('₹2.5L');
  });

  it('animates from the previous value when the input changes', async () => {
    await render({ value: 100, duration: 100 });
    await paintAt(START + 100);
    expect(shown()).toBe('100');

    fixture.componentRef.setInput('value', 200);
    await fixture.whenStable();
    await paintAt(START + 50); // halfway: 100 + 100 * 0.875

    expect(shown()).toBe('188');
  });

  it('treats a missing value as zero', async () => {
    await render({ value: 40, duration: 100 });
    await paintAt(START + 100);

    fixture.componentRef.setInput('value', null);
    await fixture.whenStable();
    await paintAt(START + 100);

    expect(shown()).toBe('0');
  });

  it('cancels the pending frame when destroyed', async () => {
    await render({ value: 1000 });
    const pending = [...frames.keys()].at(-1);

    fixture.destroy();

    expect(cancelFrame).toHaveBeenCalledWith(pending);
    expect(frames.has(pending!)).toBe(false);
  });
});
