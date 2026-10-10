import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { Confetti } from './confetti';

describe('Confetti', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(count?: number) {
    const fixture = TestBed.createComponent(Confetti);
    if (count !== undefined) fixture.componentRef.setInput('count', count);
    await fixture.whenStable();
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.confetti i'));
  }

  it('renders 120 pieces by default', async () => {
    expect(await render()).toHaveLength(120);
  });

  it('renders the requested number of pieces', async () => {
    expect(await render(12)).toHaveLength(12);
  });

  it('is decorative only', async () => {
    const fixture = TestBed.createComponent(Confetti);
    await fixture.whenStable();
    expect(fixture.nativeElement.querySelector('.confetti').getAttribute('aria-hidden')).toBe('true');
  });

  it('positions each piece within the viewport with randomised motion', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(0.5);

    const [piece] = await render(1);

    expect(piece.style.left).toBe('50%');
    expect(piece.style.animationDelay).toBe('250ms');
    expect(piece.style.animationDuration).toBe('2600ms');
    expect(piece.style.width).toBe('12px');
    expect(piece.style.getPropertyValue('--drift')).toBe('0px');
    expect(piece.style.getPropertyValue('--spin')).toBe('720deg');
  });

  it('cycles through the brand colours', async () => {
    const pieces = await render(7);
    const colours = pieces.map((p) => p.style.background);

    expect(new Set(colours.slice(0, 6)).size).toBe(6);
    expect(colours[6]).toBe(colours[0]);
  });
});
