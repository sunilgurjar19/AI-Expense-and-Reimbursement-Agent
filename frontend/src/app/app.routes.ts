import { Routes, UrlMatchResult, UrlSegment } from '@angular/router';

import { authGuard, guestGuard, managerGuard } from './core/auth/auth.guards';

export function agentMatcher(segments: UrlSegment[]): UrlMatchResult | null {
  if (segments[0]?.path !== 'agent' || segments.length > 2) return null;
  return { consumed: segments, posParams: segments[1] ? { id: segments[1] } : {} };
}

export const routes: Routes = [
  {
    path: 'login',
    canActivate: [guestGuard],
    title: 'Sign in',
    loadComponent: () => import('./features/auth/login/login').then((m) => m.LoginPage),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./layout/shell/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'dashboard' },
      {
        path: 'dashboard',
        title: 'Dashboard',
        loadComponent: () => import('./features/dashboard/dashboard').then((m) => m.DashboardPage),
      },
      {
        // One route for "/agent" (new, unsaved claim) and "/agent/:id", so the workspace
        // stays mounted when a new claim is first saved and receives its id.
        matcher: agentMatcher,
        title: 'Expense agent',
        loadComponent: () =>
          import('./features/agent/agent-workspace').then((m) => m.AgentWorkspace),
      },
      {
        path: 'claims',
        title: 'My claims',
        loadComponent: () =>
          import('./features/claims/claims-list/claims-list').then((m) => m.ClaimsListPage),
      },
      {
        path: 'claims/:id',
        title: 'Claim',
        loadComponent: () =>
          import('./features/claims/claim-detail/claim-detail').then((m) => m.ClaimDetailPage),
      },
      {
        path: 'approvals',
        title: 'Approvals',
        canActivate: [managerGuard],
        loadComponent: () =>
          import('./features/approvals/approvals-list').then((m) => m.ApprovalsListPage),
      },
      {
        path: 'approvals/:id',
        title: 'Review claim',
        canActivate: [managerGuard],
        loadComponent: () =>
          import('./features/claims/claim-detail/claim-detail').then((m) => m.ClaimDetailPage),
        data: { mode: 'approval' },
      },
      {
        path: 'settings',
        title: 'Settings',
        loadComponent: () => import('./features/settings/settings').then((m) => m.SettingsPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
