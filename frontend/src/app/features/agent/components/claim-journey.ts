import { Component, computed, input } from '@angular/core';

import { JOURNEY } from '../../../core/models/display';
import { ClaimStatus } from '../../../core/models/models';

/** Horizontal stepper showing where the claim is in its end-to-end journey. */
@Component({
  selector: 'app-claim-journey',
  template: `
    <div class="journey">
      <div class="rail"><div class="rail-fill" [style.width.%]="fill()"></div></div>
      <ol>
      @for (step of steps; track step.key; let i = $index) {
        <li [class.done]="i < current()" [class.current]="i === current()">
          <span class="node">
            @if (i < current()) { ✓ } @else { {{ i + 1 }} }
          </span>
          <span class="label">{{ step.label }}</span>
        </li>
      }
      </ol>
    </div>
  `,
  styles: `
    .journey {
      position: relative; padding: 14px 18px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
    }
    ol { list-style: none; margin: 0; padding: 0; display: flex; justify-content: space-between; }
    .rail {
      position: absolute; left: 48px; right: 48px; top: 29px; height: 4px;
      border-radius: 4px; background: var(--brand-100); overflow: hidden;
    }
    .rail-fill {
      height: 100%; border-radius: 4px; background: var(--gradient);
      transition: width 0.9s var(--ease);
    }
    li {
      position: relative; z-index: 1;
      display: flex; flex-direction: column; align-items: center; gap: 6px; width: 90px;
    }
    .node {
      display: grid; place-items: center; width: 30px; height: 30px; border-radius: 50%;
      background: var(--surface); border: 2px solid var(--brand-200);
      color: var(--text-3); font-size: 12px; font-weight: 700;
      transition: all 0.4s var(--ease);
    }
    .label { font-size: 12px; font-weight: 600; color: var(--text-3); white-space: nowrap; transition: color 0.3s; }
    li.done .node { background: var(--brand-600); border-color: var(--brand-600); color: #fff; }
    li.done .label { color: var(--text-2); }
    li.current .node {
      background: var(--gradient); border-color: transparent; color: #fff; transform: scale(1.15);
      animation: pulse-ring 1.6s infinite;
    }
    li.current .label { color: var(--brand-700); }
  `,
})
export class ClaimJourney {
  readonly status = input.required<ClaimStatus>();
  readonly readiness = input(0);

  protected readonly steps = JOURNEY;

  protected readonly current = computed(() => {
    const index = JOURNEY.findIndex((s) => s.statuses.includes(this.status()));
    return this.status() === 'paid' ? JOURNEY.length : Math.max(0, index);
  });

  /** Rail fill: completed steps plus partial progress within the review step. */
  protected readonly fill = computed(() => {
    const segments = JOURNEY.length - 1;
    const base = Math.min(this.current(), segments);
    const partial = this.status() === 'needs_attention' ? this.readiness() / 100 : 0;
    return Math.min(100, ((base + partial) / segments) * 100);
  });
}
