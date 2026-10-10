import { TestBed } from '@angular/core/testing';

import { AppConfigService } from '../config/app-config.service';
import { ToastService } from './toast.service';

describe('ToastService', () => {
  const DEFAULT_DURATION = 3000;
  let service: ToastService;

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [{ provide: AppConfigService, useValue: { value: { toastDurationMs: DEFAULT_DURATION } } }],
    });
    service = TestBed.inject(ToastService);
  });

  const titles = () => service.toasts().map((t) => t.title);

  it('starts empty', () => {
    expect(service.toasts()).toEqual([]);
  });

  it('adds a toast with a unique id and the configured default duration', () => {
    service.show({ level: 'info', title: 'Receipt uploaded', message: 'Reading it now' });
    service.show({ level: 'info', title: 'Second' });

    const [first, second] = service.toasts();
    expect(first).toEqual({
      id: 1,
      level: 'info',
      title: 'Receipt uploaded',
      message: 'Reading it now',
      duration: DEFAULT_DURATION,
    });
    expect(second.id).toBe(2);
  });

  it('respects a custom duration and keeps the link', () => {
    service.show({ level: 'success', title: 'Approved', link: '/claims/c-1', duration: 10_000 });

    expect(service.toasts()[0]).toEqual(expect.objectContaining({ duration: 10_000, link: '/claims/c-1' }));
  });

  it('auto-dismisses each toast after its duration', () => {
    service.show({ level: 'info', title: 'Short', duration: 1000 });
    service.show({ level: 'info', title: 'Default' });

    vi.advanceTimersByTime(999);
    expect(titles()).toEqual(['Short', 'Default']);

    vi.advanceTimersByTime(1);
    expect(titles()).toEqual(['Default']);

    vi.advanceTimersByTime(DEFAULT_DURATION);
    expect(titles()).toEqual([]);
  });

  it('shows at most four toasts, dropping the oldest', () => {
    for (const title of ['one', 'two', 'three', 'four', 'five']) {
      service.show({ level: 'info', title });
    }

    expect(titles()).toEqual(['two', 'three', 'four', 'five']);
  });

  it('dismisses a toast by id', () => {
    service.show({ level: 'info', title: 'keep' });
    service.show({ level: 'info', title: 'drop' });

    service.dismiss(service.toasts()[1].id);

    expect(titles()).toEqual(['keep']);
  });

  it('ignores dismissing an unknown id', () => {
    service.show({ level: 'info', title: 'keep' });
    service.dismiss(999);
    expect(titles()).toEqual(['keep']);
  });

  it('has success() and error() shortcuts', () => {
    service.success('Saved', 'All good');
    service.error('Failed');

    expect(service.toasts()).toEqual([
      expect.objectContaining({ level: 'success', title: 'Saved', message: 'All good' }),
      expect.objectContaining({ level: 'error', title: 'Failed', message: undefined }),
    ]);
  });
});
