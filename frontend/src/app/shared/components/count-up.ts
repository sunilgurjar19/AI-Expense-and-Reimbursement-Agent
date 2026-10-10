import { Component, DestroyRef, effect, inject, input, signal, untracked } from '@angular/core';

import { formatMoney } from '../pipes/money.pipe';

/** Animates a number from its previous value to the new one. */
@Component({
  selector: 'app-count-up',
  template: `{{ display() }}`,
})
export class CountUp {
  readonly value = input(0);
  readonly currency = input<string | null>(null);
  readonly compact = input(false);
  readonly duration = input(900);

  protected readonly display = signal('0');
  private current = 0;
  private frame = 0;

  constructor() {
    inject(DestroyRef).onDestroy(() => cancelAnimationFrame(this.frame));
    effect(() => {
      const target = this.value() ?? 0;
      untracked(() => this.animate(target));
    });
  }

  private animate(target: number): void {
    cancelAnimationFrame(this.frame);
    const from = this.current;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / this.duration());
      const eased = 1 - Math.pow(1 - t, 3);
      this.current = from + (target - from) * eased;
      this.display.set(this.format(this.current));
      if (t < 1) this.frame = requestAnimationFrame(step);
    };
    this.frame = requestAnimationFrame(step);
  }

  private format(value: number): string {
    const currency = this.currency();
    return currency ? formatMoney(value, currency, this.compact()) : Math.round(value).toLocaleString('en-IN');
  }
}
