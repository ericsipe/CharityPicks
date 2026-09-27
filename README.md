# CharityPicks

Tracking pages for the "2026 Pick 5 For Charity" pool on Splash Sports.

- `index.html` — the friends board (5 entrants, graded live against ESPN). Edited by hand each week.
- `everyone.html` — all 91 entries: season table, weekly picks with Splash's official grades, most-picked teams. Reads `data/`.
- `data/index.json` + `data/wkN.json` — one file per week, written by `collect.js`.
- `tools/collect.js` — runs inside a signed-in Splash tab (the Claude app's built-in browser), collects this week and next, and hands the result to `tools/receiver.py` on this PC.
- `tools/receiver.py` — tiny local page + server that receives the hand-off and writes `data/incoming.json`.
- `tools/ingest.py` — merges `data/incoming.json` into `data/`, commits and pushes (GitHub Pages republishes in about a minute).

## Automatic refresh

Scheduled tasks in the Claude desktop app run the collector Tuesday to Saturday at 7:00 AM and
Saturday at 10:15 AM (right after picks lock), Central time. Each run: start `tools/receiver.py`,
open the contest in the app's built-in browser (signed in to Splash once by Eric), paste
`tools/collect.js` and call `runCollector()`, then `python tools/ingest.py`. Between runs the
Everyone page grades live from ESPN's public scoreboard in the visitor's browser, so weekend
scores update without any run. Splash's official grades replace ESPN's at the next run.

If Splash ever signs the built-in browser out, the run stops at the sign-in page and says so;
sign in again in that browser pane and the next run picks up.

Published at https://ericsipe.github.io/CharityPicks/ (friends board) and
https://ericsipe.github.io/CharityPicks/everyone.html (whole pool).
