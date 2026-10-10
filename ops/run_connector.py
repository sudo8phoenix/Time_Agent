"""Automatically drain committed snapshots to MOCK PMIS — prototype."""
import argparse
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.db.session import session_factory
from app.integrations.mock_pmis import MockPMISConnector
from app.integrations.outbox import run_once


def main():
    parser = argparse.ArgumentParser(description="MOCK PMIS — prototype outbox worker")
    parser.add_argument("--url", default="http://127.0.0.1:8091")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    connector = MockPMISConnector(args.url)
    while True:
        worked = run_once(session_factory, connector)
        if args.once:
            return
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
