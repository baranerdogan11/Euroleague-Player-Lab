// Assist links (events.py ties every assist to the basket it set up): the club page's passing network and the player page's
// assist partners must tell the same story as the box score. For every player, the teammates he set up plus the few assists
// the play-by-play cannot tie to a basket make his box-score assists; a club's pairs from a passer who played only for that
// club add up to his own list; and a pair in the club's top connections reads the same on the passer's page.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled, go, noSidewaysScroll} from './site.js';

test.describe('desktop', () => {
  test.use(DESKTOP);
  test('passing network agrees with the box score and the player pages', async ({page}) => {
    test.setTimeout(180000);
    const problems = await prepare(page);
    await page.goto('./');
    await settled(page);
    const bad = await page.evaluate(async () => {
      const out = [];
      for (const code of Object.keys(CLUBS)) {
        const d = await (await fetch(`${META.path}${code}.json?v=${encodeURIComponent(META.built || '')}`)).json();
        const pairs = (d.assists && d.assists.pairs) || [];
        for (const p of d.players) {
          const P = p.cur.partners, ast = p.cur.tot.ast || 0;
          if (!P) { if (ast) out.push(`${code} ${p.pid}: ${ast} assists but no partners`); continue; }
          const to = P.to.reduce((s, e) => s + e[2], 0);
          if (to + P.x !== ast || P.x < 0) out.push(`${code} ${p.pid}: partners ${to} + ${P.x} untied != ${ast} box-score assists`);
          if (p.cur.games.every(g => g.own === code)) {
            const club = pairs.filter(q => q[0] === p.pid).reduce((s, q) => s + q[2], 0);
            if (club !== to) out.push(`${code} ${p.pid}: club network ${club} != his list ${to}`);
          }
        }
      }
      return out;
    });
    expect(bad).toEqual([]);
    for (const club of ['MAD', 'ULK', 'PAN']) {
      await go(page, `#${club}`, () => document.querySelectorAll('#an .an-n').length > 1);
      // every player who has played for the club, and everyone in its pairs, has a square on the ring
      const missing = await page.evaluate(() => { const on = new Set([...document.querySelectorAll('#an .an-n')].map(n => n.dataset.p)), d = team();
        return [...d.players.filter(p => p.cur.tot.gp).map(p => p.pid), ...d.assists.pairs.flatMap(q => [q[0], q[1]])].filter(pid => !on.has(pid)); });
      expect(missing, `${club}: players missing from the network`).toEqual([]);
      const first = await page.evaluate(() => { const r = document.querySelector('#an-top tbody tr'); return {a: r.dataset.a, b: r.dataset.b, n: r.querySelector('td.k').textContent.trim()}; });
      // tapping the passer keeps only his arrows, each labelled with its count; his top pair among them
      await page.click(`#an .an-n[data-p="${first.a}"]`);
      await expect(page.locator(`#an .an-n[data-p="${first.a}"]`)).toHaveAttribute('aria-pressed', 'true');
      await expect(page.locator(`#an .an-e.out[data-a="${first.a}"][data-b="${first.b}"] text`)).toHaveText(first.n);
      await page.click(`#an .an-n[data-p="${first.a}"]`);
      await expect(page.locator('#an.focus')).toHaveCount(0);
      if (!await page.locator(`#an-top a[href="#${club}/${first.a}"]`).count()) continue;   // the passer has left the club
      await go(page, `#${club}/${first.a}`, () => !document.querySelector('#ap').hidden);
      await expect(page.locator(`#ap .ap-col:first-child .ap-r[data-pid="${first.b}"] b`)).toHaveText(first.n);
    }
    // the network wears each club's colours: two clubs never draw their arrows in the same colour, and each reads on the paper
    const ink = {};
    for (const club of ['MAD', 'PAN', 'ULK']) {
      await go(page, `#${club}`, () => document.querySelectorAll('#an .an-e path').length > 1);
      ink[club] = await page.evaluate(() => { const p = document.querySelector('#an .an-e path'), n = document.querySelector('#an .an-n rect');
        return {arrow: getComputedStyle(p).stroke, node: getComputedStyle(n).fill, bg: getComputedStyle(document.body).backgroundColor}; });
    }
    expect(new Set(Object.values(ink).map(v => v.arrow)).size, 'arrows in each club\'s own colour').toBe(3);
    const rgb = s => s.match(/\d+/g).slice(0, 3).map(Number), L = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * r + .7152 * g + .0722 * b; };
    const cr = (a, b) => { const x = L(rgb(a)), y = L(rgb(b)); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); };
    for (const [club, v] of Object.entries(ink)) for (const k of ['arrow', 'node']) expect(cr(v[k], v.bg), `${club} ${k} reads on the page`).toBeGreaterThanOrEqual(2.9);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});

for (const [lang, theme] of [['en', 'light'], ['tr', 'dark']]) test.describe(`phone ${lang}`, () => {
  test.use(PHONE);
  test('passing network and partners fit a phone', async ({page}) => {
    const problems = await prepare(page, {lang, theme});
    await page.goto('./');
    await settled(page);
    await go(page, '#MAD', () => document.querySelectorAll('#an .an-n').length > 1);
    await page.locator('#an').scrollIntoViewIfNeeded();
    await noSidewaysScroll(page, 'club page');
    // every name on the ring stays inside the drawing
    const cut = await page.evaluate(() => { const svg = document.querySelector('#an'), vb = svg.viewBox.baseVal;
      return [...svg.querySelectorAll('.an-n .nm')].map(t => ({t: t.textContent, b: t.getBBox()})).filter(({b}) => b.x < vb.x || b.x + b.width > vb.x + vb.width || b.y < vb.y || b.y + b.height > vb.y + vb.height).map(x => x.t); });
    expect(cut, 'names cut off the network').toEqual([]);
    const pid = await page.locator('#an-top tbody tr').first().getAttribute('data-a');
    await page.locator(`#an .an-n[data-p="${pid}"]`).tap();
    await expect(page.locator('#an.focus')).toHaveCount(1);
    await page.screenshot({path: test.info().outputPath(`network-390-${lang}-${theme}.png`), fullPage: false});
    await go(page, `#MAD/${pid}`, () => !document.querySelector('#ap').hidden);
    await page.locator('#ap').scrollIntoViewIfNeeded();
    await noSidewaysScroll(page, 'player page');
    const box = await page.locator('#ap').boundingBox();
    expect(box && box.x >= 0 && box.x + box.width <= 390, 'assist partners inside the screen').toBe(true);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
