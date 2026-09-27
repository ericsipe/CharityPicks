"""tools/ingest.py — merge data/incoming.json (from the collector) into data/, commit, push.

Run from anywhere:  python C:/Users/erics/CharityPicks/tools/ingest.py
Exit code 0 = published (or nothing new); anything else = look at the message.
"""
import json, pathlib, subprocess, sys, datetime

REPO = pathlib.Path(__file__).resolve().parent.parent
DATA = REPO / "data"
INCOMING = DATA / "incoming.json"
INDEX = DATA / "index.json"


def main() -> int:
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
        # Never overwrite a week that has picks with an empty collection (Splash hiccup).
        if path.exists() and not week["entries"]:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("entries"):
                print(f"{key}: incoming has 0 entries, keeping the stored {len(old['entries'])}")
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
