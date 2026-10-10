import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';

import { errorMessage } from '../../../core/auth/auth.interceptor';
import { AuthService } from '../../../core/auth/auth.service';
import { DemoUser } from '../../../core/models/models';
import { ToastService } from '../../../core/ui/toast.service';

const FLOW = [
  { icon: '📸', title: 'Drop a pile of bills', text: 'Photos, screenshots, PDFs - any order.' },
  { icon: '🧠', title: 'AI reads & sorts', text: 'Extracts, categorises, converts currency.' },
  { icon: '🛡️', title: 'Policy & duplicates', text: 'Flags issues and asks only what matters.' },
  { icon: '🚀', title: 'Ready to submit', text: 'A clean claim, routed for approval.' },
];

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html',
  styleUrl: './login.scss',
})
export class LoginPage {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly toast = inject(ToastService);

  protected readonly flow = FLOW;
  protected readonly demoUsers = signal<DemoUser[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly showPassword = signal(false);

  protected readonly username = signal('');
  protected readonly password = signal('');

  constructor() {
    this.auth.demoUsers().subscribe({ next: (users) => this.demoUsers.set(users), error: () => {} });
  }

  protected useDemo(user: DemoUser): void {
    this.username.set(user.username);
    this.password.set(user.password);
    this.error.set(null);
  }

  protected submit(): void {
    if (!this.username() || !this.password() || this.loading()) return;
    this.loading.set(true);
    this.error.set(null);
    this.auth.login(this.username().trim(), this.password()).subscribe({
      next: (res) => {
        this.toast.success(`Welcome back, ${res.user.name.split(' ')[0]}!`, 'You are signed in.');
        this.router.navigate(['/dashboard']);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(errorMessage(err, 'Unable to sign in'));
      },
    });
  }
}
