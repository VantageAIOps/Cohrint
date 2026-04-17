/**
 * Cohrint — Shared Theme System
 *
 * Include this script in <head> of every page (before styles render)
 * to prevent flash-of-wrong-theme.
 *
 * Usage: <script src="/theme.js"></script>
 *
 * API:
 *   cohrintTheme.get()    → 'dark' | 'light'
 *   cohrintTheme.set(t)   → sets theme + persists
 *   cohrintTheme.toggle() → toggles dark ↔ light
 */
(function() {
  var KEY = 'cohrint_theme';
  var theme = localStorage.getItem(KEY) || 'light';
  document.documentElement.setAttribute('data-theme', theme);

  window.cohrintTheme = {
    get: function() { return localStorage.getItem(KEY) || 'light'; },
    set: function(t) {
      document.documentElement.setAttribute('data-theme', t);
      localStorage.setItem(KEY, t);
      // Update all toggle buttons on the page
      document.querySelectorAll('[data-theme-toggle]').forEach(function(btn) {
        btn.textContent = t === 'dark' ? '☾' : '☀';
        btn.title = t === 'light' ? 'Switch to dark theme' : 'Switch to light theme';
      });
    },
    toggle: function() {
      var current = this.get();
      this.set(current === 'dark' ? 'light' : 'dark');
    }
  };
})();
