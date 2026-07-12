# tests/test_redact.py
import json

from recon.redact import (
    REDACTED,
    redact_dir,
    redact_headers,
    redact_json,
    redact_record,
    redact_text,
)


def test_authorization_header_is_wiped():
    assert redact_headers({"Authorization": "Bearer eyJabc.def.ghi"}) == {"Authorization": REDACTED}


def test_non_sensitive_header_is_kept():
    assert redact_headers({"Content-Type": "application/json"}) == {"Content-Type": "application/json"}


def test_cookie_headers_are_wiped_case_insensitively():
    out = redact_headers({"cookie": "a=1", "Set-Cookie": "s=2"})
    assert out == {"cookie": REDACTED, "Set-Cookie": REDACTED}


def test_jwt_in_free_text_is_redacted():
    token = "eyJhbGciOi.eyJzdWIiOi.SIG_nature123"
    assert redact_text(f"token={token}") == "token=" + REDACTED


def test_personnummer_is_redacted():
    assert redact_text("user 19900101-1234 logged in") == "user " + REDACTED + " logged in"
    assert redact_text("id 199001011234") == "id " + REDACTED


def test_sensitive_json_keys_are_wiped():
    payload = {"access_token": "abc", "refreshToken": "def", "name": "Alice"}
    assert redact_json(payload) == {"access_token": REDACTED, "refreshToken": REDACTED, "name": "Alice"}


def test_redact_json_recurses_dicts_and_lists():
    payload = {"outer": [{"password": "p", "keep": "v"}]}
    assert redact_json(payload) == {"outer": [{"password": REDACTED, "keep": "v"}]}


def test_redact_record_covers_url_headers_and_bodies():
    record = {
        "method": "POST",
        "url": "https://api.example/login?pnr=199001011234",
        "host": "api.example",
        "path": "/login",
        "status": 200,
        "request": {"headers": {"Authorization": "Bearer x"}, "body": {"password": "p"}},
        "response": {"headers": {"Set-Cookie": "s=1"}, "body": {"access_token": "t", "ok": True}},
    }
    out = redact_record(record)
    assert REDACTED in out["url"]
    assert out["request"]["headers"]["Authorization"] == REDACTED
    assert out["request"]["body"]["password"] == REDACTED
    assert out["response"]["headers"]["Set-Cookie"] == REDACTED
    assert out["response"]["body"]["access_token"] == REDACTED
    assert out["response"]["body"]["ok"] is True


def test_form_encoded_oauth_secrets_are_redacted():
    body = "grant_type=refresh_token&client_id=android&client_secret=s3cr3t&refresh_token=r3fr3sh&code=auth123"
    out = redact_text(body)
    assert "s3cr3t" not in out
    assert "r3fr3sh" not in out
    assert "auth123" not in out
    assert "client_id=android" in out          # non-secret preserved
    assert "grant_type=refresh_token" in out    # value word preserved, only the param is wiped


def test_form_redaction_ignores_lookalike_params():
    assert redact_text("postalcode=12345") == "postalcode=12345"
    assert redact_text("a=1&qrcode=ABCDEF") == "a=1&qrcode=ABCDEF"


def test_redact_dir_writes_redacted_files(tmp_path):
    src = tmp_path / "raw"
    src.mkdir()
    dst = tmp_path / "fixtures"
    (src / "0001_POST_login.json").write_text(
        json.dumps({
            "method": "POST", "url": "https://api.alf.se/login", "host": "api.alf.se",
            "path": "/login", "status": 200,
            "request": {"headers": {"Authorization": "Bearer eyJa.bbbbbb.cccc"}, "body": {}},
            "response": {"headers": {}, "body": {"access_token": "secret", "ok": True}},
        }),
        encoding="utf-8",
    )
    assert redact_dir(src, dst) == 1
    out = json.loads((dst / "0001_POST_login.json").read_text(encoding="utf-8"))
    assert out["request"]["headers"]["Authorization"] == REDACTED
    assert out["response"]["body"]["access_token"] == REDACTED
    assert out["response"]["body"]["ok"] is True
