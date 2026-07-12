# recon/redact.py
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REDACTED = "<REDACTED>"

# Header names whose entire value is wiped (compared case-insensitively).
SENSITIVE_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie",
    "x-api-key", "x-auth-token", "x-access-token",
})

# JSON keys wiped when any of these appears as a case-insensitive substring.
SENSITIVE_KEY_PATTERNS = (
    "token", "secret", "password", "passwd", "authorization", "auth",
    "personnummer", "pnr", "ssn", "refresh", "bankid", "ocsp",
    "signature", "sessionid", "session_id", "cookie", "credential",
)

# Swedish personnummer: 10 or 12 digits with optional separator. Over-matches
# some numeric blobs on purpose - safety over fidelity.
_PERSONNUMMER_RE = re.compile(r"\b(?:19|20)?\d{6}[-+]?\d{4}\b")
# JWT / three-part base64url blobs.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{4,}\b")
# Sensitive values in form-urlencoded / query strings (OAuth token exchanges).
_FORM_SECRET_RE = re.compile(
    r"(^|[?&])(client_secret|refresh_token|access_token|id_token|password|code)=([^&#\s]+)",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    text = _JWT_RE.sub(REDACTED, text)
    text = _PERSONNUMMER_RE.sub(REDACTED, text)
    text = _FORM_SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}={REDACTED}", text)
    return text


def _key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)


def redact_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            key: (REDACTED if _key_is_sensitive(key) else redact_json(value))
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact_json(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in headers.items():
        if name.lower() in SENSITIVE_HEADERS:
            result[name] = REDACTED
        else:
            result[name] = redact_text(value)
    return result


def _redact_side(side: Any) -> Any:
    if not isinstance(side, dict):
        return side
    out = dict(side)
    if isinstance(side.get("headers"), dict):
        out["headers"] = redact_headers(side["headers"])
    if "body" in side:
        out["body"] = redact_json(side["body"])
    return out


def redact_record(record: dict) -> dict:
    out = dict(record)
    if isinstance(record.get("url"), str):
        out["url"] = redact_text(record["url"])
    if "request" in record:
        out["request"] = _redact_side(record["request"])
    if "response" in record:
        out["response"] = _redact_side(record["response"])
    return out


def redact_dir(src: Path, dst: Path) -> int:
    """Redact every *.json record in src into dst. Returns the count processed."""
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in sorted(src.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        (dst / path.name).write_text(
            json.dumps(redact_record(record), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        count += 1
    return count


if __name__ == "__main__":
    src_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("recon/raw")
    dst_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("recon/fixtures")
    print(f"redacted {redact_dir(src_dir, dst_dir)} records into {dst_dir}")
