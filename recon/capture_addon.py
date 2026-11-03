"""mitmproxy addon: capture Alf/Onics cloud traffic to recon/raw/.

Run with:
    mitmdump -s recon/capture_addon.py

Pure helpers below have no mitmproxy dependency so they are unit-testable.
The addon class accesses the injected flow object duck-typed.
"""
from __future__ import annotations

import gzip
import json
import re
import zlib
from pathlib import Path
from typing import Any

# Widen/narrow during recon as the real hosts are discovered. Over-capture is
# safe because recon/raw/ is git-ignored.
TARGET_HOST_SUFFIXES: tuple[str, ...] = (
    "lfhub", "lansforsakringar", "lf.se", "bankid",
    "alf.se", "onics", "develco", "iotdevice.io", "squid.link",
)

RAW_DIR = Path(__file__).resolve().parent / "raw"
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def is_target_host(host: str) -> bool:
    lowered = host.lower()
    return any(suffix in lowered for suffix in TARGET_HOST_SUFFIXES)


def decompress_body(raw: bytes, content_encoding: str | None) -> bytes:
    """Undo content-encoding so the body can be stored as readable text.

    mitmproxy normally hands over decoded bytes, but when its own decoding fails it
    returns the compressed stream instead. Storing that as text replaces every
    non-UTF-8 byte with U+FFFD and the payload is gone for good, so decompress here
    rather than trusting the caller. Sniffing the gzip magic comes first because it
    is the only signal that stays correct either way: an already-decoded body has no
    magic and is returned untouched, header or no header.
    """
    try:
        if raw[:2] == b"\x1f\x8b":
            return gzip.decompress(raw)
        encoding = (content_encoding or "").lower().strip()
        if encoding == "deflate":
            return zlib.decompress(raw, -zlib.MAX_WBITS)
        if encoding == "br":
            import brotli  # only installed with the [capture] extra

            return brotli.decompress(raw)
    except Exception:  # noqa: BLE001 - a body we can't decompress is still worth storing
        return raw
    return raw


def parse_body(
    content_type: str | None, raw: bytes | None, content_encoding: str | None = None
) -> Any:
    if not raw:
        return None
    text = decompress_body(raw, content_encoding).decode("utf-8", errors="replace")
    if content_type and "json" in content_type.lower():
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def build_record(
    *, method: str, url: str, host: str, path: str, status: int,
    req_headers: dict[str, str], req_body: Any,
    resp_headers: dict[str, str], resp_body: Any,
) -> dict:
    return {
        "method": method,
        "url": url,
        "host": host,
        "path": path,
        "status": status,
        "request": {"headers": req_headers, "body": req_body},
        "response": {"headers": resp_headers, "body": resp_body},
    }


class AlfCaptureAddon:
    def __init__(self) -> None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def response(self, flow: Any) -> None:
        host = flow.request.pretty_host
        if not is_target_host(host):
            return
        self._counter += 1
        record = build_record(
            method=flow.request.method,
            url=flow.request.pretty_url,
            host=host,
            path=flow.request.path.split("?", 1)[0],
            status=flow.response.status_code,
            req_headers=dict(flow.request.headers),
            req_body=parse_body(
                flow.request.headers.get("content-type"),
                flow.request.get_content(strict=False),
                flow.request.headers.get("content-encoding"),
            ),
            resp_headers=dict(flow.response.headers),
            resp_body=parse_body(
                flow.response.headers.get("content-type"),
                flow.response.get_content(strict=False),
                flow.response.headers.get("content-encoding"),
            ),
        )
        name = _SAFE.sub("_", f"{self._counter:04d}_{flow.request.method}_{record['path']}")
        (RAW_DIR / f"{name}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
        )


addons = [AlfCaptureAddon()]
