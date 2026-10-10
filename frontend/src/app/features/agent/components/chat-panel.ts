import { Component, ElementRef, effect, inject, input, output, signal, viewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppConfigService } from '../../../core/config/app-config.service';
import { ChatMessage, Question } from '../../../core/models/models';
import { MarkdownLitePipe } from '../../../shared/pipes/markdown-lite.pipe';
import { RelativeTimePipe } from '../../../shared/pipes/relative-time.pipe';
import { QuestionCard } from './question-card';

@Component({
  selector: 'app-chat-panel',
  imports: [FormsModule, QuestionCard, MarkdownLitePipe, RelativeTimePipe],
  templateUrl: './chat-panel.html',
  styleUrl: './chat-panel.scss',
})
export class ChatPanel {
  readonly messages = input.required<ChatMessage[]>();
  readonly questions = input<Question[]>([]);
  readonly agentName = input('Agent');
  readonly processing = input(0);
  readonly thinking = input(false);
  readonly answering = input<string | null>(null);
  readonly disabled = input(false);

  readonly answered = output<{ question: Question; value: unknown }>();
  readonly send = output<string>();
  readonly attach = output<File[]>();

  protected readonly quickPrompts = inject(AppConfigService).value.quickPrompts;
  protected readonly draft = signal('');
  private readonly scroller = viewChild<ElementRef<HTMLElement>>('scroller');

  constructor() {
    // Keep the newest message / question in view.
    effect(() => {
      this.messages();
      this.questions();
      this.thinking();
      const el = this.scroller()?.nativeElement;
      if (el) setTimeout(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }), 60);
    });
  }

  protected submit(text = this.draft()): void {
    const message = text.trim();
    if (!message || this.thinking() || this.disabled()) return;
    this.send.emit(message);
    this.draft.set('');
  }

  protected onAttach(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files?.length) this.attach.emit(Array.from(input.files));
    input.value = '';
  }
}
