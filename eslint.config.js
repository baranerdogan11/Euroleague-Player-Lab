// ESLint over the page's script (copied out of template.html by tests/lint/extract.js), the service worker and the Node
// tests. Run: npm run lint
import js from '@eslint/js';
import globals from 'globals';

// the house style: `try { ... } catch (e) {}` around storage calls that may throw in a private window
const rules = {'no-empty': ['error', {allowEmptyCatch: true}], 'no-unused-vars': ['error', {caughtErrors: 'none', args: 'none'}]};

export default [
  {ignores: ['node_modules/', 'test-results/', 'playwright-report/']},
  {
    files: ['tests/lint/.out/app.js'],
    ...js.configs.recommended,
    languageOptions: {ecmaVersion: 2022, sourceType: 'script', globals: {...globals.browser, THREE: 'readonly'}},
    // a dead variable is reported but does not fail the check: the template carries a handful today (see the CI log)
    rules: {...js.configs.recommended.rules, ...rules, 'no-unused-vars': ['warn', {caughtErrors: 'none', args: 'none'}]},
  },
  {
    files: ['sw.js'],
    ...js.configs.recommended,
    languageOptions: {ecmaVersion: 2022, sourceType: 'script', globals: globals.serviceworker},
    rules: {...js.configs.recommended.rules, ...rules},
  },
  {
    // the browser tests: Node code whose page.evaluate callbacks run in the page, against the page's own globals
    files: ['tests/e2e/**/*.js'],
    ...js.configs.recommended,
    languageOptions: {ecmaVersion: 2022, sourceType: 'module', globals: {...globals.node, ...globals.browser, META: 'readonly', LANG: 'readonly', team: 'readonly', checkFresh: 'readonly'}},
    rules: {...js.configs.recommended.rules, ...rules},
  },
  {
    files: ['tests/**/*.js', 'eslint.config.js'],
    ignores: ['tests/lint/.out/**', 'tests/e2e/**'],
    ...js.configs.recommended,
    languageOptions: {ecmaVersion: 2022, sourceType: 'module', globals: globals.node},
    rules: {...js.configs.recommended.rules, ...rules},
  },
];
