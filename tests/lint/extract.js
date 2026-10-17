// Copies the page's script out of template.html into tests/lint/.out/app.js so ESLint and the TypeScript checker can read
// it as a file. The build placeholders become typed stand-ins (the real values are injected by build.py). Line numbers
// match template.html: line N of app.js is line N of the template, so an error points straight at the template.
import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const tpl = readFileSync(join(ROOT, 'template.html'), 'utf8');
const open = tpl.lastIndexOf('<script>'), close = tpl.indexOf('</script>', open);
if (open < 0 || close < 0) throw new Error('template.html: no <script> block found');
const before = tpl.slice(0, open + '<script>'.length).split('\n').length - 1;   // the template line the script starts on, less one
const js = tpl.slice(open + '<script>'.length, close)
  .replace('/*META*/', '/** @type {any} */ ({})')
  .replace('/*TR*/{}', '/** @type {Record<string, string>} */ ({})');
mkdirSync(join(ROOT, 'tests/lint/.out'), {recursive: true});
writeFileSync(join(ROOT, 'tests/lint/.out/app.js'), '\n'.repeat(before) + js);
