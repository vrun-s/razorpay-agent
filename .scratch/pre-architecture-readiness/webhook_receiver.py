#!/usr/bin/env python3
"""Throwaway local webhook receiver for the halted-subscription empirical test.

Not part of the app. Prints every incoming POST body + headers so we can see
which Razorpay events arrive (and when) while manually forcing a subscription
through its retry ladder in the dashboard. Delete this file once the
empirical test in .scratch/pre-architecture-readiness/spec.md is resolved.

Usage:
    python webhook_receiver.py [port]   # default port 8787

Then, in another terminal, tunnel it to a public URL:
    ssh -R 80:localhost:8787 nokey@localhost.run

localhost.run prints a public https:// URL — register THAT as the Razorpay
webhook URL (Dashboard -> Settings -> Webhooks -> Add New Webhook).
"""
import sys
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        ts = datetime.now().isoformat(timespec="seconds")

        print(f"\n{'=' * 60}")
        print(f"[{ts}] POST {self.path}")
        print(f"{'-' * 60}")
        sig = self.headers.get("X-Razorpay-Signature")
        event_id = self.headers.get("X-Razorpay-Event-Id")
        if sig:
            print(f"X-Razorpay-Signature: {sig}")
        if event_id:
            print(f"X-Razorpay-Event-Id: {event_id}")
        try:
            payload = json.loads(body)
            print(json.dumps(payload, indent=2))
            event = payload.get("event", "<no 'event' field>")
            print(f"\n>>> event = {event}")
        except json.JSONDecodeError:
            print(body.decode(errors="replace"))
        print(f"{'=' * 60}\n")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, fmt, *args):
        pass  # silence default access logging; our own print is the log


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"Listening on http://localhost:{port} (Ctrl-C to stop)")
    print("Tunnel it publicly with: ssh -R 80:localhost:%d nokey@localhost.run" % port)
    HTTPServer(("localhost", port), Handler).serve_forever()
