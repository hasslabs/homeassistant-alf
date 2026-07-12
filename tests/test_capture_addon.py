# tests/test_capture_addon.py
from recon.capture_addon import build_record, is_target_host, parse_body


def test_is_target_host_matches_known_suffixes():
    assert is_target_host("api.alf.se")
    assert is_target_host("cloud.onics.io")
    assert is_target_host("gw.develco.com")
    assert is_target_host("lfhub.net")
    assert is_target_host("auth.lfhub.net")


def test_is_target_host_rejects_unrelated():
    assert not is_target_host("www.google.com")
    assert not is_target_host("telemetry.microsoft.com")


def test_parse_body_json():
    assert parse_body("application/json", b'{"a": 1}') == {"a": 1}


def test_parse_body_falls_back_to_text():
    assert parse_body("text/plain", b"hello") == "hello"


def test_parse_body_handles_empty():
    assert parse_body(None, None) is None
    assert parse_body("application/json", b"") is None


def test_build_record_shape():
    record = build_record(
        method="POST", url="https://api.alf.se/login", host="api.alf.se", path="/login",
        status=200, req_headers={"A": "b"}, req_body={"x": 1},
        resp_headers={"C": "d"}, resp_body={"ok": True},
    )
    assert record["method"] == "POST"
    assert record["host"] == "api.alf.se"
    assert record["path"] == "/login"
    assert record["status"] == 200
    assert record["request"] == {"headers": {"A": "b"}, "body": {"x": 1}}
    assert record["response"] == {"headers": {"C": "d"}, "body": {"ok": True}}
