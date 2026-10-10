import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastStack } from './layout/toast-stack';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, ToastStack],
  template: `
    <router-outlet />
    <app-toast-stack />
  `,
})
export class App {}
