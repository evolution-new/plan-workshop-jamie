#!/usr/bin/env python3
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


DATA_FILE = os.environ.get("JAMIE_PLAN_DATA", "/opt/jamie-plan-api/data/state.json")
HOST = os.environ.get("JAMIE_PLAN_HOST", "127.0.0.1")
PORT = int(os.environ.get("JAMIE_PLAN_PORT", "8771"))

STORE_LOCK = threading.Lock()
STORE = {"state": None, "version": 0, "updated_at": None}


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_parent(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)


def read_store():
    if not os.path.exists(DATA_FILE):
        return {"state": None, "version": 0, "updated_at": None}
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return {
        "state": payload.get("state"),
        "version": int(payload.get("version") or 0),
        "updated_at": payload.get("updated_at"),
    }


def write_store(payload):
    ensure_parent(DATA_FILE)
    fd, tmp_path = tempfile.mkstemp(prefix="jamie-plan-", suffix=".json", dir=os.path.dirname(DATA_FILE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(tmp_path, DATA_FILE)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if urlparse(self.path).path != "/state":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return
        with STORE_LOCK:
            payload = {
                "ok": True,
                "state": STORE.get("state"),
                "version": STORE.get("version", 0),
                "updated_at": STORE.get("updated_at"),
            }
        self.send_json(200, payload)

    def do_PUT(self):
        if urlparse(self.path).path != "/state":
            self.send_json(404, {"ok": False, "error": "not_found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"ok": False, "error": "bad_length"})
            return

        raw_body = self.rfile.read(content_length or 0)
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_json(400, {"ok": False, "error": "bad_json"})
            return

        state = payload.get("state")
        if not isinstance(state, dict) or not isinstance(state.get("blocks"), list):
            self.send_json(400, {"ok": False, "error": "bad_state"})
            return

        with STORE_LOCK:
            STORE["state"] = state
            STORE["version"] = int(STORE.get("version", 0)) + 1
            STORE["updated_at"] = now_iso()
            write_store(STORE)
            response = {
                "ok": True,
                "state": STORE["state"],
                "version": STORE["version"],
                "updated_at": STORE["updated_at"],
            }
        self.send_json(200, response)


def main():
    global STORE
    STORE = read_store()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Jamie plan API listening on http://{HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
