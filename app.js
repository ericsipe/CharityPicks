/* Shared page logic for index.html (friends) and everyone.html (whole pool). Data comes from data/*.json written by tools/collect.js; live scores from ESPN. */
/* ---------------------------------------------------------------
   Data comes from data/index.json + data/wkN.json, written by the
   collector (collect.js) from Splash's own API — grades are Splash's
   official ones. Nothing here is typed by hand.

   FRIENDS: Splash entry name (or handle) -> { label, key }. key picks the
   color in style.css (me, f1..f4).
   --------------------------------------------------------------- */
const FRIENDS = {
  "The Daddies":  { label: "The Daddies", key: "me" },
  "TD33for99":    { label: "TD33for99",   key: "f1" },
  "Purple Reign": { label: "Purple Reign", key: "f2" },
  "DKMEIS":       { label: "D-PIGGY$",    key: "f3" },   // Splash entry "DKMEIS" (handle DKMEIS)
  "DKMEIS2":      { label: "Susan",       key: "f4" },   // Splash entry "DKMEIS2" (same handle)
};

const MODE = document.body.dataset.mode || "everyone";   // "friends" on index.html, "everyone" on everyone.html
const FRIENDS_PAGE = MODE === "friends";
const $ = (id) => document.getElementById(id);
let WEEKS = [], selected = 0, friendsOnly = false, query = "";

const friend = (e) => FRIENDS[e.name] || FRIENDS[e.handle] || null;
const key = (e) => e.id;
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function nameCell(e) {
  const f = friend(e);
  if (FRIENDS_PAGE && f) {
    const entry = e.name && e.name !== e.handle ? `${esc(e.name)} · ${esc(e.handle)}` : esc(e.handle);
    return `${esc(f.label)}<span class="sub">${entry}</span>`;
  }
  const main = e.name && e.name !== e.handle ? esc(e.name) : esc(e.handle);
  const sub = e.name && e.name !== e.handle ? `<span class="sub">${esc(e.handle)}</span>` : "";
  return `${main}${f ? `<span class="tag">${esc(f.label)}</span>` : ""}${sub}`;
}
const rowAttr = (e) => { const f = friend(e); return f ? ` data-f="${f.key}"` : ""; };
const fmtSpread = (s) => (s > 0 ? "+" : "") + Number(s).toFixed(1);
const ct = (iso, opts) => new Date(iso).toLocaleString("en-US", { timeZone: "America/Chicago", ...opts });

/* ---- live scores from ESPN between collector runs ----------------------
   Picks and lines always come from the Splash data. For games Splash has not
   graded yet, the page fetches ESPN's public scoreboard, matches each game by
   league + team names, and grades the pick against the Splash line itself.
   Splash's own won/lost always wins once the collector has recorded it.       */
const ESPN = {};                       // gameId -> { as, hs, state, detail }
const ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/";
const norm = (t) => String(t || "").toLowerCase().replace(/[^a-z0-9]/g, "");
const NFL_ALIAS = { LA: "LAR", WAS: "WSH", JAC: "JAX" };   // Splash -> ESPN abbreviations
function weekNeedsLive(w) { return Object.values(w.games).some((g) => g.status !== "finalized" && g.status !== "finished"); }
function espnFeedsFor(w) {
  const feeds = new Set();
  const nfl = (w.title || "").match(/NFL Week (\d+)/);
  for (const g of Object.values(w.games)) {
    if (g.status === "finalized" || g.status === "finished") continue;
    if (g.lg === "nfl" && nfl) feeds.add(`${ESPN_BASE}nfl/scoreboard?seasontype=2&week=${nfl[1]}&dates=${new Date(g.start).getUTCFullYear()}`);
    if (g.lg === "ncaaf") { const d = new Date(new Date(g.start).toLocaleString("en-US", { timeZone: "America/Chicago" })); feeds.add(`${ESPN_BASE}college-football/scoreboard?groups=80&limit=400&dates=${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`); }
  }
  return [...feeds];
}
function teamMatches(splashAlias, splashName, t) {
  const a = norm(splashAlias), names = [t.abbreviation, t.location, t.shortDisplayName, t.name, t.displayName].map(norm);
  if (names[0] === a || names[0] === norm(NFL_ALIAS[splashAlias] || "")) return true;
  const n = norm(splashName);
  return n && (names.includes(n) || norm(t.displayName).startsWith(n));
}
async function loadEspn(w) {
  const feeds = espnFeedsFor(w);
  if (!feeds.length) return 0;
  const events = [];
  const results = await Promise.allSettled(feeds.map((u) => fetch(u, { cache: "no-store" }).then((r) => r.json())));
  for (const r of results) if (r.status === "fulfilled") for (const ev of r.value.events || []) events.push(ev);
  let matched = 0;
  for (const [gid, g] of Object.entries(w.games)) {
    if (g.status === "finalized" || g.status === "finished") continue;
    const ev = events.find((e) => { const c = e.competitions[0]; const home = c.competitors.find((x) => x.homeAway === "home"), away = c.competitors.find((x) => x.homeAway === "away"); return home && away && teamMatches(g.home, g.homeName, home.team) && teamMatches(g.away, g.awayName, away.team); });
    if (!ev) continue;
    const c = ev.competitions[0]; const home = c.competitors.find((x) => x.homeAway === "home"), away = c.competitors.find((x) => x.homeAway === "away");
    ESPN[gid] = { as: +away.score || 0, hs: +home.score || 0, state: ev.status.type.state, detail: ev.status.type.shortDetail };
    matched++;
  }
  return matched;
}

function gradePick(pick, games) {
  const [gid, team, spread, grade] = pick;
  const g = games[gid], sp = fmtSpread(spread);
  if (!g) return { cls: "pend", team, sp, word: "?", detail: "game not in feed" };
  const isAway = g.away === team, opp = isAway ? g.home : g.away;
  const me = isAway ? g.as : g.hs, them = isAway ? g.hs : g.as;
  const score = (me == null || them == null) ? "" : (isAway ? `${team} ${me}–${them} @${opp}` : `@${opp} ${them}–${me} ${team}`);
  const clock = g.q ? ` Q${g.q} ${g.clock || ""}`.trimEnd() : "";
  if (grade === "won")  return { cls: "win",  team, sp, word: "✓", detail: score, pts: 1 };
  if (grade === "lost") return { cls: "loss", team, sp, word: "✗", detail: score, pts: 0 };
  const live = ESPN[gid];
  if (live && live.state !== "pre") {
    const lme = isAway ? live.as : live.hs, lthem = isAway ? live.hs : live.as;
    const lscore = isAway ? `${team} ${lme}–${lthem} @${opp}` : `@${opp} ${lthem}–${lme} ${team}`;
    const adj = (lme - lthem) + spread;
    if (live.state === "post") {
      if (adj > 0) return { cls: "win",  team, sp, word: "✓", detail: lscore + " · final", pts: 1, espnFinal: true };
      if (adj < 0) return { cls: "loss", team, sp, word: "✗", detail: lscore + " · final", pts: 0, espnFinal: true };
      return { cls: "pend", team, sp, word: "–", detail: lscore + " · push", pts: 0, espnFinal: true };
    }
    const word = adj > 0 ? "▲" : adj < 0 ? "▼" : "•";
    return { cls: "live", team, sp, word, detail: `${lscore} · ${live.detail}`, pts: 0, live: adj > 0 ? 1 : 0 };
  }
  if (grade === "winning") return { cls: "live", team, sp, word: "▲", detail: score + clock, pts: 0, live: 1 };
  if (grade === "losing")  return { cls: "live", team, sp, word: "▼", detail: score + clock, pts: 0, live: 0 };
  if (g.status === "scheduled") return { cls: "pend", team, sp, word: "", detail: `vs ${opp} · ${ct(g.start, { weekday: "short", hour: "numeric", minute: "2-digit" })}` };
  return { cls: "pend", team, sp, word: "–", detail: score ? score + " (push)" : `vs ${opp}` };
}

function weekStats(w) {
  const out = {};
  for (const e of w.entries) {
    let live = 0, done = true, pts = 0;
    for (const p of e.picks) {
      const g = gradePick(p, w.games);
      pts += g.pts || 0; live += g.live || 0;
      if (!(p[3] === "won" || p[3] === "lost" || g.espnFinal)) done = false;
    }
    if (e.picks.length === 0) done = true;
    // Splash's official total wins whenever it is at least what we can see.
    pts = Math.max(pts, e.pts || 0);
    out[key(e)] = { e, pts, live, done, entered: e.picks.length > 0 };
  }
  return out;
}

function renderLegend() {
  $("legend").innerHTML = Object.values(FRIENDS).map((f) => `<button type="button" class="chip" data-key="${f.key}" style="--fc: var(--${f.key})">${esc(f.label)}</button>`).join("");
  $("legend").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => jumpTo(b.dataset.key)));
}

// Scroll the season table to a friend's row and flash it.
function jumpTo(k) {
  if (friendsOnly && $("friendsOnly")) { friendsOnly = false; $("friendsOnly").setAttribute("aria-pressed", "false"); renderAll(); }
  const row = $("season").querySelector(`tbody tr[data-f="${k}"]`);
  if (!row) return;
  row.scrollIntoView({ block: "center" });
  row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash");
}

function renderSeason() {
  const stats = WEEKS.map(weekStats);
  const all = new Map();
  for (const w of WEEKS) for (const e of w.entries) if (!all.has(key(e))) all.set(key(e), e);
  const rows = [...all.values()].map((e) => {
    const per = stats.map((s) => s[key(e)] || { pts: 0, live: 0, done: true, entered: false });
    return { e, per, total: per.reduce((a, r) => a + r.pts, 0), live: per.reduce((a, r) => a + r.live, 0) };
  });
  rows.sort((a, b) => b.total - a.total || b.live - a.live || a.e.handle.localeCompare(b.e.handle));
  const q = query.trim().toLowerCase();
  const shown = rows.filter((r) => ((!friendsOnly && !FRIENDS_PAGE) || friend(r.e)) && (!q || `${r.e.handle} ${r.e.name || ""}`.toLowerCase().includes(q)));
  const ranked = FRIENDS_PAGE ? shown : rows;     // friends page ranks the five among themselves
  let rank = 0, prev = null;
  ranked.forEach((r, i) => { if (r.total !== prev) { rank = i + 1; prev = r.total; } r.rank = rank; });
  const tie = (r) => ranked.filter((x) => x.total === r.total).length > 1 ? "T" : "";
  if ($("count")) $("count").textContent = `${shown.length} of ${rows.length} entries`;
  $("season").querySelector("thead").innerHTML = `<tr><th>#</th><th>Entrant</th>${WEEKS.map((w, i) => `<th class="num"><button type="button" data-i="${i}" aria-pressed="${i === selected}">${esc(w.label)}</button></th>`).join("")}<th class="num">Total</th></tr>`;
  $("season").querySelector("tbody").innerHTML = shown.map((r) => `
    <tr${rowAttr(r.e)}>
      <td>${tie(r)}${r.rank}</td>
      <td>${nameCell(r.e)}</td>
      ${r.per.map((p) => `<td class="num">${p.entered ? p.pts + (p.done ? "" : "*") : "–"}</td>`).join("")}
      <td class="num total">${r.total}${r.live ? ` <span class="live">+${r.live}</span>` : ""}</td>
    </tr>`).join("");
  $("season").querySelectorAll("thead button").forEach((b) => b.addEventListener("click", () => { selected = +b.dataset.i; renderAll(); }));
}

function renderTabs() {
  const w = WEEKS[selected];
  $("weekTabs").innerHTML = WEEKS.map((x, i) => `<button type="button" data-i="${i}" aria-pressed="${i === selected}">${esc(x.label)}</button>`).join("") +
    `<span class="meta">${esc(w.dates || "")} · picks locked ${ct(w.lockedAt, { month: "short", day: "numeric", hour: "numeric" })} CT</span>`;
  $("weekTabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { selected = +b.dataset.i; renderAll(); }));
}

function renderBoard() {
  const w = WEEKS[selected];
  $("weekTitle").textContent = w.title || w.label;
  const stats = weekStats(w);
  const q = query.trim().toLowerCase();
  let rows = w.entries.filter((e) => e.picks.length).map((e) => ({ e, ...stats[key(e)] }));
  rows.sort((a, b) => (b.pts + b.live) - (a.pts + a.live) || b.pts - a.pts || a.e.handle.localeCompare(b.e.handle));
  if (FRIENDS_PAGE) rows = rows.filter((r) => friend(r.e));
  let rank = 0, prev = null;
  rows.forEach((r, i) => { const k = r.pts + r.live; if (k !== prev) { rank = i + 1; prev = k; } r.rank = rank; });
  rows = rows.filter((r) => (!friendsOnly || friend(r.e)) && (!q || `${r.e.handle} ${r.e.name || ""}`.toLowerCase().includes(q)));
  if (!w.entries.length) {
    $("board").querySelector("tbody").innerHTML = `<tr><td colspan="4" class="meta">No picks yet. Picks lock ${ct(w.lockedAt, { weekday: "short", month: "short", day: "numeric", hour: "numeric" })} CT; the board fills in as entries are made.</td></tr>`;
    if ($("pop")) $("pop").innerHTML = ""; return;
  }
  $("board").querySelector("tbody").innerHTML = rows.map((r) => `
    <tr${rowAttr(r.e)}>
      <td>${r.rank}</td>
      <td>${nameCell(r.e)}</td>
      <td class="num total">${r.pts}${r.live ? ` <span class="live">+${r.live}</span>` : ""}${r.done ? "" : "*"}</td>
      <td><div class="picks">${r.e.picks.map((p) => { const g = gradePick(p, w.games); return `<span class="pick ${g.cls}"><b>${esc(g.team)}</b> ${g.sp} ${g.word} <span class="d">${esc(g.detail)}</span></span>`; }).join("")}</div></td>
    </tr>`).join("");
  const pop = {};
  for (const e of w.entries) for (const p of e.picks) { const k = `${p[1]} ${fmtSpread(p[2])}`; pop[k] = pop[k] || { n: 0, grade: p[3], gid: p[0], team: p[1], spread: p[2] }; pop[k].n++; }
  const list = Object.values(pop).sort((a, b) => b.n - a.n).slice(0, 24);
  if ($("pop")) $("pop").innerHTML = list.map((v) => { const g = gradePick([v.gid, v.team, v.spread, v.grade], w.games); return `<li class="${g.cls}">${v.n} × ${esc(v.team)} ${fmtSpread(v.spread)} ${g.word}</li>`; }).join("");
}

function renderAll() { renderSeason(); renderTabs(); renderBoard(); }

async function load() {
  try {
    const idx = await (await fetch("data/index.json", { cache: "no-store" })).json();
    WEEKS = await Promise.all(idx.weeks.map((w) => fetch(w.file, { cache: "no-store" }).then((r) => r.json())));
    // Open on the newest week that has picks; a week with none yet still gets a tab.
    selected = Math.max(0, ...WEEKS.map((w, i) => (w.entries.length ? i : -1)));
    const latest = WEEKS[selected];
    renderLegend(); renderAll();
    $("note").textContent = "Picks and lines come from Splash. ✓/✗ are Splash's official grades, or ESPN finals until Splash confirms them; ▲/▼ are live leaders from ESPN, refreshed every minute while a game is on. * = week still in progress.";
    let liveNote = "";
    const stamp = () => { $("updated").textContent = `${latest.entries.length} entries · picks collected ${ct(latest.collectedAt, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} CT` + (liveNote ? ` · live scores ${liveNote}` : ""); };
    stamp();
    const liveWeeks = WEEKS.filter(weekNeedsLive);
    const refresh = window.__refresh = async () => { let n = 0; for (const w of liveWeeks) n += await loadEspn(w); liveNote = n ? `updated ${new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}` : ""; stamp(); renderAll(); };
    if (liveWeeks.length) { await refresh(); setInterval(refresh, 60_000); document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); }); }
  } catch (e) {
    $("error").hidden = false; $("error").textContent = "Could not load the data files: " + e.message;
  }
}

if ($("q")) $("q").addEventListener("input", (ev) => { query = ev.target.value; renderAll(); });
if ($("friendsOnly")) $("friendsOnly").addEventListener("click", (ev) => { friendsOnly = !friendsOnly; ev.currentTarget.setAttribute("aria-pressed", String(friendsOnly)); renderAll(); });
if ($("refresh")) $("refresh").addEventListener("click", () => window.__refresh && window.__refresh());
load();
