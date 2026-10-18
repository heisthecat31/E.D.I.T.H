"""Move the old local memory (H:\\SatelliteAI\\memory.json) into her brain on the server, as one
player's record (docs/brainplan.md). Their profile, notes, places, what they taught her, events.

    python tools/import_memory.py --name "<in-game name>" --brain https://sparkapi-production-e6df.up.railway.app
    (the admin token comes from the EDITH_ADMIN_TOKEN environment variable, never the command line)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--brain", default="https://sparkapi-production-e6df.up.railway.app")
    ap.add_argument("--memory", default=r"H:\SatelliteAI\memory.json")
    a = ap.parse_args()
    token = os.environ.get("EDITH_ADMIN_TOKEN")
    if not token:
        print("set EDITH_ADMIN_TOKEN first")
        return 1
    mem = json.loads(Path(a.memory).read_text(encoding="utf-8"))
    rec = {k: mem[k] for k in ("facts", "events", "turns", "places", "learned", "profile") if k in mem}
    pts = (mem.get("points") or {}).get(a.name)                   # her points for you ({nice, mean, at})
    if pts:
        rec["points"] = {"nice": int(pts.get("nice", 0)), "mean": float(pts.get("mean", 0)),
                         "mean_at": float(pts.get("at", 0)), "streak": 0}
    url = f"{a.brain.rstrip('/')}/edith/brain/player/{urllib.parse.quote(a.name, safe='')}"
    req = urllib.request.Request(url, data=json.dumps(rec).encode(), method="PUT",
                                 headers={"X-Admin-Token": token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.status, r.read().decode())
    print(f"{a.name}: {len(rec.get('events', []))} events, {len(rec.get('learned', []))} taught, "
          f"{len(rec.get('places', {}))} places")
    return 0


if __name__ == "__main__":
    sys.exit(main())
