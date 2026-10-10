import { Route, UrlSegment } from '@angular/router';

import { agentMatcher, routes } from './app.routes';
import { authGuard, guestGuard, managerGuard } from './core/auth/auth.guards';
import { AgentWorkspace } from './features/agent/agent-workspace';
import { ApprovalsListPage } from './features/approvals/approvals-list';
import { LoginPage } from './features/auth/login/login';
import { ClaimDetailPage } from './features/claims/claim-detail/claim-detail';
import { ClaimsListPage } from './features/claims/claims-list/claims-list';
import { DashboardPage } from './features/dashboard/dashboard';
import { SettingsPage } from './features/settings/settings';
import { Shell } from './layout/shell/shell';

const segments = (...paths: string[]) => paths.map((path) => new UrlSegment(path, {}));

describe('agentMatcher', () => {
  it('matches "/agent" (new claim) without an id', () => {
    const url = segments('agent');
    expect(agentMatcher(url)).toEqual({ consumed: url, posParams: {} });
  });

  it('matches "/agent/:id" and exposes the id segment', () => {
    const url = segments('agent', 'c-123');
    const result = agentMatcher(url);

    expect(result?.consumed).toBe(url);
    expect(result?.posParams?.['id'].path).toBe('c-123');
  });

  it('rejects deeper paths under /agent', () => {
    expect(agentMatcher(segments('agent', 'c-123', 'extra'))).toBeNull();
  });

  it.each([['claims'], ['agents'], ['dashboard', 'agent']])('rejects other paths (%s)', (...paths) => {
    expect(agentMatcher(segments(...paths))).toBeNull();
  });

  it('rejects the empty path', () => {
    expect(agentMatcher([])).toBeNull();
  });
});

describe('routes', () => {
  const shell = routes.find((r) => r.path === '' && r.children)!;
  const child = (path: string) => shell.children!.find((r) => r.path === path)!;
  const agentRoute = shell.children!.find((r) => r.matcher === agentMatcher)!;
  const load = (route: Route) => (route.loadComponent as () => Promise<unknown>)();

  it('lets only signed-out users reach the login page', async () => {
    const login = routes.find((r) => r.path === 'login')!;
    expect(login.canActivate).toEqual([guestGuard]);
    expect(await load(login)).toBe(LoginPage);
  });

  it('protects the application shell with the auth guard', async () => {
    expect(shell.canActivate).toEqual([authGuard]);
    expect(await load(shell)).toBe(Shell);
  });

  it('redirects the root to the dashboard and unknown URLs to the root', () => {
    expect(shell.children![0]).toEqual({ path: '', pathMatch: 'full', redirectTo: 'dashboard' });
    expect(routes.at(-1)).toEqual({ path: '**', redirectTo: '' });
  });

  it.each([
    ['dashboard', DashboardPage],
    ['claims', ClaimsListPage],
    ['claims/:id', ClaimDetailPage],
    ['settings', SettingsPage],
  ])('lazy-loads the right page for "%s"', async (path, component) => {
    expect(await load(child(path))).toBe(component);
  });

  it('serves both /agent and /agent/:id from one workspace route', async () => {
    expect(await load(agentRoute)).toBe(AgentWorkspace);
  });

  it('restricts approvals to managers', async () => {
    expect(child('approvals').canActivate).toEqual([managerGuard]);
    expect(await load(child('approvals'))).toBe(ApprovalsListPage);
  });

  it('reuses the claim detail page in approval mode for managers', async () => {
    const review = child('approvals/:id');
    expect(review.canActivate).toEqual([managerGuard]);
    expect(review.data).toEqual({ mode: 'approval' });
    expect(await load(review)).toBe(ClaimDetailPage);
  });

  it('gives every page a browser title', () => {
    const pages = [routes.find((r) => r.path === 'login')!, ...shell.children!.filter((r) => !r.redirectTo)];
    for (const page of pages) {
      expect(page.title, page.path ?? 'agent').toEqual(expect.any(String));
    }
  });
});
