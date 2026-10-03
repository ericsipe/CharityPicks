/* tools/collect.js — pull the current weeks of the pool from Splash and hand them to this PC.

   HOW IT IS USED (by the scheduled task, or by hand in a Claude session)
   1. Start the receiver on this PC:  python tools/receiver.py data/incoming.json
   2. In the app's built-in browser (signed in to Splash), open the contest's
      "Picks by Week" view (any week), e.g.
      https://contests.app.splashsports.com/team-pickem/contests/contest_01KZ49QZ2TCZS7ZVXTW175VHWZ/standings/picks/slate_01KZ49QZ2QHB47JBGNNWRZ8S1X
   3. Paste this whole file into the tab with the javascript tool, followed by:
        await runCollector()
      The tab collects "this week" (the week whose date range contains today) and the
      week after it, gzips the result, and NAVIGATES to the local receiver page with the
      data in the URL fragment. The receiver saves data/incoming.json and exits.
   4. Run  python tools/ingest.py  to merge incoming.json into data/, commit and push.

   WHY THIS SHAPE
   Splash's data service answers only with the bearer token the web app holds. The
   token stays inside the tab: the script borrows it from the app's own requests and
   never returns it. Splash's Content-Security-Policy blocks fetch() to localhost, so
   the result travels by a plain navigation instead, which CSP cannot stop.
   Each week button carries its slate id in data-testid="standings-period-<slate>",
   so no week needs to be clicked to find its id.

   WHAT EACH WEEK LOOKS LIKE
   { slate, label, title, dates, lockedAt, collectedAt,
     games:   { gameId: { lg, start, status, away, home, awayName, homeName, as, hs, hsp, q, clock } },
     entries: [ { rank, handle, name, id, pts, picks: [[gameId, teamAlias, spread, grade], ...] } ] }
   grade is Splash's own: "won" | "lost" | "winning" | "losing" | null (not graded yet).
*/
const CONTEST = "contest_01KZ49QZ2TCZS7ZVXTW175VHWZ";
const API = "https://api.splashsports.com/contests-service-v2/api";
const RECEIVER = "http://127.0.0.1:8765/collector.html";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function weekButtons() {
  return [...document.querySelectorAll('button[data-testid^="standings-period-slate_"]')];
}
const slateOf = (b) => b.dataset.testid.replace("standings-period-", "");

async function tokenWorks(tok) {
  try { return (await fetch(`${API}/contests/${CONTEST}`, { headers: { Authorization: tok } })).ok; } catch { return false; }
}

// The Splash web app keeps its access token in a cookie the tab can read. That is the
// first choice (10/3/26: the XHR capture below stopped working because re-clicking the
// selected week no longer sends a request). The capture stays as the fallback, now
// accepting only a Bearer token (a "Basic" header from another request fooled it on 10/2).
async function splashToken() {
  if (window.__splashTok) return window.__splashTok;
  const c = document.cookie.split(";").map((s) => s.trim()).find((s) => s.startsWith("accessToken="));
  if (c) {
    const v = decodeURIComponent(c.slice("accessToken=".length));
    const tok = /^Bearer /i.test(v) ? v : `Bearer ${v}`;
    if (v && await tokenWorks(tok)) return (window.__splashTok = tok);
  }
  const orig = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function (k, v) {
    if (/^authorization$/i.test(k) && /^Bearer /i.test(v)) window.__splashTok = v;
    return orig.apply(this, arguments);
  };
  // Nudge the app into making a request so the header shows up: click a week other than
  // the selected one (the data comes from the API afterwards, so the view does not matter).
  const btns = weekButtons();
  const btn = btns.find((b) => b.getAttribute("aria-current") !== "true") || btns[0];
  if (btn) btn.click();
  for (let i = 0; i < 60 && !window.__splashTok; i++) await sleep(250);
  if (!window.__splashTok) throw new Error("Could not get Splash's token (no accessToken cookie and no Bearer header seen); reload the page and run again.");
  return window.__splashTok;
}

// "Sep 28-Oct 5" or "Dec 28-Jan 4" -> [start, end) as local dates
const MON = { Jan: 0, Feb: 1, Mar: 2, Apr: 3, May: 4, Jun: 5, Jul: 6, Aug: 7, Sep: 8, Oct: 9, Nov: 10, Dec: 11 };
function dateRange(text, today) {
  const m = text.match(/([A-Z][a-z]{2}) (\d+)\s*-\s*(?:([A-Z][a-z]{2}) )?(\d+)/);
  if (!m) return null;
  let y = today.getFullYear();
  if (MON[m[1]] === 0 && today.getMonth() === 11) y += 1;          // a January week seen in December
  const a = new Date(y, MON[m[1]], +m[2]);
  let b = new Date(y, MON[m[3] || m[1]], +m[4]);
  if (b < a) b = new Date(y + 1, MON[m[3] || m[1]], +m[4]);        // range crosses New Year
  return [a, new Date(b.getTime() + 86400000)];
}

function describeButton(b, index) {
  const text = b.textContent.trim().replace(/\s+/g, " ").replace(/live$/i, "").trim();
  const m = text.match(/^(NFL Week \d+) \| (.+?)([A-Z][a-z]{2} \d+.*)$/);
  return { label: `Wk ${index + 1}`, title: m ? `${m[1]} / ${m[2].trim()}` : text, dates: m ? m[3] : "" };
}

async function collectSlate(slate, meta) {
  const tok = await splashToken();
  const get = async (u) => {
    const r = await fetch(u, { headers: { Authorization: tok } });
    if (!r.ok) throw new Error(`${r.status} from ${u.split("?")[0]}`);
    return r.json();
  };
  const lb = await get(`${API}/leaderboards?contestId=${CONTEST}&slateId=${slate}&picksSlateId=${slate}&includeOwnLivePicks=true&limit=100`);
  const ps = await get(`${API}/team-pickem/picksheets?contestId=${CONTEST}&slateId=${slate}`);
  if (lb.nextCursor) throw new Error("More than 100 entries; add cursor paging.");
  const games = {};
  for (const g of ps.data.games) {
    games[g.gameId] = { lg: g.league, start: g.startsAt, status: g.status, away: g.away.alias, home: g.home.alias,
      awayName: g.away.name, homeName: g.home.name, as: g.away.score, hs: g.home.score, hsp: g.home.spread,
      q: g.state?.quarter ?? null, clock: g.state?.clock ?? null };
  }
  const entries = lb.data.map((e) => ({
    rank: e.displayRank, handle: e.user?.handle, name: e.entry?.displayName, id: e.entry?.id, pts: e.score,
    picks: (e.picks?.data || []).map((p) => [p.gameId, p.team?.alias, p.spread, p.grade]),
  }));
  const used = new Set(entries.flatMap((e) => e.picks.map((p) => p[0])));
  for (const id of Object.keys(games)) if (!used.has(id)) delete games[id];
  const week = { slate, ...meta, lockedAt: ps.data.slateFullyLockedAt, collectedAt: new Date().toISOString(), games, entries };
  // Sanity check: the slate's lock date must fall inside the week button's date range.
  const today = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Chicago" }));
  const r = dateRange(meta.dates || "", today);
  const lock = new Date(new Date(week.lockedAt).toLocaleString("en-US", { timeZone: "America/Chicago" }));
  if (r && !(lock >= r[0] && lock < r[1])) throw new Error(`${meta.title}: slate ${slate} locks ${week.lockedAt}, outside ${meta.dates}`);
  return week;
}

// Which weeks to collect: the one whose date range contains today, and the next one.
function targetWeeks() {
  const today = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Chicago" }));
  today.setHours(12, 0, 0, 0);
  const btns = weekButtons();
  if (!btns.length) throw new Error("No week buttons on this page; open the Picks by Week view.");
  let idx = btns.findIndex((b) => { const r = dateRange(b.textContent, today); return r && today >= r[0] && today < r[1]; });
  if (idx < 0) idx = btns.findIndex((b) => b.textContent.trim().endsWith("live"));
  if (idx < 0) throw new Error("No week button matches today's date.");
  return [idx, idx + 1].filter((i) => i < btns.length).map((i) => ({ index: i, button: btns[i] }));
}

async function handOff(obj) {
  const raw = JSON.stringify(obj);
  const cs = new CompressionStream("gzip"); const w = cs.writable.getWriter();
  w.write(new TextEncoder().encode(raw)); w.close();
  const bytes = new Uint8Array(await new Response(cs.readable).arrayBuffer());
  let bin = ""; for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  setTimeout(() => { location.href = RECEIVER + "#" + btoa(bin); }, 100);
  return raw.length;
}

// The one call the task makes. Returns a short summary; the data goes to the receiver.
async function runCollector() {
  await splashToken();
  const out = {};
  for (const { index, button } of targetWeeks()) {
    out[`wk${index + 1}`] = await collectSlate(slateOf(button), describeButton(button, index));
  }
  const summary = Object.entries(out).map(([k, w]) => `${k} ${w.slate} ${w.entries.length} entries, locks ${w.lockedAt.slice(0, 10)}`).join("; ");
  const size = await handOff(out);
  return `${summary}; ${size} bytes handed to the receiver`;
}
window.runCollector = runCollector;
