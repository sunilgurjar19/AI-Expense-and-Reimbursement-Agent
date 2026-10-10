import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { App } from './app';
import { ToastService } from './core/ui/toast.service';

describe('App', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideZonelessChangeDetection(), provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
  });

  it('hosts the router outlet and the global toast stack', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('router-outlet')).not.toBeNull();
    expect(host.querySelector('app-toast-stack')).not.toBeNull();
  });

  it('shows toasts raised anywhere in the app', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    TestBed.inject(ToastService).show({ level: 'success', title: 'Claim approved', duration: 60_000 });
    await fixture.whenStable();

    expect((fixture.nativeElement as HTMLElement).querySelector('.toast strong')!.textContent).toBe('Claim approved');
  });
});
