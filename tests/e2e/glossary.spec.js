// Stat definitions: one table (GLOSS in template.html) holds every stat the site shows, with its name, a plain sentence and
// the formula; the glossary page (#glossary, linked from every page's foot and the cover's) lists it all, in English and
// Turkish, and #glossary/<id> opens at one entry. A stat's label (table heading, tile, Leaders board, chart label) opens its
// entry in a card that never covers the number it explains; a tap elsewhere, the label again, Escape or a scroll closes it,
// and the keyboard reaches it. Every visible stat label on every page names an entry, and every entry has its Turkish.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled, go} from './site.js';

const card = page => page.evaluate(() => { const d = document.querySelector('#def'); return d.hidden ? null : {text: d.textContent, def: DEF_AT && DEF_AT.dataset.def}; });
const rect = (page, sel) => page.evaluate(s => { const r = document.querySelector(s).getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; }, sel);
const apart = (a, b) => a.bottom <= b.top || a.top >= b.bottom || a.right <= b.left || a.left >= b.right;

test.describe('glossary page', () => {
  for (const [name, use, lang] of [['desktop', DESKTOP, 'en'], ['phone', PHONE, 'tr']]) {
    test(`every entry, from the foot of a page (${name}, ${lang})`, async ({page}, info) => {
      await page.setViewportSize(use.viewport);
      const problems = await prepare(page, {lang});
      await page.goto('./#standings');
      await settled(page);
      await page.click('.wrap > .foot a[href="#glossary"]');
      await page.waitForFunction(() => document.body.classList.contains('gl-on') && document.querySelectorAll('#gl [data-id]').length > 0);
      await settled(page);
      const shown = await page.evaluate(() => [...document.querySelectorAll('#gl [data-id]')].map(x => x.dataset.id));
      expect(shown).toEqual(await page.evaluate(() => GLOSS.flatMap(([, rows]) => rows.map(r => r[0]))));
      expect(await page.locator('#gl .gl-g').count()).toBe(await page.evaluate(() => GLOSS.length));
      expect(await page.textContent('#gl-ts code')).toBe(lang === 'tr' ? 'Sayı ÷ (2 × (denenen şut + 0,44 × denenen SA))' : 'PTS ÷ (2 × (FGA + 0.44 × FTA))');
      // the phone tab bar keeps its five tabs, none of them lit
      expect(await page.locator('#tabbar > *').count()).toBe(5);
      await page.screenshot({path: info.outputPath(`glossary-${name}-${lang}.png`), fullPage: name === 'desktop'});
      await go(page, '#glossary/poss', () => !!document.querySelector('#gl-poss.hit'));
      const top = (await rect(page, '#gl-poss')).top;
      expect(top).toBeGreaterThanOrEqual(0);
      expect(top).toBeLessThan(220);
      expect(problems, 'the page reported errors').toEqual([]);
    });
  }

  test('the cover links it too', async ({page}) => {
    await page.setViewportSize(DESKTOP.viewport);
    const problems = await prepare(page);
    await page.goto('./');
    await settled(page);
    await page.click('.cv-foot a[href="#glossary"]');
    await page.waitForFunction(() => document.body.classList.contains('gl-on'));
    expect(problems, 'the page reported errors').toEqual([]);
  });
});

test('every entry has its Turkish: name, sentence, formula, label and group', async ({page}) => {
  await prepare(page);
  await page.goto('./#glossary');
  await settled(page);
  const missing = await page.evaluate(() => {
    const keys = GLOSS.flatMap(([group, rows]) => [group, ...rows.flatMap(r => [r[1], r[2], r[3], r[4]].filter(Boolean))]).concat(['Glossary']);
    return [...new Set(keys)].filter(k => T.tr[k] == null || T.tr[k] === '');
  });
  expect(missing, 'Turkish strings missing from lang/tr.json').toEqual([]);
});

for (const [name, use, lang] of [['desktop', DESKTOP, 'en'], ['phone', PHONE, 'tr']]) {
  test(`a stat label opens its card; a tap elsewhere, the label again, a scroll and Escape close it (${name}, ${lang})`, async ({page}, info) => {
    await page.setViewportSize(use.viewport);
    const problems = await prepare(page, {lang});
    const tap = sel => page.locator(sel).first().click();
    await page.goto('./');
    await settled(page);
    const code = await page.evaluate(() => META.clubs[0].code);
    await go(page, `#${code}`, () => document.body.classList.contains('cb-on'));
    await go(page, `#${code}/${await page.evaluate(() => team().players.find(p => p.cur && p.cur.tot && p.cur.tot.gp).pid)}`, () => document.querySelectorAll('#tiles .tile[data-def]').length === 7 && !document.querySelector('#role').hidden);
    expect(await card(page)).toBeNull();
    // the role strip's true shooting: the card names it, shows the formula with the reader's decimal mark, and sits clear of its number
    await page.locator('#role [data-def^="ts"]').scrollIntoViewIfNeeded();
    await tap('#role [data-def^="ts"]');
    let c = await card(page);
    expect(c.def).toMatch(/^ts/);
    expect(c.text).toContain(lang === 'tr' ? 'Gerçek şut yüzdesi' : 'True shooting percentage');
    expect(c.text).toContain(lang === 'tr' ? '0,44' : '0.44');
    const box = await rect(page, '#def'), num = await page.evaluate(() => { const r = document.querySelector('#role [data-def^="ts"]').closest('[data-def-box]').querySelector('b').getBoundingClientRect(); return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; });
    expect(apart(box, num), 'the card sits clear of the number').toBe(true);
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(use.viewport.width);
    await page.screenshot({path: info.outputPath(`card-${name}-${lang}.png`)});
    // a tap elsewhere closes it; the same label twice opens and closes it; a scroll closes it
    await tap('#nm');
    expect(await card(page)).toBeNull();
    await page.locator('#tiles .tile').first().scrollIntoViewIfNeeded();
    await tap('#tiles .tile');
    expect((await card(page)).def).toMatch(/^pts/);
    await tap('#tiles .tile');
    expect(await card(page)).toBeNull();
    await tap('#tiles .tile');
    await page.mouse.wheel(0, 400);
    await page.waitForFunction(() => document.querySelector('#def').hidden);
    // the card's link opens the glossary at the entry
    await page.locator('#tiles .tile').first().scrollIntoViewIfNeeded();
    await tap('#tiles .tile');
    await tap('#def a');
    await page.waitForFunction(() => document.body.classList.contains('gl-on') && !!document.querySelector('#gl-pts.hit'));
    expect(await card(page)).toBeNull();
    // a heading that sorts keeps sorting and opens its card over the redrawn table; Escape closes it
    await go(page, '#standings/ratings/net', () => document.querySelectorAll('#st-rt-body tr').length > 5);
    await tap('#st-rt-head th[data-k="drtg"] button');
    await expect(page.locator('#st-rt-head th[data-k="drtg"]')).toHaveAttribute('aria-sort', 'ascending');
    expect((await card(page)).def).toBe('drtg poss rank');
    const th = await rect(page, '#st-rt-head th[data-k="drtg"]');
    expect((await rect(page, '#def')).bottom, 'a heading’s card sits above it, clear of the column').toBeLessThanOrEqual(th.top);
    await page.keyboard.press('Escape');
    expect(await card(page)).toBeNull();
    // Leaders: a board out of view opens its table; the board in view opens its card with the floor
    await go(page, '#leaders', () => document.querySelectorAll('#ld-wrap tbody tr').length > 0);
    await tap('.ld-board[data-k="fg3p"]');
    await page.waitForFunction(() => document.querySelector('.ld-board[data-k="fg3p"]').classList.contains('on'));
    expect(await card(page)).toBeNull();
    await page.evaluate(() => scrollTo(0, 0));
    await tap('.ld-board[data-k="fg3p"]');
    c = await card(page);
    expect(c.def).toBe('fg3p q3p');
    expect(c.text).toContain('15');
    expect(problems, 'the page reported errors').toEqual([]);
  });
}

test('the keyboard reaches a label, Enter opens its card with the focus on its link, Escape closes it and gives the focus back', async ({page}) => {
  await page.setViewportSize(DESKTOP.viewport);
  const problems = await prepare(page);
  await page.goto('./#lineups');
  await settled(page);
  await page.waitForFunction(() => document.querySelectorAll('#ln-wrap thead th[data-def]').length > 4);
  await page.focus('#ln-wrap th[data-def="poss"]');
  await page.keyboard.press('Enter');
  expect((await card(page)).text).toContain('0.44');
  expect(await page.evaluate(() => document.activeElement.closest('#def') !== null)).toBe(true);
  await page.keyboard.press('Escape');
  expect(await card(page)).toBeNull();
  expect(await page.evaluate(() => document.activeElement.dataset.def)).toBe('poss');
  // Tab from the card goes back to the label
  await page.keyboard.press(' ');
  await page.keyboard.press('Tab');
  expect(await card(page)).toBeNull();
  expect(await page.evaluate(() => document.activeElement.dataset.def)).toBe('poss');
  expect(problems, 'the page reported errors').toEqual([]);
});

// on a 375px phone, a card never covers the number it explains: tiles, splits, the role strip and table headings
test('on a 375px phone no card covers its number', async ({page}) => {
  await page.setViewportSize({width: 375, height: 740});
  const problems = await prepare(page, {lang: 'tr'});
  await page.goto('./');
  await settled(page);
  const code = await page.evaluate(() => META.clubs[0].code);
  await go(page, `#${code}`, () => document.body.classList.contains('cb-on'));
  await go(page, `#${code}/${await page.evaluate(() => team().players.find(p => p.cur && p.cur.tot && p.cur.tot.gp).pid)}`, () => document.querySelectorAll('#tiles .tile[data-def]').length === 7);
  const labels = ['#tiles .tile:nth-child(3)', '#splits .split:nth-child(2) .k', '#role > div:nth-child(4) > span', '.xfg-row > div:nth-child(3)', '#trend thead th[data-def="usg"]'];
  for (const sel of labels) {
    await page.locator(sel).scrollIntoViewIfNeeded();
    await page.locator(sel).click();
    expect(await card(page), sel).not.toBeNull();
    const box = await rect(page, '#def');
    // the number: inside the label's box, or under a heading the first row's cell in its column
    const nums = await page.evaluate(s => { const el = document.querySelector(s), b = el.closest('[data-def-box]') || el, rs = [];
      if (el.tagName === 'TH') { const i = [...el.parentElement.children].indexOf(el), td = el.closest('table').querySelector(`tbody tr:not(.dnp) td:nth-child(${i + 1})`); if (td) rs.push(td.getBoundingClientRect()); rs.push(el.getBoundingClientRect()); }
      else for (const n of b.querySelectorAll('b')) rs.push(n.getBoundingClientRect());
      return rs.map(r => ({top: r.top, bottom: r.bottom, left: r.left, right: r.right})); }, sel);
    expect(nums.length, sel).toBeGreaterThan(0);
    for (const n of nums) expect(apart(box, n), `the card over ${sel} covers its number`).toBe(true);
    expect(box.left).toBeGreaterThanOrEqual(0);
    expect(box.right).toBeLessThanOrEqual(375);
    await page.keyboard.press('Escape');
  }
  expect(problems, 'the page reported errors').toEqual([]);
});

// ---- coverage: every visible stat label on every page names entries of the glossary. Plain headings (who, which club,
// when, against whom, the jersey number and the row's place) and the score-by-period table name no stat.
const PLAIN = new Set(['', '#', 'Player', 'Club', 'Date', 'Rd', 'Opponent', 'Result', 'Position', 'Age', 'Height', 'Game', 'Line', 'Metric']);
const LABELS = ['table thead th', '.tile', '.st-tile', '.split .k', '.xfg-row > div', '#role > div > span', '.gauge .k', '.ld-board', '.gm-ldr-c h3', '.gm-cmp .lab', '.cmp-m .lab', '#cmp-table tbody td:first-child', '#diet-cap', '#ap-cap', '#cmp-diet-t', '.cv-lead .cv-th > span'];
test('every visible stat label on every page opens a glossary entry', async ({page}) => {
  test.setTimeout(240_000);
  await page.setViewportSize(DESKTOP.viewport);
  const problems = await prepare(page);
  await page.goto('./');
  await settled(page);
  const meta = await page.evaluate(() => ({club: META.clubs[0].code, game: META.games[0][0]}));
  const visits = [
    ['cover', '#', () => document.body.classList.contains('cv-on') && document.querySelectorAll('.cv-tbl tbody tr').length > 0],
    ['club', `#${meta.club}`, () => document.querySelectorAll('#club .cb-tab tbody tr').length >= 8],
    ['player', null, () => !document.querySelector('#role').hidden && document.querySelectorAll('#log tbody tr').length > 0],
    ['compare', '#compare', () => document.querySelector('#cmp-panel')?.getBoundingClientRect().height > 200],
    ['standings', '#standings', () => document.querySelectorAll('#st-body tr').length > 5],
    ['standings ratings', '#standings/ratings', () => document.querySelectorAll('#st-rt-body tr').length > 5],
    ['games', '#games', () => document.querySelectorAll('#gs-list a').length > 0],
    ['game', `#game/${meta.game}`, () => document.querySelectorAll('#game .gm-ldr-c').length === 4],
    ['game box', `#game/${meta.game}/box`, () => document.querySelectorAll('#game .gm-box tbody tr').length > 8],
    ['game shots', `#game/${meta.game}/shots`, () => document.querySelectorAll('#game .gm-shooters tbody tr').length > 0],
    ['game fives', `#game/${meta.game}/fives`, () => document.querySelectorAll('#game .gm-fives tbody tr').length > 0],
    ['lineups', '#lineups', () => document.querySelectorAll('#ln-wrap tbody tr').length > 0],
    ['lineups on/off', 'tab:onoff', () => document.querySelectorAll('#ln-wrap tbody tr').length > 0],
    ['lineups by game', 'tab:game', () => document.querySelectorAll('#ln-wrap tbody tr').length > 0],
    ['glossary', '#glossary', () => document.querySelectorAll('#gl [data-id]').length > 50],
  ];
  const groups = ['scoring', 'rebounds', 'playmaking', 'shooting', 'efficiency', 'advanced'];
  for (const g of groups) visits.push([`leaders ${g}`, `leaders:${g}`, () => document.querySelectorAll('#ld-wrap tbody tr').length > 0]);
  const bad = [], checked = [];
  for (const [name, where, probe] of visits) {
    if (where === null) await go(page, `#${meta.club}/${await page.evaluate(() => team().players.find(p => p.cur && p.cur.tot && p.cur.tot.gp).pid)}`, probe);
    else if (where.startsWith('tab:')) { await page.click(`#ln-tabs button[data-v="${where.slice(4)}"]`); if (where === 'tab:game') await page.evaluate(c => { const s = document.querySelector('#ln-club'); s.value = c; s.dispatchEvent(new Event('change', {bubbles: true})); }, meta.club); await page.waitForFunction(probe); }
    else if (where.startsWith('leaders:')) { if (!(await page.evaluate(() => document.body.classList.contains('ld-on')))) await go(page, '#leaders', () => document.querySelectorAll('#ld-wrap tbody tr').length > 0); await page.click(`#ld-group button[data-v="${where.slice(8)}"]`); await page.waitForFunction(probe); }
    else await go(page, where, probe);
    // the compare page draws its head-to-head once a second player is picked
    if (name === 'compare') {
      await page.evaluate(() => { const s = document.querySelector('#cmp-oclub'), o = [...s.options].find(x => x.value && x.value !== state.team); s.value = o.value; s.dispatchEvent(new Event('change', {bubbles: true})); });
      await page.waitForFunction(() => !document.querySelector('#cmp-page').hidden && document.querySelectorAll('#cmp-h2h .cmp-m').length > 5);
    }
    const found = await page.evaluate(([sels, plain]) => {
      const skip = new Set(plain), ids = new Set(Object.keys(DEF)), out = [];
      let n = 0;
      for (const el of document.querySelectorAll(sels.join(','))) {
        if (!el.getClientRects().length || el.closest('[hidden], .gm-q')) continue;
        const txt = el.textContent.replace(/[▼▲]/g, '').trim();
        if (el.tagName === 'TH' && skip.has(txt)) continue;
        n++;
        const own = el.dataset.def ? el : el.querySelector(':scope > [data-def]');
        if (!own || !own.dataset.def.split(' ').every(id => ids.has(id))) out.push(txt.slice(0, 40) || el.className);
      }
      return {out, n};
    }, [LABELS, [...PLAIN]]);
    for (const f of found.out) bad.push(`${name}: ${f}`);
    checked.push(`${name} ${found.n}`);
    expect(found.n, `stat labels found on ${name}`).toBeGreaterThan(['games', 'glossary'].includes(name) ? -1 : 2);
  }
  console.log(`stat labels checked: ${checked.join(', ')}`);
  expect(bad, 'labels without a glossary entry').toEqual([]);
  expect(problems, 'the page reported errors').toEqual([]);
});
