import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { seedSession } from '@testing/fakes';
import { makePublicConfig, makeUser } from '@testing/fixtures';

import { AuthService } from '../auth/auth.service';
import { PolicyStore } from './policy.store';

const CONFIG_URL = 'http://localhost:8100/api/config';

describe('PolicyStore', () => {
  let http: HttpTestingController;

  function setup(): PolicyStore {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    const store = TestBed.inject(PolicyStore);
    TestBed.tick(); // run the store's auth effect
    return store;
  }

  afterEach(() => http.verify());

  describe('before the config is available', () => {
    it('exposes safe defaults', () => {
      const store = setup();

      expect(store.config()).toBeNull();
      expect(store.currency()).toBe('INR');
      expect(store.agentName()).toBe('Agent');
      expect(store.categories()).toEqual([]);
      expect(store.category('travel')).toBeUndefined();
    });

    it('does not call the API while signed out', () => {
      setup();
      http.expectNone(CONFIG_URL);
    });
  });

  it('loads the public config immediately when a session already exists', () => {
    seedSession();
    const store = setup();

    http.expectOne(CONFIG_URL).flush(makePublicConfig({ currency: 'USD', agent_name: 'Rika' }));

    expect(store.currency()).toBe('USD');
    expect(store.agentName()).toBe('Rika');
    expect(store.categories().map((c) => c.key)).toEqual(['travel', 'meals', 'lodging']);
  });

  it('loads the public config as soon as the user signs in', () => {
    const store = setup();
    const auth = TestBed.inject(AuthService);

    auth.login('employee', 'employee123').subscribe();
    http
      .expectOne('http://localhost:8100/api/auth/login')
      .flush({ access_token: 't', token_type: 'bearer', user: makeUser() });
    TestBed.tick();

    http.expectOne(CONFIG_URL).flush(makePublicConfig());
    expect(store.config()).not.toBeNull();
  });

  describe('category lookup', () => {
    let store: PolicyStore;

    beforeEach(() => {
      seedSession();
      store = setup();
      http.expectOne(CONFIG_URL).flush(makePublicConfig());
    });

    it('finds a category rule by key', () => {
      expect(store.category('meals')).toEqual(expect.objectContaining({ key: 'meals', label: 'Meals' }));
    });

    it.each([null, undefined, '', 'unknown'])('returns undefined for %j', (key) => {
      expect(store.category(key)).toBeUndefined();
    });
  });

  it('refresh() re-fetches the config and updates derived values', () => {
    seedSession();
    const store = setup();
    http.expectOne(CONFIG_URL).flush(makePublicConfig({ currency: 'INR' }));

    store.refresh();
    http.expectOne(CONFIG_URL).flush(makePublicConfig({ currency: 'EUR' }));

    expect(store.currency()).toBe('EUR');
  });
});
