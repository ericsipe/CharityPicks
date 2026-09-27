# CharityPicks

Tracking pages for the "2026 Pick 5 For Charity" pool on Splash Sports.

- `index.html` — the friends board (5 entrants, graded live against ESPN). Edited by hand each week.
- `everyone.html` — all 91 entries: season table, weekly picks with Splash's official grades, most-picked teams. Reads `data/`.
- `data/index.json` + `data/wkN.json` — one file per week, written by `collect.js`.
- `collect.js` — runs inside a signed-in Splash tab and returns one week as JSON (see the comment at the top).

Weekly refresh (to be automated): run `collect.js` for the current week in a signed-in Splash tab,
save the result as `data/wkN.json`, add the week to `data/index.json`, commit, push. GitHub Pages
publishes `main` at https://ericsipe.github.io/CharityPicks/ .
