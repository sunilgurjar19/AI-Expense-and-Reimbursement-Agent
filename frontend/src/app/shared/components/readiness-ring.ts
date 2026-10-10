import { Component, computed, input } from '@angular/core';

/** Circular meter: the fill carries state, the track is a lighter step of the same hue. */
@Component({
  selector: 'app-readiness-ring',
  template: `
    <div class="ring" [style.width.px]="size()" [style.height.px]="size()"
         role="meter" aria-valuemin="0" aria-valuemax="100" [attr.aria-valuenow]="value()"
         [attr.aria-label]="label()">
      <svg [attr.viewBox]="'0 0 ' + size() + ' ' + size()">
        <circle [class]="'track ' + tone()" [attr.cx]="center()" [attr.cy]="center()"
                [attr.r]="radius()" [attr.stroke-width]="stroke()" />
        <circle [class]="'fill ' + tone()" [attr.cx]="center()" [attr.cy]="center()"
                [attr.r]="radius()" [attr.stroke-width]="stroke()"
                [attr.stroke-dasharray]="circumference()" [attr.stroke-dashoffset]="offset()" />
      </svg>
      <div class="center">
        <strong [style.font-size.px]="size() * 0.24">{{ value() }}<small>%</small></strong>
        @if (label()) {
          <span>{{ label() }}</span>
        }
      </div>
    </div>
  `,
  styles: `
    .ring { position: relative; flex-shrink: 0; }
    svg { transform: rotate(-90deg); width: 100%; height: 100%; }
    circle { fill: none; }
    .fill { stroke-linecap: round; transition: stroke-dashoffset 0.9s var(--ease), stroke 0.4s; }
    .track.low { stroke: #fde7c7; }   .fill.low { stroke: #d97706; }
    .track.mid { stroke: var(--brand-100); } .fill.mid { stroke: var(--brand-600); }
    .track.high { stroke: #c9f0dd; }  .fill.high { stroke: #059669; }
    .center {
      position: absolute; inset: 0;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      line-height: 1.1;
    }
    strong { font-weight: 800; color: var(--text); }
    small { font-size: 0.55em; font-weight: 700; color: var(--text-2); }
    span { font-size: 11px; color: var(--text-2); font-weight: 500; }
  `,
})
export class ReadinessRing {
  readonly value = input(0);
  readonly size = input(120);
  readonly label = input('');

  protected readonly stroke = computed(() => Math.max(6, this.size() * 0.09));
  protected readonly center = computed(() => this.size() / 2);
  protected readonly radius = computed(() => (this.size() - this.stroke()) / 2);
  protected readonly circumference = computed(() => 2 * Math.PI * this.radius());
  protected readonly offset = computed(
    () => this.circumference() * (1 - Math.min(100, Math.max(0, this.value())) / 100),
  );
  protected readonly tone = computed(() => (this.value() >= 100 ? 'high' : this.value() >= 40 ? 'mid' : 'low'));
}
