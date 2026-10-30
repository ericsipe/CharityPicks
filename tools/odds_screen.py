"""tools/odds_screen.py — price the pool board against sharp-ish markets.

    python tools/odds_screen.py BOARD.json [--json OUT.json] [--top N]

BOARD.json is a list of the week's pool games:
    [{"lg": "nfl"|"ncaaf", "away": "WIS", "home": "IOWA", "awayName": "Wisconsin",
      "homeName": "Iowa", "awayNick": "Badgers", "homeNick": "Hawkeyes",
      "hsp": -3.5, "start": "2026-10-31T16:00:00Z"}, ...]
hsp is the POOL's home spread (Splash's frozen number).

WHY THESE SOURCES
Kalshi and Polymarket list a full ladder of "<team> wins by over X.5" contracts per
game, priced by traders with real money, with no bookmaker margin baked into the price.
So instead of guessing how much half a point is worth with key-number tables, the
screen reads P(pick covers the POOL's exact number) straight off the ladder (mid of bid
and ask; linear between strikes when the pool number is not listed). DraftKings
(via ESPN's public scoreboard) is shown only as a reference line: it is a retail book.
Pinnacle has no public API (its site feed needs a key scraped from their JavaScript,
which this tool will not use); a licensed odds feed is the clean route to it.

OUTPUT
Per game, the side the markets like at the pool number, its cover probability from
each source and a liquidity-weighted blend, each source's fair line (where its ladder
crosses 50%), and DK's line. Edge = blend - 50%.
"""
import argparse, datetime, difflib, gzip, json, re, sys, urllib.request

UA = {"User-Agent": "CharityPicks odds screen (personal use)", "Accept-Encoding": "gzip"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    return json.loads(raw.decode("utf-8"))


def norm(s):
    s = (s or "").lower().replace("&", " and ").replace(".", " ")
    s = re.sub(r"\bst\b", "state", s)
    s = re.sub(r"\buniv(ersity)?\b|\bthe\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def mid(bid, ask, last=None):
    """Midpoint when both sides are quoted and the market is not absurdly wide."""
    if bid and ask and 0 < bid < ask and ask - bid <= 0.10:
        return (bid + ask) / 2, ask - bid
    if last and 0 < last < 1 and bid and ask and bid <= last <= ask:
        return last, ask - bid
    return None, None


# ---------------------------------------------------------------- ladders
# A ladder is {"home": {s: p}, "away": {s: p}} where p = P(that team wins by more than s),
# plus "depth" (dollars of liquidity / open interest across the ladder) and "width" (avg spread).

def kalshi_ladders():
    out = {}
    for lg, series in (("nfl", "KXNFLSPREAD"), ("ncaaf", "KXNCAAFSPREAD")):
        cursor = ""
        while True:
            d = get(f"https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={series}"
                    f"&status=open&limit=1000" + (f"&cursor={cursor}" if cursor else ""))
            for m in d.get("markets", []):
                ev = m["event_ticker"]                       # KXNCAAFSPREAD-26OCT31KSUCOL
                codes = ev.split("-", 1)[1][7:]              # KSUCOL
                team = re.match(r"[A-Z&]+", m["ticker"].rsplit("-", 1)[1]).group(0)
                side = "away" if codes.startswith(team) else "home" if codes.endswith(team) else None
                if not side:
                    continue
                f = lambda k: float(m[k]) if m.get(k) not in (None, "") else None
                p, w = mid(f("yes_bid_dollars"), f("yes_ask_dollars"), f("last_price_dollars"))
                g = out.setdefault((lg, ev), {"lg": lg, "title": m.get("title", ""), "codes": codes,
                                              "home": {}, "away": {}, "names": {}, "depth": 0.0, "widths": []})
                g["names"][side] = re.sub(r"\s+wins by over.*$", "", m.get("title", ""))
                g["depth"] += f("open_interest_fp") or 0
                if p is not None:
                    g[side][float(m["floor_strike"])] = p
                    g["widths"].append(w)
            cursor = d.get("cursor") or ""
            if not cursor:
                break
    return list(out.values())


def poly_ladders(today):
    out = []
    for lg, series in (("nfl", "12185"), ("ncaaf", "12756")):
        offset = 0
        while True:
            evs = get(f"https://gamma-api.polymarket.com/events?series_id={series}&closed=false"
                      f"&limit=100&offset={offset}")
            if not evs:
                break
            for e in evs:
                day = (e.get("slug") or "")[-10:]
                if day < today:
                    continue
                title = e.get("title") or ""
                if " vs. " not in title:
                    continue
                away_n, home_n = title.split(" vs. ", 1)
                g = {"lg": lg, "slug": e["slug"], "names": {"away": away_n, "home": home_n},
                     "home": {}, "away": {}, "depth": 0.0, "widths": []}
                for m in e.get("markets", []):
                    if m.get("sportsMarketType") != "spreads":
                        continue
                    q = re.match(r"Spread:\s*(.+?)\s*\((-?[\d.]+)\)", m.get("question") or "")
                    if not q:
                        continue
                    team, line = q.group(1), abs(float(q.group(2)))
                    side = "away" if sim(team, away_n) >= sim(team, home_n) else "home"
                    try:
                        last = float(json.loads(m.get("outcomePrices") or "[]")[0])
                    except (ValueError, IndexError):
                        last = None
                    p, w = mid(m.get("bestBid"), m.get("bestAsk"), last)
                    g["depth"] += m.get("liquidityNum") or 0
                    if p is not None:
                        g[side][line] = p
                        g["widths"].append(w)
                out.append(g)
            offset += 100
    return out


def espn_lines(dates):
    """DraftKings main line from ESPN's public scoreboard: {(lg, away, home): (homeLine, homeOdds, awayOdds)}."""
    out = {}
    paths = {"nfl": "nfl/scoreboard?seasontype=2&dates=", "ncaaf": "college-football/scoreboard?groups=80&limit=400&dates="}
    for lg, p in paths.items():
        for day in dates:
            try:
                d = get(f"https://site.api.espn.com/apis/site/v2/sports/football/{p}{day}")
            except Exception:
                continue
            for e in d.get("events", []):
                c = e["competitions"][0]
                t = {x["homeAway"]: x["team"] for x in c["competitors"]}
                o = (c.get("odds") or [{}])[0].get("pointSpread", {})
                try:
                    line = float(o["home"]["close"]["line"])
                except (KeyError, ValueError, TypeError):
                    continue
                out[(lg, t["away"]["location"], t["home"]["location"])] = (
                    line, o["home"]["close"].get("odds"), o["away"]["close"].get("odds"))
    return out


# ---------------------------------------------------------------- math

def p_over(ladder, side, s):
    """P(side wins by more than s), linear between listed strikes, from both ladders."""
    pts = {}
    for k, p in ladder[side].items():
        pts[k] = p
    other = "home" if side == "away" else "away"
    for k, p in ladder[other].items():   # P(other wins by > k) = P(side margin < -k) -> P(side > -k) ~ 1-p
        pts.setdefault(-k, 1 - p)
    if not pts:
        return None
    xs = sorted(pts)
    if s in pts:
        return pts[s]
    lo = [x for x in xs if x < s]
    hi = [x for x in xs if x > s]
    if not lo or not hi:
        return None                      # outside the ladder: do not extrapolate
    a, b = lo[-1], hi[0]
    if b - a > 6:
        return None
    return pts[a] + (pts[b] - pts[a]) * (s - a) / (b - a)


def fair_home_line(ladder, near):
    """Home spread where P(home covers) = 50% (negative = home favored). Thin tail quotes can
    cross 50% too, so take the crossing nearest the pool's own number."""
    pts = dict((k, p) for k, p in ladder["home"].items())
    for k, p in ladder["away"].items():
        pts.setdefault(-k, 1 - p)
    xs = sorted(pts)
    found = []
    for a, b in zip(xs, xs[1:]):
        pa, pb = pts[a], pts[b]
        if (pa - 0.5) * (pb - 0.5) <= 0 and pa != pb and b - a <= 6:
            found.append(-(a + (0.5 - pa) * (b - a) / (pb - pa)))
    if not found:
        return None
    t = min(found, key=lambda f: abs(f - near))
    return round(t * 2) / 2 if abs(t * 2 - round(t * 2)) < 0.15 else round(t, 1)


def american_to_p(o):
    try:
        o = float(str(o).replace("+", ""))
    except ValueError:
        return None
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


# ---------------------------------------------------------------- matching

def match(game, ladders, key):
    best, score = None, 0.0
    for g in ladders:
        if g["lg"] != game["lg"]:
            continue
        if key == "kalshi" and g["codes"] == game["away"] + game["home"]:
            return g
        s = min(max(sim(n, g["names"].get(side, "")) for n in (game[side + "Name"], game.get(side + "Nick", "")))
                for side in ("away", "home"))
        if s > score:
            best, score = g, s
    return best if score >= 0.72 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=0)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    board = json.load(open(a.board, encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc)
    board = [g for g in board if datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00")) > now]
    days = sorted({(datetime.datetime.fromisoformat(g["start"].replace("Z", "+00:00"))
                    - datetime.timedelta(hours=5)).strftime("%Y%m%d") for g in board})
    today = (now - datetime.timedelta(hours=5)).strftime("%Y-%m-%d")

    K, P, D = kalshi_ladders(), poly_ladders(today), espn_lines(days)
    rows = []
    for g in board:
        L = g["hsp"]
        fav, dog = ("home", "away") if L < 0 else ("away", "home")
        s = abs(L)
        src = {}
        for name, lad in (("kalshi", match(g, K, "kalshi")), ("poly", match(g, P, "poly"))):
            if not lad:
                continue
            pf = p_over(lad, fav, s)
            width = sum(lad["widths"]) / len(lad["widths"]) if lad["widths"] else None
            src[name] = {"p_fav": pf, "fair": fair_home_line(lad, L), "depth": lad["depth"], "width": width}
        dk = None
        for (lg, an, hn), v in D.items():
            if lg == g["lg"] and sim(an, g["awayName"]) > 0.8 and sim(hn, g["homeName"]) > 0.8:
                dk = v
        # blend: weight each source by depth, damped by quote width
        num = den = 0.0
        for v in src.values():
            if v["p_fav"] is None:
                continue
            w = (min(v["depth"], 500000) ** 0.5) / (1 + 20 * (v["width"] or 0.05))
            num += w * v["p_fav"]
            den += w
        pf = num / den if den else None
        on_fav = pf is not None and pf >= 0.5
        pick = None if pf is None else f"{g[fav]} {-s:+g}" if on_fav else f"{g[dog]} {s:+g}"
        rows.append({"game": f"{g['away']}@{g['home']}", "lg": g["lg"], "start": g["start"], "poolHome": L,
                     "pick": pick, "onFav": on_fav, "p": None if pf is None else pf if on_fav else 1 - pf,
                     "kalshi": src.get("kalshi"), "poly": src.get("poly"), "dk": dk[0] if dk else None})

    def side_p(r, name):
        v = r.get(name)
        if not v or v["p_fav"] is None or r["p"] is None:
            return "  —  "
        mine = v["p_fav"] if r["onFav"] else 1 - v["p_fav"]
        return f"{mine*100:4.1f}%"

    def fl(v):
        return "—" if v is None else f"{v:+g}"

    rows.sort(key=lambda r: -(r["p"] or 0))
    if a.top:
        rows = rows[:a.top]
    print(f"Odds screen {now.astimezone(datetime.timezone(datetime.timedelta(hours=-5))).strftime('%a %m/%d %I:%M %p')} Central"
          " — cover % is AT THE POOL NUMBER; fair lines are home spreads")
    print(f"{'Game':12} {'Pool(H)':>7} {'Pick':12} {'Cover%':>6} {'Kalshi':>7} {'Poly':>7} "
          f"{'K fair':>6} {'P fair':>6} {'DK':>6}  K$OI/P$liq")
    for r in rows:
        k, p = r["kalshi"] or {}, r["poly"] or {}
        print(f"{r['game']:12} {r['poolHome']:+7g} {r['pick'] or '—':12} "
              f"{(r['p']*100 if r['p'] else 0):5.1f}% {side_p(r,'kalshi'):>7} {side_p(r,'poly'):>7} "
              f"{fl(k.get('fair')):>6} {fl(p.get('fair')):>6} {fl(r['dk']):>6}  "
              f"{int(k.get('depth') or 0)//1000}k/{int(p.get('depth') or 0)//1000}k")
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    sys.exit(main())
