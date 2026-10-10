import { Component, computed, input } from '@angular/core';

const COLORS = ['#4f46e5', '#7c3aed', '#c026d3', '#059669', '#f59e0b', '#38bdf8'];

/** Lightweight CSS confetti burst. Render it with an @if to replay. */
@Component({
  selector: 'app-confetti',
  template: `
    <div class="confetti" aria-hidden="true">
      @for (piece of pieces(); track $index) {
        <i [style.left.%]="piece.left" [style.background]="piece.color"
           [style.animation-delay.ms]="piece.delay" [style.animation-duration.ms]="piece.duration"
           [style.--drift]="piece.drift + 'px'" [style.--spin]="piece.spin + 'deg'"
           [style.width.px]="piece.size" [style.height.px]="piece.size * 0.45"></i>
      }
    </div>
  `,
  styles: `
    .confetti { position: fixed; inset: 0; pointer-events: none; overflow: hidden; z-index: 1000; }
    i {
      position: absolute; top: -20px; border-radius: 2px;
      animation-name: fall; animation-timing-function: cubic-bezier(0.25, 0.6, 0.5, 1); animation-fill-mode: forwards;
    }
    @keyframes fall {
      to { transform: translate(var(--drift), 105vh) rotate(var(--spin)); opacity: 0.2; }
    }
  `,
})
export class Confetti {
  readonly count = input(120);

  protected readonly pieces = computed(() =>
    Array.from({ length: this.count() }, (_, i) => ({
      left: Math.random() * 100,
      color: COLORS[i % COLORS.length],
      delay: Math.random() * 500,
      duration: 1800 + Math.random() * 1600,
      drift: (Math.random() - 0.5) * 300,
      spin: 360 + Math.random() * 720,
      size: 8 + Math.random() * 8,
    })),
  );
}
