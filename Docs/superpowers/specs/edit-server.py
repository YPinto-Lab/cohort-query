#!/usr/bin/env python3
"""Serve one spec .html and write its pencil edits back to disk.

Run:  python3 edit-server.py 2026-06-17-askslm-architecture-hld-lld.html
Open: http://127.0.0.1:8000  — edit titles/text, click "Save to disk".

The page POSTs the edited content region; this splices it between the
<!--EDITABLE-START--> / <!--EDITABLE-END--> markers in the source file,
leaving head, nav, and scripts untouched so git sees only the text changes.

ponytail: dev-only doc editor — single file, stdlib only, no auth (localhost).
"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

START_MARKER = "<!--EDITABLE-START-->"
END_MARKER = "<!--EDITABLE-END-->"
TARGET: Path = None


class SpecEditor(BaseHTTPRequestHandler):
    def do_GET(self):
        self._reply(code=200, body=TARGET.read_text(encoding="utf-8"), content_type="text/html")

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        new_region = self.rfile.read(length).decode("utf-8")
        self._splice_region(new_region)
        self._reply(code=200, body="saved", content_type="text/plain")

    def _splice_region(self, new_region):
        source = TARGET.read_text(encoding="utf-8")
        before = source.split(START_MARKER)[0]
        after = source.split(END_MARKER, 1)[1]
        rebuilt = f"{before}{START_MARKER}\n{new_region}\n{END_MARKER}{after}"
        TARGET.write_text(rebuilt, encoding="utf-8")

    def _reply(self, code, body, content_type):
        payload = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")  # always re-fetch — no stale renders after an edit
        self.end_headers()
        self.wfile.write(payload)


def main():
    global TARGET
    TARGET = Path(sys.argv[1]).resolve()
    HTTPServer(("127.0.0.1", 8000), SpecEditor).serve_forever()


if __name__ == "__main__":
    main()
