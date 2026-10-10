import { RelativeTimePipe } from './relative-time.pipe';

describe('RelativeTimePipe', () => {
  const NOW = new Date('2026-10-10T12:00:00Z');
  const SECOND = 1000;
  const MINUTE = 60 * SECOND;
  const HOUR = 60 * MINUTE;
  const DAY = 24 * HOUR;

  const pipe = new RelativeTimePipe();
  /** ISO timestamp `offsetMs` from NOW (negative = in the past). */
  const at = (offsetMs: number) => new Date(NOW.getTime() + offsetMs).toISOString();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  it.each([null, undefined, ''])('returns an empty string for %j', (value) => {
    expect(pipe.transform(value)).toBe('');
  });

  it('says "just now" for anything under a minute, past or future', () => {
    expect(pipe.transform(at(0))).toBe('just now');
    expect(pipe.transform(at(-59 * SECOND))).toBe('just now');
    expect(pipe.transform(at(30 * SECOND))).toBe('just now');
  });

  it.each([
    { when: '1 minute ago', offset: -1 * MINUTE, expected: '1 minute ago' },
    { when: '5 minutes ago', offset: -5 * MINUTE, expected: '5 minutes ago' },
    { when: '3 hours ago', offset: -3 * HOUR, expected: '3 hours ago' },
    { when: '1 day ago', offset: -1 * DAY, expected: 'yesterday' },
    { when: '3 days ago', offset: -3 * DAY, expected: '3 days ago' },
    { when: '7 days ago', offset: -7 * DAY, expected: 'last week' },
    { when: '14 days ago', offset: -14 * DAY, expected: '2 weeks ago' },
    { when: '30 days ago', offset: -30 * DAY, expected: 'last month' },
    { when: '400 days ago', offset: -400 * DAY, expected: 'last year' },
    { when: '3 years ago', offset: -3 * 365 * DAY, expected: '3 years ago' },
    { when: '5 minutes ahead', offset: 5 * MINUTE, expected: 'in 5 minutes' },
    { when: '3 hours ahead', offset: 3 * HOUR, expected: 'in 3 hours' },
    { when: '1 day ahead', offset: 1 * DAY, expected: 'tomorrow' },
  ])('formats a timestamp $when as "$expected"', ({ offset, expected }) => {
    expect(pipe.transform(at(offset))).toBe(expected);
  });

  it('uses the largest unit that fits, rounded to the nearest whole unit', () => {
    // 100 minutes is past the one-hour threshold, so it is expressed in (rounded) hours.
    expect(pipe.transform(at(-100 * MINUTE))).toBe('2 hours ago');
    expect(pipe.transform(at(-160 * SECOND))).toBe('3 minutes ago');
  });
});
