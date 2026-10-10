"""Separate loopback HTTP receiver with durable SQLite state. MOCK PMIS — prototype."""
import argparse
import json
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

LABEL = "MOCK PMIS — prototype"


def create_server(path, port=8091):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS activities (project TEXT, version TEXT, activity TEXT, revision INTEGER, payload TEXT, PRIMARY KEY(project,version,activity))")
        db.execute("CREATE TABLE IF NOT EXISTS receipts (key TEXT PRIMARY KEY, payload TEXT, receipt TEXT)")
    class Handler(BaseHTTPRequestHandler):
        def respond(self, code, data):
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            parts = self.path.split("/")
            if len(parts) != 5 or parts[1] != "activities":
                return self.respond(404, {"label": LABEL})
            with sqlite3.connect(path) as db:
                row = db.execute("SELECT payload FROM activities WHERE project=? AND version=? AND activity=?", tuple(unquote(p) for p in parts[2:])).fetchone()
            self.respond(200 if row else 404, json.loads(row[0]) if row else {"label": LABEL})

        def do_POST(self):
            if self.path != "/updates":
                return self.respond(404, {"label": LABEL})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 100000:
                    raise ValueError("Invalid body size")
                p = json.loads(self.rfile.read(length))
                for name in ("project_id", "activity_id", "source_schedule_version", "state", "idempotency_key"):
                    if name not in p:
                        raise ValueError("Missing mapping field")
                keys = (p["external_project_id"], p["source_schedule_version_id"], p["external_activity_id"])
                if not all(isinstance(k, str) and k.strip() for k in keys) or p["label"] != LABEL or not isinstance(p["state_revision"], int) or p["state_revision"] < 1 or not p["idempotency_key"]:
                    raise ValueError("Invalid mapping or revision")
                for kind in ("actual_start", "actual_finish"):
                    e = p["state"][kind]
                    if e and ((e["precision"] == "date" and e.get("local_time") is not None) or (e["precision"] != "date" and not e.get("local_time"))):
                        raise ValueError("Incompatible endpoint precision")
            except (ValueError, KeyError, TypeError):
                return self.respond(422, {"label": LABEL, "error": "Invalid contract/mapping/precision"})
            raw = json.dumps(p, sort_keys=True)
            with sqlite3.connect(path, timeout=10) as db:
                db.execute("BEGIN IMMEDIATE")
                previous = db.execute("SELECT payload,receipt FROM receipts WHERE key=?", (p["idempotency_key"],)).fetchone()
                if previous:
                    return self.respond(200 if previous[0] == raw else 409, json.loads(previous[1]) if previous[0] == raw else {"error": "Idempotency key conflict", "label": LABEL})
                current = db.execute("SELECT revision,payload FROM activities WHERE project=? AND version=? AND activity=?", keys).fetchone()
                if current and current[0] == p["state_revision"] and json.loads(current[1])["state"] != p["state"]:
                    return self.respond(409, {"label": LABEL, "error": "Revision conflict"})
                # A new schedule needs a separate mapping namespace. Reusing an existing
                # namespace with a changed internal activity/version number is rejected.
                if current and any(json.loads(current[1])[k] != p[k] for k in ("activity_id", "source_schedule_version", "project_id")):
                    return self.respond(409, {"label": LABEL, "error": "Mapping/version conflict"})
                applied = current is None or current[0] < p["state_revision"]
                if applied:
                    db.execute("INSERT OR REPLACE INTO activities VALUES (?,?,?,?,?)", (*keys, p["state_revision"], raw))
                receipt = {"label": LABEL, "idempotency_key": p["idempotency_key"], "applied": applied,
                           "received_at": datetime.now(timezone.utc).isoformat(), "state_revision": p["state_revision"]}
                db.execute("INSERT INTO receipts VALUES (?,?,?)", (p["idempotency_key"], raw, json.dumps(receipt)))
            self.respond(200, receipt)

        def log_message(self, *_args):
            pass
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=LABEL)
    parser.add_argument("--db", default="mock-pmis.sqlite3")
    parser.add_argument("--port", type=int, default=8091)
    args = parser.parse_args()
    print(LABEL, flush=True)
    create_server(args.db, args.port).serve_forever()
