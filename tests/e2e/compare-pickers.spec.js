// The compare page's four pickers (club and player on each side) open, show every option on screen, pick by tap, click
// and keyboard, and close. Their lists used to be cut off at the bottom edge of the hero block.
import {test, expect} from '@playwright/test';
import {DESKTOP, PHONE, prepare, settled, noSidewaysScroll} from './site.js';

const btnOf = (page, id) => page.locator(`.dd:has(#${id}-list) .dd-btn`);

// the open list lies inside the viewport, above the phone tab bar, and its first and last options can be hit where they are drawn
async function reachable(page, id) {
  const list = page.locator(`#${id}-list`);
  await expect(list).toBeVisible();
  const r = await list.evaluate(l => {
    const tb = document.querySelector('.tabbar'), floor = tb && getComputedStyle(tb).display !== 'none' ? tb.getBoundingClientRect().top : innerHeight;
    const hit = li => { li.scrollIntoView({block: 'nearest'}); const b = li.getBoundingClientRect(); const e = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2); return !!e && li.contains(e); };
    const box = l.getBoundingClientRect(), lis = [...l.children];
    return {n: lis.length, top: box.top, bottom: box.bottom, floor, first: hit(lis[0]), last: hit(lis[lis.length - 1])};
  });
  expect(r.n, `${id} has options`).toBeGreaterThan(1);
  expect(r.top, `${id} list starts on screen`).toBeGreaterThanOrEqual(0);
  expect(r.bottom, `${id} list ends above the screen edge and tab bar`).toBeLessThanOrEqual(r.floor + 1);
  expect(r.first, `${id} first option can be hit`).toBe(true);
  expect(r.last, `${id} last option can be hit`).toBe(true);
}

// the selected row reads against the list background (WCAG AA for text)
async function selectedReadable(page, id) {
  const ratio = await page.locator(`#${id}-list li[aria-selected="true"]`).evaluate(li => {
    const rgb = c => c.match(/[\d.]+/g).slice(0, 3).map(Number);
    const lum = ([r, g, b]) => { const f = v => (v /= 255) <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
    let el = li, bg = 'rgba(0, 0, 0, 0)';
    while (el && /rgba\(.*, 0\)|transparent/.test(bg)) { bg = getComputedStyle(el).backgroundColor; el = el.parentElement; }
    const a = lum(rgb(getComputedStyle(li).color)), b = lum(rgb(bg));
    return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
  });
  expect(ratio, `${id} selected row contrast`).toBeGreaterThanOrEqual(4.5);
}

const cases = [
  {name: 'desktop en light', use: DESKTOP, lang: 'en', theme: 'light', tap: false},
  {name: 'desktop tr dark', use: DESKTOP, lang: 'tr', theme: 'dark', tap: false},
  {name: 'phone en light', use: PHONE, lang: 'en', theme: 'light', tap: true},
  {name: 'phone tr dark', use: PHONE, lang: 'tr', theme: 'dark', tap: true},
];

for (const c of cases) test.describe(c.name, () => {
  test.use(c.use);
  test('compare pickers open, show every option, pick and close', async ({page}) => {
    const problems = await prepare(page, {lang: c.lang, theme: c.theme});
    await page.goto('./#compare');
    await settled(page);
    await expect(btnOf(page, 'cmp-club')).toBeVisible();
    const press = async id => { const b = btnOf(page, id); await b.scrollIntoViewIfNeeded(); if (c.tap) await b.tap(); else await b.click(); };

    // left side: both lists open whole, the selected row is readable, Escape and a second press close them
    for (const id of ['cmp-club', 'cmp-me']) {
      await press(id);
      await reachable(page, id);
      await selectedReadable(page, id);
      await page.keyboard.press('Escape');
      await expect(page.locator(`#${id}-list`)).toBeHidden();
      await press(id);
      await expect(page.locator(`#${id}-list`)).toBeVisible();
      await press(id);
      await expect(page.locator(`#${id}-list`)).toBeHidden();
    }

    // right side: pick another club from its list, which opens that club's player
    const mine = await page.locator('#cmp-club').inputValue();
    await press('cmp-oclub');
    await reachable(page, 'cmp-oclub');
    const other = page.locator('#cmp-oclub-list li').filter({hasNot: page.locator(`img[src*="/${mine}."]`)}).nth(1);
    if (c.tap) await other.tap(); else await other.click();
    await expect(page.locator('#cmp-oclub-list')).toBeHidden();
    await expect(btnOf(page, 'cmp-opp')).toBeEnabled();
    await expect(page.locator('#cmp-opp')).not.toHaveValue('');

    // the opponent's player list: open whole, then a pick by keyboard
    await press('cmp-opp');
    await reachable(page, 'cmp-opp');
    await page.keyboard.press('Escape');
    const before = await page.locator('#cmp-opp').inputValue();
    await btnOf(page, 'cmp-opp').focus();
    await page.keyboard.press('ArrowDown');
    await expect(page.locator('#cmp-opp-list')).toBeVisible();
    const n = await page.locator('#cmp-opp-list li').count();
    const idx = await page.locator('#cmp-opp').evaluate(s => s.selectedIndex);
    if (idx === n - 1) await page.keyboard.press('ArrowUp');
    await page.keyboard.press('Enter');
    await expect(page.locator('#cmp-opp-list')).toBeHidden();
    await expect(page.locator('#cmp-opp')).not.toHaveValue(before);
    await expect(btnOf(page, 'cmp-opp')).toBeFocused();

    // the left player by keyboard too: the hero follows the pick
    const meBefore = await page.locator('#cmp-me').inputValue();
    await btnOf(page, 'cmp-me').focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(page.locator('#cmp-me')).not.toHaveValue(meBefore);
    const shown = await page.locator('#cmp-me').evaluate(s => s.options[s.selectedIndex].text.replace(/^#\S+\s/, '').split(' ').pop().toUpperCase());
    await expect(page.locator('#cmp-who-l')).toContainText(shown, {ignoreCase: true});

    // a tap or click outside closes an open list
    await press('cmp-oclub');
    await expect(page.locator('#cmp-oclub-list')).toBeVisible();
    await page.mouse.click(5, 300);
    await expect(page.locator('#cmp-oclub-list')).toBeHidden();

    await noSidewaysScroll(page, `compare ${c.name}`);
    expect(problems, 'the page reported errors').toEqual([]);
  });
});
