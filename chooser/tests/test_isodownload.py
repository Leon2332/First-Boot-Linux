#!/usr/bin/env python3
"""ISO catalog download — local HTTP, no GTK."""

from __future__ import annotations

import hashlib
import http.server
import os
import sys
import tempfile
import threading
import unittest
HERE = os.path.dirname(os.path.abspath(__file__))
CHOOSER_DIR = os.path.dirname(HERE)
if CHOOSER_DIR not in sys.path:
    sys.path.insert(0, CHOOSER_DIR)

from firstboot.isodownload import (  # noqa: E402
    DownloadError,
    dest_is_payload_image,
    download_iso,
    edition_relpath,
)
from firstboot.payload import Edition  # noqa: E402

ZERO = "0" * 64
BODY = b"first-boot-iso-bytes" * 1024
SHA = hashlib.sha256(BODY).hexdigest()


def _ed(**kwargs: object) -> Edition:
    base: dict = {
        "id": "plasma",
        "name": "KDE Plasma",
        "default": True,
        "claimed_local": False,
        "file": None,
        "url": "https://example.invalid/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
        "sha256": ZERO,
        "size_bytes": len(BODY),
        "available": False,
    }
    base.update(kwargs)
    return Edition(**base)


class _Handler(http.server.BaseHTTPRequestHandler):
    payload = BODY

    def log_message(self, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        data = self.payload
        start = 0
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            spec = rng.split("=", 1)[1]
            start_s, _, _end = spec.partition("-")
            try:
                start = int(start_s or "0")
            except ValueError:
                start = 0
            chunk = data[start:]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.send_header("Content-Length", str(len(chunk)))
            self.end_headers()
            self.wfile.write(chunk)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class RelpathTests(unittest.TestCase):
    def test_uses_file_when_present(self) -> None:
        ed = _ed(file="images/linuxmint-22.3-mate-64bit.iso")
        self.assertEqual(edition_relpath(ed), "images/linuxmint-22.3-mate-64bit.iso")

    def test_filename_from_url(self) -> None:
        ed = _ed()
        self.assertEqual(
            edition_relpath(ed),
            "images/Fedora-KDE-Desktop-Live-44-1.7.x86_64.iso",
        )

    def test_rejects_escape(self) -> None:
        ed = _ed(file=None, url="https://example.invalid/../etc/passwd")
        with self.assertRaises(DownloadError):
            edition_relpath(ed)

    def test_dest_must_stay_under_images(self) -> None:
        self.assertTrue(
            dest_is_payload_image("/run/payload", "/run/payload/images/a.iso")
        )
        self.assertFalse(
            dest_is_payload_image("/run/payload", "/run/payload/../etc/a.iso")
        )
        self.assertFalse(
            dest_is_payload_image("/run/payload", "/tmp/a.iso")
        )


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address[:2]
        self.url = f"http://{host}:{port}/os.iso"

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def test_download_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "images", "os.iso")
            seen: list[int] = []
            download_iso(self.url, dest, SHA, len(BODY), on_progress=seen.append)
            self.assertTrue(os.path.isfile(dest))
            with open(dest, "rb") as fh:
                self.assertEqual(fh.read(), BODY)
            self.assertEqual(seen[-1], 100)
            self.assertFalse(os.path.isfile(dest + ".part"))

    def test_skip_if_already_good(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "images", "os.iso")
            os.makedirs(os.path.dirname(dest))
            with open(dest, "wb") as fh:
                fh.write(BODY)
            download_iso(self.url, dest, SHA, len(BODY))
            self.assertEqual(os.path.getsize(dest), len(BODY))

    def test_resume_part(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "images", "os.iso")
            os.makedirs(os.path.dirname(dest))
            with open(dest + ".part", "wb") as fh:
                fh.write(BODY[:100])
            download_iso(self.url, dest, SHA, len(BODY))
            with open(dest, "rb") as fh:
                self.assertEqual(fh.read(), BODY)

    def test_bad_checksum_deletes_part(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "images", "os.iso")
            with self.assertRaises(DownloadError) as ctx:
                download_iso(self.url, dest, ZERO, len(BODY))
            self.assertIn("checksum", str(ctx.exception).lower())
            self.assertFalse(os.path.isfile(dest))
            self.assertFalse(os.path.isfile(dest + ".part"))


if __name__ == "__main__":
    unittest.main()
