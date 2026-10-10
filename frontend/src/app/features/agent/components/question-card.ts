import { Component, computed, effect, input, output, signal, untracked } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { Question } from '../../../core/models/models';
import { MarkdownLitePipe } from '../../../shared/pipes/markdown-lite.pipe';

/** One focused question from the agent, with an input that matches its type. */
@Component({
  selector: 'app-question-card',
  imports: [FormsModule, MarkdownLitePipe],
  template: `
    <div class="q" [class.active]="active()" [class.busy]="busy()">
      <p class="prompt" [innerHTML]="question().prompt | markdownLite"></p>

      @switch (question().type) {
        @case ('choice') {
          <div class="choices">
            @for (o of question().options; track o.value; let first = $first) {
              <button class="btn btn-sm" [class.btn-primary]="first" [class.btn-ghost]="!first"
                      [disabled]="busy()" (click)="answered.emit(o.value)">{{ o.label }}</button>
            }
          </div>
        }
        @case ('select') {
          <div class="chips">
            @for (o of question().options; track o.value) {
              <button class="chip" [disabled]="busy()" (click)="answered.emit(o.value)">{{ o.label }}</button>
            }
          </div>
        }
        @default {
          <form class="row" (ngSubmit)="submit()">
            <input class="input" name="value" [type]="inputType()" [ngModel]="value()" (ngModelChange)="value.set($event)"
                   [placeholder]="placeholder()" [disabled]="busy()" [attr.step]="question().type === 'number' ? '0.01' : null" />
            <button class="btn btn-primary btn-sm" type="submit" [disabled]="busy() || !hasValue()">
              @if (busy()) { <span class="spinner"></span> } @else { {{ question().kind === 'confirm_amount' ? 'Confirm' : 'Save' }} }
            </button>
          </form>
        }
      }
    </div>
  `,
  styles: `
    .q {
      padding: 14px; border-radius: 14px; background: var(--surface);
      border: 1px solid var(--border); border-left: 4px solid var(--brand-200);
      transition: border-color 0.3s, box-shadow 0.3s, opacity 0.3s;
    }
    .q.active { border-left-color: var(--accent-500); box-shadow: 0 8px 24px -12px rgb(124 58 237 / 45%); }
    .q:not(.active) { opacity: 0.8; }
    .q.busy { opacity: 0.6; }
    .prompt { margin: 0 0 10px; font-size: 13.5px; font-weight: 500; }
    .choices { display: flex; gap: 8px; flex-wrap: wrap; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip {
      height: 30px; padding: 0 12px; border-radius: 999px; cursor: pointer;
      border: 1px solid var(--border-strong); background: var(--surface); font-size: 12.5px; font-weight: 500;
      transition: all 0.2s var(--ease);
    }
    .chip:hover:not(:disabled) { border-color: var(--brand-500); background: var(--brand-50); color: var(--brand-700); transform: translateY(-1px); }
    .row { display: flex; gap: 8px; }
    .row .input { height: 36px; border-radius: 9px; }
    .row .btn { height: 36px; min-width: 70px; }
  `,
})
export class QuestionCard {
  readonly question = input.required<Question>();
  readonly active = input(false);
  readonly busy = input(false);
  readonly answered = output<unknown>();

  protected readonly value = signal<string | number | null>(null);
  private readonly questionId = computed(() => this.question().id);

  constructor() {
    // Reset the input only when a different question arrives, not on every live claim update.
    effect(() => {
      this.questionId();
      const preset = untracked(() => this.question().default);
      this.value.set(typeof preset === 'number' || typeof preset === 'string' ? preset : null);
    });
  }

  protected inputType(): string {
    const type = this.question().type;
    return type === 'number' ? 'number' : type === 'date' ? 'date' : 'text';
  }

  protected placeholder(): string {
    return this.question().type === 'number' ? 'Amount' : 'Type your answer…';
  }

  protected hasValue(): boolean {
    const v = this.value();
    return v !== null && String(v).trim() !== '';
  }

  protected submit(): void {
    if (this.hasValue()) this.answered.emit(this.value());
  }
}
