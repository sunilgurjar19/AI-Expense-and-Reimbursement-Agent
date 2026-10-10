import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { ToastService } from '../ui/toast.service';
import { AuthService } from './auth.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const toast = inject(ToastService);
  const token = auth.token();
  const request = token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;

  return next(request).pipe(
    catchError((error: HttpErrorResponse) => {
      const isLogin = req.url.endsWith('/auth/login');
      if (error.status === 401 && !isLogin && auth.isAuthenticated()) {
        auth.logout();
        toast.show({ level: 'warning', title: 'Session expired', message: 'Please sign in again.' });
      } else if (error.status === 0) {
        toast.show({ level: 'error', title: 'Server unreachable', message: 'Is the FastAPI backend running?' });
      }
      return throwError(() => error);
    }),
  );
};

/** Extract a readable message from an API error. */
export function errorMessage(error: unknown, fallback = 'Something went wrong'): string {
  if (error instanceof HttpErrorResponse) {
    const detail = error.error?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return fallback;
}
