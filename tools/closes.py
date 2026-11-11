"""tools/closes.py — store each finished game's closing line in data/closes.json.

The pool's lines freeze when the board posts; the market keeps moving until kickoff. The page
compares every pick's pool line with the DraftKings closing line (ESPN's odds feed) and shows the
average as the season table's CLV column. This script adds the closes for finished games that are
not stored yet:  { gameId: closing HOME spread }.  ingest.py runs it on every publish; it can also
be run by hand:  python tools/closes.py
"""
import json, pathlib, re, datetime, urllib.request, concurrent.futures as cf

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "data"
CLOSES = DATA / "closes.json"
LEAGUE = {"nfl": "nfl", "ncaaf": "college-football"}
SITE = "https://site.api.espn.com/apis/site/v2/sports/football/"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/"


def get(url):
    err = None
    for _ in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:  # noqa: BLE001 - retry any network error
            err = e
    raise err


def when(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))


norm = lambda s: re.sub(r"[^a-z]", "", (s or "").lower())


def side_score(alias, name, team):
    n = norm(name)
    cands = [norm(team.get(k)) for k in ("location", "displayName", "shortDisplayName", "name")]
    if n and any(c and (n == c or n in c or c in n) for c in cands):
        return 2
    return 1 if team.get("abbreviation") == alias else 0


def main():
    closes = json.loads(CLOSES.read_text(encoding="utf-8")) if CLOSES.exists() else {}
    todo = {}
    for f in sorted(DATA.glob("wk*.json")):
        for gid, g in json.loads(f.read_text(encoding="utf-8")).get("games", {}).items():
            if gid not in closes and g.get("status") in ("finished", "finalized"):
                todo[gid] = g
    if not todo:
        return 0
    # ESPN scoreboards, one per league and day (a date range returns 400 for college).
    days = {(g["lg"], (when(g["start"]) - datetime.timedelta(hours=6)).strftime("%Y%m%d")) for g in todo.values()}

    def board(k):
        lg, day = k
        url = f"{SITE}{LEAGUE[lg]}/scoreboard?limit=400&dates={day}" + ("&groups=80" if lg == "ncaaf" else "")
        out = []
        for e in get(url).get("events", []):
            c = e["competitions"][0]["competitors"]
            out.append({"lg": lg, "id": e["id"], "date": e["date"],
                        "home": next(x for x in c if x["homeAway"] == "home")["team"],
                        "away": next(x for x in c if x["homeAway"] == "away")["team"]})
        return out

    def close_for(item):
        gid, g = item
        best = None
        for e in events:
            if e["lg"] != g["lg"] or abs((when(e["date"]) - when(g["start"])).total_seconds()) > 36 * 3600:
                continue
            s = side_score(g["home"], g.get("homeName"), e["home"]) + side_score(g["away"], g.get("awayName"), e["away"])
            if s >= 3 and (not best or s > best[0]):
                best = (s, e)
        if not best:
            return gid, None
        eid = best[1]["id"]
        for it in get(f"{CORE}{LEAGUE[g['lg']]}/events/{eid}/competitions/{eid}/odds").get("items", []):
            try:
                v = it["homeTeamOdds"]["close"]["pointSpread"]["american"]
                return gid, 0.0 if v in ("EVEN", "PK") else float(v)
            except (KeyError, TypeError, ValueError):
                if it.get("spread") is not None:
                    return gid, float(it["spread"])
        return gid, None

    with cf.ThreadPoolExecutor(8) as ex:
        events = [e for es in ex.map(board, sorted(days)) for e in es]
    with cf.ThreadPoolExecutor(12) as ex:
        found = {gid: v for gid, v in ex.map(close_for, todo.items()) if v is not None}
    if found:
        closes.update(found)
        CLOSES.write_text(json.dumps(closes, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    missing = len(todo) - len(found)
    print(f"closing lines: {len(found)} added" + (f", {missing} not found" if missing else ""))
    return len(found)


if __name__ == "__main__":
    main()
