import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { ClaimStatus } from '../../../core/models/models';
import { ClaimJourney } from './claim-journey';

describe('ClaimJourney', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideZonelessChangeDetection()] });
  });

  async function render(status: ClaimStatus, readiness = 0) {
    const fixture = TestBed.createComponent(ClaimJourney);
    fixture.componentRef.setInput('status', status);
    fixture.componentRef.setInput('readiness', readiness);
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    const steps = Array.from(host.querySelectorAll('li'));
    return {
      labels: steps.map((li) => li.querySelector('.label')!.textContent!.trim()),
      done: steps.filter((li) => li.classList.contains('done')).length,
      current: steps.findIndex((li) => li.classList.contains('current')),
      nodes: steps.map((li) => li.querySelector('.node')!.textContent!.trim()),
      fill: parseFloat((host.querySelector('.rail-fill') as HTMLElement).style.width),
    };
  }

  it('shows the seven steps of the claim journey', async () => {
    const { labels } = await render('draft');
    expect(labels).toEqual(['Collect', 'Read & extract', 'Review', 'Ready', 'Approval', 'Payout', 'Reimbursed']);
  });

  it.each([
    ['draft', 0],
    ['processing', 1],
    ['needs_attention', 2],
    ['ready', 3],
    ['submitted', 4],
    ['rejected', 4],
    ['approved', 5],
  ] as [ClaimStatus, number][])('marks the step for "%s" (index %i) as current and earlier ones done', async (status, index) => {
    const { current, done } = await render(status);

    expect(current).toBe(index);
    expect(done).toBe(index);
  });

  it('numbers upcoming steps and ticks completed ones', async () => {
    const { nodes } = await render('ready');
    expect(nodes).toEqual(['✓', '✓', '✓', '4', '5', '6', '7']);
  });

  it('completes every step once the claim is paid', async () => {
    const { done, current, fill } = await render('paid');

    expect(done).toBe(7);
    expect(current).toBe(-1);
    expect(fill).toBe(100);
  });

  it.each([
    ['draft', 0],
    ['ready', 50],
    ['approved', (5 / 6) * 100],
  ] as [ClaimStatus, number][])('fills the rail in proportion to progress (%s)', async (status, expected) => {
    expect((await render(status)).fill).toBeCloseTo(expected);
  });

  it('adds partial progress inside the review step based on readiness', async () => {
    const { fill } = await render('needs_attention', 50);
    // two completed segments plus half of the third, out of six segments
    expect(fill).toBeCloseTo((2.5 / 6) * 100);
  });

  it('ignores readiness outside the review step', async () => {
    const { fill } = await render('processing', 80);
    expect(fill).toBeCloseTo((1 / 6) * 100);
  });
});
