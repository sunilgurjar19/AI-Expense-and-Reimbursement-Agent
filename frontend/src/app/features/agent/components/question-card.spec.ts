import { provideZonelessChangeDetection } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { makeQuestion } from '@testing/fixtures';

import { Question } from '../../../core/models/models';
import { QuestionCard } from './question-card';

describe('QuestionCard', () => {
  let fixture: ComponentFixture<QuestionCard>;
  let emitted: unknown[];

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(question: Question, inputs: { active?: boolean; busy?: boolean } = {}) {
    fixture = TestBed.createComponent(QuestionCard);
    fixture.componentRef.setInput('question', question);
    for (const [name, value] of Object.entries(inputs)) {
      fixture.componentRef.setInput(name, value);
    }
    emitted = [];
    fixture.componentInstance.answered.subscribe((value) => emitted.push(value));
    await fixture.whenStable();
  }

  const el = () => fixture.nativeElement as HTMLElement;
  const input = () => el().querySelector('input') as HTMLInputElement;
  const saveButton = () => el().querySelector('button[type=submit]') as HTMLButtonElement;
  const buttons = (selector: string) => Array.from(el().querySelectorAll<HTMLButtonElement>(selector));

  async function type(value: string) {
    input().value = value;
    input().dispatchEvent(new Event('input'));
    await fixture.whenStable();
  }

  it('renders the prompt with lightweight markdown', async () => {
    await render(makeQuestion({ prompt: 'Confirm the **total** for Uber' }));

    expect(el().querySelector('.prompt')!.innerHTML).toBe('Confirm the <strong>total</strong> for Uber');
  });

  it('highlights the active question', async () => {
    await render(makeQuestion(), { active: true });
    expect(el().querySelector('.q')!.classList).toContain('active');
  });

  describe('choice questions', () => {
    const question = makeQuestion({
      type: 'choice',
      kind: 'duplicate',
      options: [
        { value: 'exclude', label: 'Remove duplicate' },
        { value: 'keep', label: 'Keep both' },
      ],
    });

    it('renders one button per option, emphasising the first', async () => {
      await render(question);

      const options = buttons('.choices button');
      expect(options.map((b) => b.textContent!.trim())).toEqual(['Remove duplicate', 'Keep both']);
      expect(options[0].classList).toContain('btn-primary');
      expect(options[1].classList).toContain('btn-ghost');
    });

    it('emits the value of the clicked option', async () => {
      await render(question);

      buttons('.choices button')[1].click();

      expect(emitted).toEqual(['keep']);
    });

    it('disables the options while the answer is being saved', async () => {
      await render(question, { busy: true });

      expect(buttons('.choices button').every((b) => b.disabled)).toBe(true);
    });
  });

  describe('select questions', () => {
    const question = makeQuestion({
      type: 'select',
      kind: 'category',
      options: [
        { value: 'meals', label: '🍽️ Meals' },
        { value: 'travel', label: '🚕 Travel' },
        { value: 'lodging', label: '🏨 Lodging' },
      ],
    });

    it('renders the options as chips and emits the chosen value', async () => {
      await render(question);

      const chips = buttons('.chip');
      expect(chips).toHaveLength(3);
      chips[2].click();

      expect(emitted).toEqual(['lodging']);
    });

    it('disables the chips while busy', async () => {
      await render(question, { busy: true });
      expect(buttons('.chip').every((b) => b.disabled)).toBe(true);
    });
  });

  describe('text questions', () => {
    const question = makeQuestion({ type: 'text', default: null });

    it('renders a text input with a Save button that is disabled until something is typed', async () => {
      await render(question);

      expect(input().type).toBe('text');
      expect(input().placeholder).toBe('Type your answer…');
      expect(saveButton().textContent!.trim()).toBe('Save');
      expect(saveButton().disabled).toBe(true);

      await type('Client dinner');
      expect(saveButton().disabled).toBe(false);
    });

    it('keeps Save disabled for whitespace-only answers', async () => {
      await render(question);

      await type('   ');

      expect(saveButton().disabled).toBe(true);
    });

    it('emits the typed answer on Save', async () => {
      await render(question);
      await type('Client dinner with Acme');

      saveButton().click();

      expect(emitted).toEqual(['Client dinner with Acme']);
    });

    it('does not emit when the form is submitted without a value', async () => {
      await render(question);

      el().querySelector('form')!.dispatchEvent(new Event('submit'));

      expect(emitted).toEqual([]);
    });

    it('pre-fills a suggested answer from the question default', async () => {
      await render(makeQuestion({ type: 'text', default: 'Team offsite' }));

      expect(input().value).toBe('Team offsite');
      expect(saveButton().disabled).toBe(false);
    });
  });

  describe('number questions', () => {
    const question = makeQuestion({ type: 'number', kind: 'total_amount', default: null });

    it('renders an amount input with cent precision', async () => {
      await render(question);

      expect(input().type).toBe('number');
      expect(input().getAttribute('step')).toBe('0.01');
      expect(input().placeholder).toBe('Amount');
      expect(saveButton().disabled).toBe(true);
    });

    it('emits the amount the user typed', async () => {
      await render(question);
      await type('1250.5');

      saveButton().click();

      // The input is bound through the default value accessor, so the amount arrives as the
      // entered text; the API parses it (to_amount) on the server side.
      expect(emitted).toEqual(['1250.5']);
    });

    it('emits a pre-filled numeric default unchanged', async () => {
      await render(makeQuestion({ type: 'number', kind: 'confirm_amount', default: 827 }));

      saveButton().click();

      expect(emitted).toEqual([827]);
    });

    it('labels the button "Confirm" when confirming an extracted amount', async () => {
      await render(makeQuestion({ type: 'number', kind: 'confirm_amount', default: 827 }));
      expect(saveButton().textContent!.trim()).toBe('Confirm');
    });
  });

  it('renders a date picker for date questions', async () => {
    await render(makeQuestion({ type: 'date', kind: 'date' }));

    expect(input().type).toBe('date');
    expect(input().hasAttribute('step')).toBe(false);
  });

  it('shows a spinner and locks the input while busy', async () => {
    await render(makeQuestion({ type: 'text', default: 'Ready' }), { busy: true });

    expect(saveButton().querySelector('.spinner')).not.toBeNull();
    expect(saveButton().disabled).toBe(true);
    expect(input().disabled).toBe(true);
  });

  describe('when the question input changes', () => {
    it('keeps what the user typed if the same question is re-sent by a live update', async () => {
      const original = makeQuestion({ id: 'q-1', default: null });
      await render(original);
      await type('My draft answer');

      fixture.componentRef.setInput('question', { ...original, prompt: 'Reworded prompt' });
      await fixture.whenStable();

      expect(input().value).toBe('My draft answer');
    });

    it('resets to the new default when a different question arrives', async () => {
      await render(makeQuestion({ id: 'q-1' }));
      await type('Old answer');

      fixture.componentRef.setInput('question', makeQuestion({ id: 'q-2', default: 'New default' }));
      await fixture.whenStable();

      expect(input().value).toBe('New default');
    });

    it('ignores non-primitive defaults', async () => {
      await render(makeQuestion({ id: 'q-3', default: { amount: 5 } }));

      expect(input().value).toBe('');
      expect(saveButton().disabled).toBe(true);
    });
  });
});
