"""tools/covers.py — store what the prediction markets said about each pool line at lock.

The pool's lines freeze when the board posts; the markets keep moving. For every finished game this
script looks up the Kalshi and Polymarket spread ladders as they stood when the pick locked
(Saturday 10 AM Central, or kickoff for a game played before that) and stores the blended
probability that the HOME side covers the POOL number:   data/covers.json = { gameId: 0.584 }.
The page turns that into each entrant's average cover % (the season table's CLV column). It is the
same measure tools/odds_screen.py prints before lock, read from price history instead of live quotes.

ingest.py runs it on every publish; by hand:  python tools/covers.py

Sources (public, no key):
  Kalshi      events?series_ticker=KXNFLSPREAD|KXNCAAFSPREAD, markets?event_ticker=,
              markets/candlesticks?market_tickers=a,b&start_ts=&end_ts=&period_interval=60
  Polymarket  gamma events?series_id=12185|12756&closed=true, clob prices-history?market=<token>
Past games keep no resting-liquidity figure, so the blend weights use Kalshi open interest and a
tenth of Polymarket volume. Polymarket does not list every college game; those are Kalshi only.
"""
import concurrent.futures as cf, datetime, difflib, gzip, json, pathlib, re, time, urllib.error, urllib.request

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "data"
COVERS = DATA / "covers.json"
UA = {"User-Agent": "CharityPicks odds screen (personal use)", "Accept-Encoding": "gzip"}
KALSHI = "https://api.elections.kalshi.com/trade-api/v2/"
MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def get(url, tries=6):
    for i in range(tries):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read()
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(1.5 * (i + 1))
        except Exception:  # noqa: BLE001 - network hiccup, try again
            time.sleep(1 + i)
    raise RuntimeError("no answer from " + url[:100])


def norm(s):
    s = (s or "").lower().replace("&", " and ").replace(".", " ")
    s = re.sub(r"\bst\b", "state", s)
    s = re.sub(r"\buniv(ersity)?\b|\bthe\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def when(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def near(d1, d2):
    return abs((d1 - d2).days) <= 1


def wanted(side, k, pool_home):
    """Only strikes within 4.5 points of the pool number matter for reading the cover probability."""
    margin = k if side == "home" else -k
    return abs(margin - (-pool_home)) <= 4.5


def p_home(points, pool_home):
    """P(home covers the pool number) from [(side, strike, P(side wins by more than strike))]."""
    m = {k: p for side, k, p in points if side == "home"}
    for side, k, p in points:
        if side == "away":
            m.setdefault(-k, 1 - p)
    s = -pool_home
    if s in m:
        return m[s]
    lo, hi = [x for x in m if x < s], [x for x in m if x > s]
    if not lo or not hi or min(hi) - max(lo) > 6:
        return None                      # outside the ladder: do not extrapolate
    a, b = max(lo), min(hi)
    return m[a] + (m[b] - m[a]) * (s - a) / (b - a)


# ---------------------------------------------------------------- event lists

def kalshi_events(year):
    out = []
    for lg, series in (("nfl", "KXNFLSPREAD"), ("ncaaf", "KXNCAAFSPREAD")):
        cursor = ""
        while True:
            d = get(f"{KALSHI}events?series_ticker={series}&limit=200" + (f"&cursor={cursor}" if cursor else ""))
            for e in d.get("events", []):
                m = re.match(r"(\d\d)([A-Z]{3})(\d\d)(.+)", e["event_ticker"].split("-", 1)[1])   # 26NOV07MIAND
                if not m or int(m.group(1)) != year % 100 or m.group(2) not in MONTHS:
                    continue
                out.append({"lg": lg, "ev": e["event_ticker"], "codes": m.group(4), "title": e.get("title", ""),
                            "day": datetime.date(year, MONTHS[m.group(2)], int(m.group(3)))})
            cursor = d.get("cursor") or ""
            if not cursor or not d.get("events"):
                break
    return out


def poly_events(first_day):
    out = []
    for lg, series in (("nfl", "12185"), ("ncaaf", "12756")):
        offset = 0
        while True:
            evs = get(f"https://gamma-api.polymarket.com/events?series_id={series}&closed=true&limit=100"
                      f"&offset={offset}&order=startDate&ascending=false")
            older = False
            for e in evs:
                slug, title = e.get("slug") or "", e.get("title") or ""
                d = re.search(r"(\d{4}-\d\d-\d\d)$", slug)       # "-exact-margin" events do not end in a date
                if not d or " vs. " not in title:
                    continue
                day = datetime.date.fromisoformat(d.group(1))
                if day < first_day:
                    older = True
                    continue
                away, home = title.split(" vs. ", 1)
                markets = []
                for m in e.get("markets", []):
                    q = re.match(r"Spread:\s*(.+?)\s*\((-?[\d.]+)\)", m.get("question") or "")
                    if m.get("sportsMarketType") != "spreads" or not q:
                        continue
                    try:
                        token = json.loads(m["clobTokenIds"])[0]
                    except (KeyError, ValueError, IndexError):
                        continue
                    side = "away" if sim(q.group(1), away) >= sim(q.group(1), home) else "home"
                    markets.append({"side": side, "k": abs(float(q.group(2))), "tok": token, "vol": m.get("volumeNum") or 0})
                out.append({"lg": lg, "day": day, "away": away, "home": home, "mk": markets})
            if not evs or older:
                break
            offset += 100
    return out


# ---------------------------------------------------------------- one game

def kalshi_cover(g, events):
    rams = lambda c: "LAR" if c == "LA" and g["lg"] == "nfl" else c       # Kalshi's code for the Rams
    codes = (g["away"] + g["home"], rams(g["away"]) + rams(g["home"]))
    ev = next((e for e in events if e["lg"] == g["lg"] and near(e["day"], g["day"]) and e["codes"] in codes), None)
    if not ev:
        return None
    sel = {}
    for m in get(f"{KALSHI}markets?event_ticker={ev['ev']}&limit=200").get("markets", []):
        team = re.match(r"[A-Z&]+", m["ticker"].rsplit("-", 1)[1]).group(0)
        side = "away" if ev["codes"].startswith(team) else "home" if ev["codes"].endswith(team) else None
        if side and wanted(side, float(m["floor_strike"]), g["hsp"]):
            sel[m["ticker"]] = (side, float(m["floor_strike"]))
    if not sel:
        return None
    c = get(f"{KALSHI}markets/candlesticks?market_tickers={','.join(sel)}"
            f"&start_ts={g['T'] - 8 * 3600}&end_ts={g['T'] + 60}&period_interval=60")
    points, depth, widths = [], 0.0, []
    for mk in c.get("markets", []):
        candles = [x for x in mk.get("candlesticks", []) if x["end_period_ts"] <= g["T"] + 60]
        if not candles:
            continue
        x = candles[-1]
        f = lambda a: float((x.get(a) or {}).get("close_dollars") or 0)
        bid, ask, last = f("yes_bid"), f("yes_ask"), f("price")
        if 0 < bid < ask and ask - bid <= 0.10:
            p, w = (bid + ask) / 2, ask - bid
        elif 0 < bid == ask < 1:
            p, w = bid, 0.01
        elif 0 < last < 1 and bid <= last <= ask:
            p, w = last, ask - bid
        else:
            continue
        points.append(sel[mk["market_ticker"]] + (p,))
        depth += float(x.get("open_interest_fp") or 0)
        widths.append(w)
    p = p_home(points, g["hsp"])
    return None if p is None else (p, (min(depth, 500000) ** 0.5) / (1 + 20 * sum(widths) / len(widths)))


def poly_cover(g, events):
    best, score = None, 0.0
    for e in events:
        if e["lg"] != g["lg"] or not near(e["day"], g["day"]):
            continue
        s = min(sim(g.get("awayName"), e["away"]), sim(g.get("homeName"), e["home"]))
        if s > score:
            best, score = e, s
    if not best or score < 0.72:
        return None
    points, volume = [], 0.0
    for m in best["mk"]:
        if not wanted(m["side"], m["k"], g["hsp"]):
            continue
        h = get(f"https://clob.polymarket.com/prices-history?market={m['tok']}"
                f"&startTs={g['T'] - 8 * 3600}&endTs={g['T'] + 60}&fidelity=10").get("history", [])
        h = [x for x in h if x["t"] <= g["T"] + 60]
        if h and 0 < h[-1]["p"] < 1:
            points.append((m["side"], m["k"], h[-1]["p"]))
            volume += m["vol"]
    p = p_home(points, g["hsp"])
    return None if p is None else (p, (min(volume / 10, 500000) ** 0.5) / (1 + 20 * 0.03))


def main():
    covers = json.loads(COVERS.read_text(encoding="utf-8")) if COVERS.exists() else {}
    todo = {}
    for f in sorted(DATA.glob("wk*.json")):
        week = json.loads(f.read_text(encoding="utf-8"))
        for gid, g in week.get("games", {}).items():
            if gid in covers or g.get("status") not in ("finished", "finalized") or g.get("hsp") is None:
                continue
            kickoff = when(g["start"])
            lock = min(kickoff, when(week["lockedAt"]))
            todo[gid] = dict(g, T=int(lock.timestamp()), day=(kickoff - datetime.timedelta(hours=6)).date())
    if not todo:
        return 0
    first = min(g["day"] for g in todo.values())
    K, P = kalshi_events(first.year), poly_events(first - datetime.timedelta(days=1))

    def one(item):
        gid, g = item
        num = den = 0.0
        for fn, events in ((kalshi_cover, K), (poly_cover, P)):
            try:
                r = fn(g, events)
            except Exception:  # noqa: BLE001 - one source failing must not lose the other
                r = None
            if r:
                num += r[0] * r[1]
                den += r[1]
        return gid, round(num / den, 3) if den else None

    with cf.ThreadPoolExecutor(6) as ex:
        found = {gid: v for gid, v in ex.map(one, todo.items()) if v is not None}
    if found:
        covers.update(found)
        COVERS.write_text(json.dumps(covers, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    missing = len(todo) - len(found)
    print(f"market cover: {len(found)} games added" + (f", {missing} not priced" if missing else ""))
    return len(found)


if __name__ == "__main__":
    main()
