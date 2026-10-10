import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { makeQuestion } from '@testing/fixtures';

import { AppConfigService } from '../../../core/config/app-config.service';
import { ChatMessage, Question } from '../../../core/models/models';
import { ChatPanel } from './chat-panel';

describe('ChatPanel', () => {
  let fixture: ComponentFixture<ChatPanel>;
  let sent: string[];
  let answers: { question: Question; value: unknown }[];
  let attached: File[][];

  const message = (overrides: Partial<ChatMessage>): ChatMessage => ({
    id: 'm-1',
    role: 'agent',
    text: 'Hello',
    created_at: new Date().toISOString(),
    meta: {},
    ...overrides,
  });

  const conversation = [
    message({ id: 'm-1', role: 'agent', text: 'I read **3 receipts**' }),
    message({ id: 'm-2', role: 'user', text: "What's my total?" }),
  ];

  type Inputs = Partial<{
    messages: ChatMessage[];
    questions: Question[];
    agentName: string;
    processing: number;
    thinking: boolean;
    answering: string | null;
    disabled: boolean;
  }>;

  async function render(inputs: Inputs = {}) {
    TestBed.configureTestingModule({
      providers: [
        provideZonelessChangeDetection(),
        { provide: AppConfigService, useValue: { value: { quickPrompts: ["What's my total?", 'Is this ready?'] } } },
      ],
    });
    fixture = TestBed.createComponent(ChatPanel);
    fixture.componentRef.setInput('messages', conversation);
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    sent = [];
    answers = [];
    attached = [];
    fixture.componentInstance.send.subscribe((text) => sent.push(text));
    fixture.componentInstance.answered.subscribe((answer) => answers.push(answer));
    fixture.componentInstance.attach.subscribe((files) => attached.push(files));
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const status = () => el().querySelector('.status')!.textContent!.trim();
  const draftInput = () => el().querySelector('input[name=draft]') as HTMLInputElement;
  const sendButton = () => el().querySelector('button.send') as HTMLButtonElement;
  const quickPrompts = () => Array.from(el().querySelectorAll<HTMLButtonElement>('button.prompt'));

  async function typeDraft(text: string) {
    draftInput().value = text;
    draftInput().dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  describe('header', () => {
    it('shows the agent name and its idle status', async () => {
      await render({ agentName: 'Rika' });

      expect(el().querySelector('.chat-head strong')!.textContent).toBe('Rika');
      expect(status()).toBe('Your reimbursement assistant');
    });

    it.each([
      [{ processing: 1 }, 'Reading 1 receipt…'],
      [{ processing: 3 }, 'Reading 3 receipts…'],
      [{ thinking: true }, 'Thinking…'],
      [{ processing: 2, thinking: true }, 'Reading 2 receipts…'],
    ])('reports what the agent is doing (%o → "%s")', async (inputs, expected) => {
      await render(inputs);
      expect(status()).toBe(expected);
    });
  });

  describe('messages', () => {
    it('renders each message as a bubble styled by its author', async () => {
      await render();

      const bubbles = Array.from(el().querySelectorAll('.msg'));
      expect(bubbles.map((b) => b.className)).toEqual(['msg agent', 'msg user']);
      expect(bubbles[0].querySelector('.bubble div')!.innerHTML).toBe('I read <strong>3 receipts</strong>');
      expect(bubbles[0].querySelector('.mini-avatar')).not.toBeNull();
      expect(bubbles[1].querySelector('.mini-avatar')).toBeNull();
      expect(bubbles[1].querySelector('time')!.textContent).toBe('just now');
    });

    it('shows a typing indicator while the agent is busy', async () => {
      await render();
      expect(el().querySelector('.typing')).toBeNull();

      fixture.componentRef.setInput('thinking', true);
      await fixture.whenStable();

      expect(el().querySelector('.typing')).not.toBeNull();
    });

    it('scrolls to the newest message when the conversation changes', async () => {
      const scrollTo = vi.spyOn(Element.prototype, 'scrollTo');
      await render();
      const scroller = el().querySelector('.messages') as HTMLElement;
      // Only count calls made on this panel's message list (other instances may still have timers pending).
      const scrollerCalls = () => scrollTo.mock.calls.filter((_, i) => scrollTo.mock.contexts[i] === scroller);
      const toBottom = { top: scroller.scrollHeight, behavior: 'smooth' };

      await vi.waitFor(() => expect(scrollerCalls()).toEqual([[toBottom]]));

      fixture.componentRef.setInput('messages', [...conversation, message({ id: 'm-3', text: 'Total is ₹827' })]);
      await fixture.whenStable();

      await vi.waitFor(() => expect(scrollerCalls()).toEqual([[toBottom], [toBottom]]));
    });
  });

  describe('agent questions', () => {
    const questions = [
      makeQuestion({
        id: 'q-1',
        type: 'choice',
        options: [
          { value: 'keep', label: 'Keep both' },
          { value: 'exclude', label: 'Remove' },
        ],
      }),
      makeQuestion({ id: 'q-2', type: 'text' }),
    ];

    it('lists open questions with a counter, highlighting the first', async () => {
      await render({ questions });

      expect(el().querySelector('.q-count')!.textContent).toBe('2 left');
      const cards = Array.from(el().querySelectorAll('app-question-card .q'));
      expect(cards.map((c) => c.classList.contains('active'))).toEqual([true, false]);
    });

    it('forwards an answer together with its question', async () => {
      await render({ questions });

      (el().querySelector('app-question-card .choices button') as HTMLButtonElement).click();

      expect(answers).toEqual([{ question: questions[0], value: 'keep' }]);
    });

    it('marks the question being answered as busy', async () => {
      await render({ questions, answering: 'q-1' });

      const firstCard = el().querySelector('app-question-card .q')!;
      expect(firstCard.classList).toContain('busy');
    });

    it('hides questions on a locked claim', async () => {
      await render({ questions, disabled: true });
      expect(el().querySelector('.questions')).toBeNull();
    });
  });

  describe('composer', () => {
    it('sends the trimmed draft and clears the input', async () => {
      await render();
      expect(sendButton().disabled).toBe(true);

      await typeDraft('  Is the hotel within policy?  ');
      expect(sendButton().disabled).toBe(false);
      sendButton().click();
      await fixture.whenStable();

      expect(sent).toEqual(['Is the hotel within policy?']);
      expect(draftInput().value).toBe('');
    });

    it('does not send blank messages', async () => {
      await render();
      await typeDraft('   ');

      el().querySelector('form')!.dispatchEvent(new Event('submit'));

      expect(sent).toEqual([]);
      expect(sendButton().disabled).toBe(true);
    });

    it('does not send while the agent is thinking', async () => {
      await render({ thinking: true });
      await typeDraft('Hello?');

      el().querySelector('form')!.dispatchEvent(new Event('submit'));

      expect(sent).toEqual([]);
      expect(sendButton().disabled).toBe(true);
    });

    it('offers quick prompts that send immediately', async () => {
      await render();

      expect(quickPrompts().map((b) => b.textContent!.trim())).toEqual(["What's my total?", 'Is this ready?']);
      quickPrompts()[1].click();

      expect(sent).toEqual(['Is this ready?']);
    });

    it('invites the user to ask the agent by name', async () => {
      await render({ agentName: 'Rika' });
      expect(draftInput().placeholder).toBe('Ask Rika or answer in your own words…');
    });

    it('emits attached files and resets the picker', async () => {
      await render();
      const picker = el().querySelector('input[type=file]') as HTMLInputElement;
      const file = new File(['%PDF'], 'bill.pdf', { type: 'application/pdf' });
      const setValue = vi.fn();
      Object.defineProperty(picker, 'files', { value: [file], configurable: true });
      Object.defineProperty(picker, 'value', { get: () => '', set: setValue });

      picker.dispatchEvent(new Event('change'));

      expect(attached).toEqual([[file]]);
      expect(setValue).toHaveBeenCalledWith('');
    });

    it('ignores a picker change without files', async () => {
      await render();
      const picker = el().querySelector('input[type=file]') as HTMLInputElement;
      Object.defineProperty(picker, 'files', { value: [] });

      picker.dispatchEvent(new Event('change'));

      expect(attached).toEqual([]);
    });
  });

  describe('on a locked claim', () => {
    beforeEach(async () => render({ disabled: true }));

    it('explains the claim is locked and disables every input', () => {
      expect(draftInput().placeholder).toBe('This claim is locked');
      expect(draftInput().disabled).toBe(true);
      expect(sendButton().disabled).toBe(true);
      expect(quickPrompts().every((b) => b.disabled)).toBe(true);
      expect(el().querySelector('.attach')!.classList).toContain('disabled');
    });

    it('refuses to send even if a quick prompt click gets through', () => {
      // A disabled button swallows clicks, so re-enable it in the DOM to prove the
      // component's own guard (not just the disabled attribute) blocks sending.
      quickPrompts()[0].disabled = false;
      quickPrompts()[0].click();
      expect(sent).toEqual([]);
    });
  });
});
