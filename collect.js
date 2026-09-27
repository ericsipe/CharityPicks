/* collect.js — pull one week of the pool from Splash's own API.

   HOW IT IS USED
   Runs INSIDE a browser tab that is signed in to Splash and showing the
   contest (any page under contests.app.splashsports.com/team-pickem/contests/<contest>).
   A Claude session pastes this into the tab (Claude in Chrome "javascript_tool"),
   waits for the returned JSON, and writes it to data/wkN.json in this repo.
   The bearer token the site uses stays inside the page; nothing is copied out.

   WHAT IT RETURNS
   { slate, lockedAt, collectedAt, games: {gameId: {...}}, entries: [{rank, handle,
     name, id, pts, picks: [[gameId, teamAlias, spread, grade], ...]}, ...] }
   grade is Splash's own: "won" | "lost" | "winning" | "losing" | null (not started).
   Splash returns every entrant's picks as soon as the slate locks, even for
   games that have not kicked off (its web page hides them; its API does not).

   HOW TO PICK THE WEEK
   Pass the slate id (from the URL /standings/picks/slate_...) as SLATE, or leave
   it empty to use the slate in the current URL. Week 1-3 slate ids are in
   data/index.json.
*/
async function collectSplashWeek(SLATE) {
  const CONTEST = "contest_01KZ49QZ2TCZS7ZVXTW175VHWZ";
  const api = "https://api.splashsports.com/contests-service-v2/api";
  const slate = SLATE || (location.href.match(/slate_[0-9A-Z]{26}/) || [null])[0];
  if (!slate) throw new Error("No slate id: open the Picks by Week view for the week you want, or pass one.");

  // Borrow the page's own Authorization header: patch XHR, then nudge the app
  // into making a request by re-requesting the page's data (any week button click
  // also works). The token is only ever held in this tab's memory.
  if (!window.__splashTok) {
    const orig = XMLHttpRequest.prototype.setRequestHeader;
    XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
      if (/^authorization$/i.test(k)) window.__splashTok = v;
      return orig.apply(this, arguments);
    };
    const btn = [...document.querySelectorAll("button")].find((b) => /NFL Week \d+/.test(b.textContent));
    if (btn) btn.click();
    for (let i = 0; i < 40 && !window.__splashTok; i++) await new Promise((r) => setTimeout(r, 250));
    if (!window.__splashTok) throw new Error("Could not capture the site's token; reload the page and run again.");
  }
  const get = async (u) => {
    const r = await fetch(u, { headers: { Authorization: window.__splashTok } });
    if (!r.ok) throw new Error(`${r.status} from ${u.split("?")[0]}`);
    return r.json();
  };
  const lb = await get(`${api}/leaderboards?contestId=${CONTEST}&slateId=${slate}&picksSlateId=${slate}&includeOwnLivePicks=true&limit=100`);
  const ps = await get(`${api}/team-pickem/picksheets?contestId=${CONTEST}&slateId=${slate}`);
  if (lb.nextCursor) throw new Error("More than 100 entries; add cursor paging.");

  const games = {};
  for (const g of ps.data.games) {
    games[g.gameId] = { lg: g.league, start: g.startsAt, status: g.status, away: g.away.alias, home: g.home.alias,
      as: g.away.score, hs: g.home.score, hsp: g.home.spread, q: g.state?.quarter ?? null, clock: g.state?.clock ?? null };
  }
  const entries = lb.data.map((e) => ({
    rank: e.displayRank, handle: e.user?.handle, name: e.entry?.displayName, id: e.entry?.id, pts: e.score,
    picks: (e.picks?.data || []).map((p) => [p.gameId, p.team?.alias, p.spread, p.grade]),
  }));
  const used = new Set(entries.flatMap((e) => e.picks.map((p) => p[0])));
  for (const id of Object.keys(games)) if (!used.has(id)) delete games[id];
  return { slate, lockedAt: ps.data.slateFullyLockedAt, collectedAt: new Date().toISOString(), games, entries };
}
// Example (in the tab): JSON.stringify(await collectSplashWeek())
