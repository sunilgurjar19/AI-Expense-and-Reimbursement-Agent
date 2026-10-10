import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ReadinessRing } from './readiness-ring';

describe('ReadinessRing', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(inputs: { value?: number; size?: number; label?: string } = {}) {
    const fixture = TestBed.createComponent(ReadinessRing);
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    await fixture.whenStable();
    const host = fixture.nativeElement as HTMLElement;
    const [track, fill] = Array.from(host.querySelectorAll('circle'));
    return { host, meter: host.querySelector('.ring') as HTMLElement, track, fill };
  }

  const attr = (el: Element, name: string) => Number(el.getAttribute(name));

  it('shows the percentage and exposes it as an accessible meter', async () => {
    const { host, meter } = await render({ value: 65 });

    expect(host.querySelector('strong')!.textContent).toBe('65%');
    expect(meter.getAttribute('role')).toBe('meter');
    expect(meter.getAttribute('aria-valuenow')).toBe('65');
  });

  it('renders an optional caption that also labels the meter', async () => {
    const withLabel = await render({ value: 10, label: 'ready' });
    expect(withLabel.host.querySelector('.center span')!.textContent).toBe('ready');
    expect(withLabel.meter.getAttribute('aria-label')).toBe('ready');

    const withoutLabel = await render({ value: 10 });
    expect(withoutLabel.host.querySelector('.center span')).toBeNull();
  });

  const classes = (el: Element) => Array.from(el.classList).sort();

  it.each([
    { value: 0, tone: 'low' },
    { value: 39, tone: 'low' },
    { value: 40, tone: 'mid' },
    { value: 99, tone: 'mid' },
    { value: 100, tone: 'high' },
  ])('uses the "$tone" tone at $value% on both track and fill', async ({ value, tone }) => {
    const { track, fill } = await render({ value });

    expect(classes(track)).toEqual(['track', tone].sort());
    expect(classes(fill)).toEqual(['fill', tone].sort());
  });

  it('draws the arc proportionally to the value', async () => {
    const { fill } = await render({ value: 25, size: 120 });

    // stroke = max(6, 120 * 0.09) = 10.8 → radius = (120 - 10.8) / 2 = 54.6
    const circumference = 2 * Math.PI * 54.6;
    expect(attr(fill, 'r')).toBeCloseTo(54.6);
    expect(attr(fill, 'stroke-dasharray')).toBeCloseTo(circumference);
    expect(attr(fill, 'stroke-dashoffset')).toBeCloseTo(circumference * 0.75);
  });

  it('clamps the arc to 0-100% for out-of-range values', async () => {
    const over = await render({ value: 140 });
    expect(attr(over.fill, 'stroke-dashoffset')).toBeCloseTo(0);

    const under = await render({ value: -20 });
    expect(attr(under.fill, 'stroke-dashoffset')).toBeCloseTo(attr(under.fill, 'stroke-dasharray'));
  });

  it('scales to the requested size with a minimum stroke width', async () => {
    const { meter, fill, host } = await render({ size: 40 });

    expect(meter.style.width).toBe('40px');
    expect(meter.style.height).toBe('40px');
    expect(host.querySelector('svg')!.getAttribute('viewBox')).toBe('0 0 40 40');
    expect(attr(fill, 'cx')).toBe(20);
    expect(attr(fill, 'stroke-width')).toBe(6); // 40 * 0.09 would be too thin
  });
});
