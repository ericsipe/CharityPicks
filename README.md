# CharityPicks

Tracking pages for the "2026 Pick 5 For Charity" pool on Splash Sports.

## The pages (all rebuilt by the same collector run; nothing is created by hand per week)

- `index.html`: the friends board (5 entrants). Reads `data/`.
- `everyone.html`: all 91 entries: season table, weekly picks with Splash's official grades, CLV column.
- `tracker.html`: the **week tracker**. It opens on the newest week that has picks and follows it from
  Tuesday through Monday: the tracked entry's chance to sweep, expected share of the weekly pot
  ($4,700, doubling on a rollover), how many 5-0 cards to expect, who is still perfect, which side
  of each remaining game to root for and what it is worth, each finished game with who had which side
  (newest first), and the season race ($6,200 / $4,100).
  Entry dropdown (default The Daddies). 40,000 simulated weeks in the browser, refreshed every 30 s
  from ESPN. Week 17: 10 picks, the week's best score takes the pot, ties split.
  Test replay: `tracker.html?wk=11&asof=2026-11-22T15:30:00Z`.
- `scorecard.html`: the Week 11 one-off that the tracker grew out of (kept for reference).

So "build the sites for this week" = run the collector (`collect.js` + `ingest.py`). The tracker
switches to the new week by itself as soon as that week's data has picks.

**Privacy rule (Eric 11/22/26):** an entry's unplayed picks stay off the public site until that game
kicks off or the Saturday 10 AM lock, whichever is first. `ingest.py hide_unplayed()` enforces it;
never publish The Daddies' card early by any other route.

## Data and tools

- `data/index.json` + `data/wkN.json` — one file per week, written by `collect.js`.
- `tools/collect.js` — runs inside a signed-in Splash tab (Eric's Chrome via Claude in Chrome, or the Claude app's built-in browser), collects this week and next, and hands the result to `tools/receiver.py` on this PC. It takes Splash's token from the app's own `accessToken` cookie, falling back to capturing a Bearer header.
- `tools/receiver.py` — tiny local page + server that receives the hand-off and writes `data/incoming.json`.
- `tools/ingest.py` — merges `data/incoming.json` into `data/`, commits and pushes (GitHub Pages republishes in about a minute).

## Automatic refresh

Scheduled tasks in the Claude desktop app run the collector Tuesday to Friday at 7:30 PM and
10:30 PM (so weeknight picks show the night they kick off) and Saturday at 10:15 AM (right after
picks lock), Central time. Each run: start `tools/receiver.py`,
open the contest in Eric's Chrome through Claude in Chrome (Chrome keeps the Splash sign-in; the
app's built-in browser kept losing it, so it is only the fallback), paste `tools/collect.js` and
call `runCollector()`, then `python tools/ingest.py`. Between runs the Everyone page grades live
from ESPN's public scoreboard in the visitor's browser, so weekend scores update without any run.
Splash's official grades replace ESPN's at the next run.

If both browsers are signed out of Splash, the run stops at the sign-in page and says so; sign in
to Splash in Chrome and the next run picks up.

Published at https://ericsipe.github.io/CharityPicks/ (friends board),
https://ericsipe.github.io/CharityPicks/everyone.html (whole pool) and
https://ericsipe.github.io/CharityPicks/tracker.html (week tracker).
