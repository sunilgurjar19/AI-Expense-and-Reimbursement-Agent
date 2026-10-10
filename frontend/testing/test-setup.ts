/**
 * Global hygiene for the unit-test run (registered via `setupFiles` in angular.json).
 *
 * TestBed is reset automatically after each test, but browser state (localStorage, globals,
 * prototypes) and Vitest helpers (fake timers, spies, stubs) are not - reset them here so every
 * test starts from a clean slate, whatever the previous test in the file did.
 */

// jsdom has no layout engine and does not implement element scrolling; the chat panel calls it
// to keep the newest message in view. Specs can still spy on it.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = function scrollTo() {};
}

afterEach(() => {
  localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
