// The same number must read the same on every page that shows it. For every club in last night's games, each player in
// the game's box score is checked against
//   his own page: the game log row for that game (minutes, points, rebounds, ... +/-), and his season averages
//   his club page: the roster's games, minutes, points, rebounds, assists and PIR a game
//   the leaders page: games, minutes and points a game (every player, qualified or not)
// All values are read from the drawn pages, so a formatting or rounding slip in one page is caught as well as a data one.
import {test, expect} from '@playwright/test';
import {DESKTOP, prepare, settled, go} from './site.js';

test.use(DESKTOP);

const num = s => parseFloat(String(s).replace(/^[^\d+-]+/, ''));   // "S30.8" (a starter's mark) -> 30.8, "+16" -> 16
const BOX_COLS = ['Min', 'Pts', 'Reb', 'Ast', 'Stl', 'Blk', 'Tov', '2P', '3P', 'FT', 'PIR', '+/-'];
const same = (a, b) => /\//.test(a) ? a === b : num(a) === num(b);   // made/attempted pairs as text, the rest as numbers

test("last night's players agree across game, player, club and leaders pages", async ({page}) => {
  const problems = await prepare(page);
  const mismatches = [];
  const check = (what, a, b) => { if (!same(a, b)) mismatches.push(`${what}: ${a} vs ${b}`); };

  await page.goto('./');
  await settled(page);
  const games = await page.evaluate(() => [...document.querySelectorAll('#cv-games a.cv-game')].map(a => a.getAttribute('href')));
  expect(games.length, "the opening page's Last night strip").toBeGreaterThan(0);

  // the leaders table, every player: qualifiers off, all positions, all clubs
  await go(page, '#leaders', () => document.querySelectorAll('#ld-wrap tbody tr').length >= 10);
  await page.evaluate(() => { const q = document.querySelector('#ld-qual'); if (q && q.checked) q.click(); });
  await settled(page);
  const leaders = await page.evaluate(() => {
    const head = [...document.querySelectorAll('#ld-wrap thead th')].map(th => th.dataset.k || th.textContent.trim());
    return Object.fromEntries([...document.querySelectorAll('#ld-wrap tbody tr')].map(tr => {
      const pid = tr.querySelector('td.pl a').getAttribute('href').split('/')[1], cells = [...tr.children].map(td => td.textContent.trim());
      return [pid, Object.fromEntries(head.map((h, i) => [h, cells[i]]))];
    }));
  });

  let players = 0;
  for (const g of games) {
    const code = g.split('/')[1];
    await go(page, `#game/${code}/box`, () => document.querySelectorAll('#game .gm-box tbody tr').length >= 16);
    const box = await page.evaluate(cols => [...document.querySelectorAll('#game .gm-box tbody tr')].filter(tr => tr.querySelector('td.nm a')).map(tr => {
      const [club, pid] = tr.querySelector('td.nm a').getAttribute('href').slice(1).split('/'), cells = [...tr.children].slice(1).map(td => td.textContent.trim());
      return {club, pid, name: tr.querySelector('td.nm .full').textContent, stats: Object.fromEntries(cols.map((c, i) => [c, cells[i]]))};
    }), BOX_COLS);

    for (const club of new Set(box.map(r => r.club))) {
      await go(page, `#${club}`, () => document.querySelectorAll('#club .cb-tab tbody tr').length >= 8);
      const roster = await page.evaluate(() => {
        const tab = [...document.querySelectorAll('#club table.cb-tab')].find(t => t.querySelector('th button[data-sort=pts]'));
        const head = [...tab.querySelectorAll('thead th')].map(th => th.textContent.trim());
        return Object.fromEntries([...tab.querySelectorAll('tbody tr')].map(tr => [tr.querySelector('td.nm a').getAttribute('href').split('/')[1], Object.fromEntries(head.map((h, i) => [h, tr.children[i].textContent.trim()]))]));
      });

      for (const r of box.filter(x => x.club === club && num(x.stats.Min) > 0)) {   // a DNP has a box line but no game in his log
        players++;
        await go(page, `#${club}/${r.pid}`, () => document.querySelectorAll('#log tbody tr').length >= 1 && document.querySelectorAll('#tiles .tile').length >= 5);
        const me = await page.evaluate(gc => {
          const head = [...document.querySelectorAll('#log thead th')].map(th => th.textContent.trim());
          const row = [...document.querySelectorAll('#log tbody tr')].find(tr => tr.querySelector(`a.gm-lnk[href="#game/${gc}"]`));
          const log = row ? Object.fromEntries(head.map((h, i) => [h, row.children[i].textContent.trim()])) : null;
          const tiles = Object.fromEntries([...document.querySelectorAll('#tiles .tile')].map(t => [t.querySelector('span').textContent.trim(), t.querySelector('b').textContent.trim()]));
          const minCol = head.indexOf('Min');   // games played: log rows with minutes (a missed game has a row with none)
          const gp = [...document.querySelectorAll('#log tbody tr')].filter(tr => parseFloat(tr.children[minCol].textContent.replace(/^\D+/, '')) > 0).length;
          return {log, tiles, gp};
        }, code);
        const who = `${r.name} (${club}, game ${code})`;
        if (!me.log) { mismatches.push(`${who}: in the box score but not in his game log`); continue; }
        for (const c of BOX_COLS) check(`${who} ${c}, game page vs his game log`, r.stats[c], me.log[c]);

        const ro = roster[r.pid];
        if (!ro) { mismatches.push(`${who}: in the box score but not on the club page's roster`); continue; }
        check(`${who} points a game, his page vs club page`, me.tiles.Points, ro.Pts);
        check(`${who} rebounds a game, his page vs club page`, me.tiles.Rebounds, ro.Reb);
        check(`${who} assists a game, his page vs club page`, me.tiles.Assists, ro.Ast);
        check(`${who} PIR a game, his page vs club page`, me.tiles.PIR, ro.PIR);
        check(`${who} games, his game log vs club page`, me.gp, ro.GP);

        const ld = leaders[r.pid];
        if (ld) {
          check(`${who} points a game, club page vs leaders`, ro.Pts, ld.pts);
          check(`${who} minutes a game, club page vs leaders`, ro.Min, ld.min);
          check(`${who} games, club page vs leaders`, ro.GP, ld.gp);
        }
      }
    }
  }
  console.log(`checked ${players} players from ${games.length} games`);
  expect(players).toBeGreaterThan(0);
  expect(mismatches, 'numbers that differ between pages').toEqual([]);
  expect(problems, 'the page reported errors').toEqual([]);
});
