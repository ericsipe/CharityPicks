"""tools/ingest.py — merge data/incoming.json (from the collector) into data/, commit, push.

Run from anywhere:  python C:/Users/erics/CharityPicks/tools/ingest.py
Exit code 0 = published (or nothing new); anything else = look at the message.
"""
import json, pathlib, subprocess, sys, datetime, time

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "data"
INCOMING = DATA / "incoming.json"
INDEX = DATA / "index.json"


def hide_unplayed(week: dict) -> int:
    """Before the Saturday lock Splash shows other entries' picks only once a game kicks off, but
    it hands the signed-in entry (The Daddies) its own picks early. The site is public and pool-mates
    have the link, so drop every pick on a game that had not kicked off when the week was collected,
    until the lock has passed (Eric 11/22/26: locked until kickoff or 10 AM Saturday, whichever is
    sooner). Returns the number of picks dropped."""
    at, lock = week.get("collectedAt", ""), week.get("lockedAt", "")
    if not at or not lock or at >= lock:
        return 0
    games, dropped = week.get("games", {}), 0
    for e in week.get("entries", []):
        keep = [p for p in e.get("picks", []) if p[0] in games and games[p[0]].get("start", "9") <= at]
        dropped += len(e.get("picks", [])) - len(keep)
        e["picks"] = keep
    used = {p[0] for e in week.get("entries", []) for p in e["picks"]}
    for gid in [g for g in games if g not in used]:
        del games[gid]
    return dropped


def main() -> int:
    # The collector hands off 2.5 s after it returns and the task waits only ~3 s, so give the
    # receiver up to 20 s to write the file before calling the run a failure.
    for _ in range(40):
        if INCOMING.exists():
            break
        time.sleep(0.5)
    if not INCOMING.exists():
        print("no data/incoming.json; the collector did not hand anything off")
        return 2
    incoming = json.loads(INCOMING.read_text(encoding="utf-8"))
    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {
        "contest": "contest_01KZ49QZ2TCZS7ZVXTW175VHWZ", "name": "2026 Pick 5 For Charity", "weeks": []}
    by_file = {w["file"]: w for w in index["weeks"]}
    changed = []
    for key, week in incoming.items():
        if not key.startswith("wk") or not week.get("slate"):
            continue
        file = f"data/{key}.json"
        path = REPO / file
        hidden = hide_unplayed(week)
        if hidden:
            print(f"{key}: {hidden} picks on games not yet kicked off kept back until kickoff or lock")
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            # A week's slate id never changes: a different one means the collector grabbed the wrong week.
            if old.get("slate") and old["slate"] != week["slate"]:
                print(f"{key}: REFUSED, incoming slate {week['slate']} differs from stored {old['slate']}")
                continue
            # Never overwrite a week that has picks with an empty collection (Splash hiccup).
            if old.get("entries") and not week["entries"]:
                print(f"{key}: incoming has 0 entries, keeping the stored {len(old['entries'])}")
                continue
        else:
            # A new week must lock later than every stored week.
            later = [json.loads((REPO / w["file"]).read_text(encoding="utf-8")).get("lockedAt", "") for w in index["weeks"] if (REPO / w["file"]).exists()]
            if later and week.get("lockedAt", "") <= max(later):
                print(f"{key}: REFUSED, lock {week.get('lockedAt')} is not after the stored weeks")
                continue
        path.write_text(json.dumps(week, separators=(",", ":")), encoding="utf-8")
        by_file[file] = {"file": file, "slate": week["slate"], "label": week.get("label", key),
                         "title": week.get("title", ""), "dates": week.get("dates", "")}
        changed.append(f"{key} ({len(week['entries'])} entries)")
    index["weeks"] = sorted(by_file.values(), key=lambda w: int(w["file"][7:-5]))
    INDEX.write_text(json.dumps(index, indent=1), encoding="utf-8")
    INCOMING.unlink()
    if not changed:
        print("nothing new")
        return 0
    # Market cover % and closing lines for newly finished games (the page's CLV column and pick
    # tooltips). Never let either stop a publish.
    for name in ("covers", "closes"):
        try:
            __import__(name).main()
        except Exception as e:  # noqa: BLE001
            print(f"{name} skipped: {e}")
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = f"Collector: {', '.join(changed)} at {stamp}"
    for cmd in (["git", "add", "data"], ["git", "commit", "-q", "-m", msg], ["git", "push", "-q", "origin", "main"]):
        r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"{' '.join(cmd)} failed: {r.stderr.strip() or r.stdout.strip()}")
            return 3
    print("published:", msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
