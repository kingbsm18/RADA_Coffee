"""Replay a scenario against a running backend (events) and write the matching POS CSV.

Example:
    export RADA_EDGE_KEY=...            # shown once when the site was created
    python simulator/replay.py --scenario missing_sale --csv-out sales.csv
Then import sales.csv from the dashboard/API. Use --run-id for a fresh run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fake_detector  # noqa: E402


def post_event(url: str, edge_key: str, event: dict) -> int:
    request = urllib.request.Request(
        f"{url.rstrip('/')}/api/v1/events",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json", "X-Edge-Key": edge_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--scenarios", default=str(Path(__file__).with_name("scenarios.yaml")))
    parser.add_argument("--scenario", help="scenario name (see --list)")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--site-id", help="override the site id from the scenario file")
    parser.add_argument("--start", help="ISO start time with offset (default: 2 hours ago)")
    parser.add_argument("--run-id", default="", help="salt for event ids; change it to replay for real")
    parser.add_argument("--csv-out", help="write the matching POS sales CSV here")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, send nothing")
    args = parser.parse_args(argv)

    config = fake_detector.load(args.scenarios)
    if args.list or not args.scenario:
        for name, scenario in config["scenarios"].items():
            print(f"{name:26} {scenario['description']}")
        return 0
    if args.site_id:
        config["defaults"]["site_id"] = args.site_id

    now = datetime.now(timezone.utc)
    start = datetime.fromisoformat(args.start) if args.start else (now - timedelta(hours=2)).replace(
        minute=0, second=0, microsecond=0
    )
    built = fake_detector.build(config, args.scenario, start=start, run_id=args.run_id)

    if args.csv_out:
        Path(args.csv_out).write_text(fake_detector.sales_csv(built.sales), encoding="utf-8")
        print(f"wrote {len(built.sales)} sale rows to {args.csv_out}")
    print(f"{len(built.events)} events, expected final states: {dict(Counter(built.expectations.values()))}")
    if args.dry_run:
        return 0

    edge_key = os.environ.get("RADA_EDGE_KEY")
    if not edge_key:
        print("set RADA_EDGE_KEY (never pass keys on the command line)", file=sys.stderr)
        return 2
    codes = Counter(post_event(args.backend_url, edge_key, event) for event in built.events)
    print("responses:", dict(codes), "(201 created, 200 duplicate, 409 conflict: use --run-id)")
    return 0 if set(codes) <= {200, 201} else 1


if __name__ == "__main__":
    raise SystemExit(main())
