"""Fetch a catalog ISO onto the payload, then the install path is the same.

Writes ``images/<name>.iso`` under the payload. Resume uses a ``.part``
file. Checksum is SHA-256 of the finished file (verify three times:
download, USB write, customer install).
"""

from __future__ import annotations

import hashlib
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from urllib.parse import unquote, urlparse

from firstboot.payload import FILE_RE, Edition

USER_AGENT = "FirstBootLinux/1.0"
CHUNK = 256 * 1024
SLACK = 64 * 1024 * 1024


class DownloadError(Exception):
    """A customer-visible download failure."""


def edition_relpath(edition: Edition) -> str:
    if isinstance(edition.file, str) and FILE_RE.fullmatch(edition.file):
        return edition.file
    if edition.url:
        base = os.path.basename(unquote(urlparse(edition.url).path))
        rel = f"images/{base}"
        if FILE_RE.fullmatch(rel):
            return rel
    raise DownloadError("This edition has no image file name.")


def edition_dest(payload_root: str, edition: Edition) -> str:
    return os.path.abspath(os.path.join(payload_root, edition_relpath(edition)))


def free_bytes(path: str) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def dest_is_payload_image(payload_root: str, dest: str) -> bool:
    root = os.path.abspath(payload_root)
    path = os.path.abspath(dest)
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        return False
    return FILE_RE.fullmatch(rel.replace("\\", "/")) is not None


def _sha256_file(path: str, size: int = 0) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if size and os.path.getsize(path) != size:
        raise DownloadError("The image size does not match the catalog.")
    return digest.hexdigest()


def _already_good(dest: str, sha256: str, size_bytes: int) -> bool:
    if not os.path.isfile(dest):
        return False
    try:
        got = _sha256_file(dest, size_bytes)
    except OSError:
        return False
    except DownloadError:
        return False
    return got == sha256.strip().lower()


def download_iso(
    url: str,
    dest: str,
    sha256: str,
    size_bytes: int,
    *,
    on_progress: Callable[[int], None] | None = None,
) -> None:
    if not url.startswith(("https://", "http://")):
        raise DownloadError("The download address is not valid.")
    want = sha256.strip().lower()
    if len(want) != 64:
        raise DownloadError("The catalog checksum is not valid.")
    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise DownloadError(f"Cannot write the image: {exc}") from exc
    if _already_good(dest, want, size_bytes):
        if on_progress:
            on_progress(100)
        return

    part = dest + ".part"
    have = 0
    if os.path.isfile(part):
        try:
            have = os.path.getsize(part)
        except OSError:
            have = 0
        if size_bytes and have > size_bytes:
            try:
                os.remove(part)
            except OSError:
                pass
            have = 0

    need = max(size_bytes - have, 0) + SLACK
    try:
        avail = free_bytes(parent)
    except OSError:
        avail = need
    if avail < need:
        gb = need / 1_000_000_000
        raise DownloadError(
            f"Not enough space for this image (need about {gb:.1f} GB free)."
        )

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if have > 0:
        req.add_header("Range", f"bytes={have}-")
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    except urllib.error.HTTPError as exc:
        if have > 0 and exc.code == 416:
            have = 0
            try:
                os.remove(part)
            except OSError:
                pass
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                resp = urllib.request.urlopen(req, timeout=30, context=ctx)
            except (urllib.error.URLError, OSError) as exc2:
                raise DownloadError(f"Download failed: {exc2}") from exc2
        else:
            raise DownloadError(f"Download failed (HTTP {exc.code}).") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise DownloadError(f"Download failed: {exc}") from exc

    status = getattr(resp, "status", None)
    if status is None:
        status = resp.getcode()
    if status == 200:
        have = 0
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    elif status == 206:
        flags = os.O_WRONLY | os.O_APPEND
        if not os.path.isfile(part):
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            have = 0
    else:
        resp.close()
        raise DownloadError(f"Download failed (HTTP {status}).")

    digest = hashlib.sha256()
    if have > 0:
        try:
            with open(part, "rb") as prev:
                while True:
                    chunk = prev.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
        except OSError as exc:
            resp.close()
            raise DownloadError(f"Cannot resume the download: {exc}") from exc

    total = size_bytes or have
    if status == 200:
        try:
            length = int(resp.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length:
            total = length
    elif status == 206 and size_bytes:
        total = size_bytes

    got = have
    last_pct = -1

    def report(pct: int) -> None:
        nonlocal last_pct
        if on_progress and pct != last_pct:
            last_pct = pct
            on_progress(pct)

    report(min(99, got * 100 // total) if total else 0)

    try:
        with os.fdopen(os.open(part, flags, 0o644), "wb") as out:
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                got += len(chunk)
                if total:
                    report(min(99, got * 100 // total))
    except OSError as exc:
        raise DownloadError(f"Cannot write the image: {exc}") from exc
    finally:
        resp.close()

    if size_bytes and got != size_bytes:
        try:
            os.remove(part)
        except OSError:
            pass
        raise DownloadError(
            "The download did not finish. Try again when the network is steady."
        )
    if digest.hexdigest() != want:
        try:
            os.remove(part)
        except OSError:
            pass
        raise DownloadError("The image is damaged. It does not match the checksum.")
    try:
        os.replace(part, dest)
    except OSError as exc:
        raise DownloadError(f"Cannot store the image: {exc}") from exc
    if on_progress:
        on_progress(100)
