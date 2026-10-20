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


def _flow(host, path, method="GET", status=200, req_ct=None, req_body=b"",
          resp_ct="application/json", resp_body=b'{"ok": true}'):
    from types import SimpleNamespace

    class Msg(SimpleNamespace):
        def get_content(self, strict=False):
            return self.content

    request = Msg(pretty_host=host, pretty_url=f"https://{host}{path}", path=path,
                  method=method, headers={"content-type": req_ct} if req_ct else {},
                  content=req_body)
    response = Msg(status_code=status, headers={"content-type": resp_ct}, content=resp_body)
    return SimpleNamespace(request=request, response=response)


def test_addon_writes_only_target_hosts_with_safe_numbered_names(tmp_path, monkeypatch):
    import json

    from recon import capture_addon

    monkeypatch.setattr(capture_addon, "RAW_DIR", tmp_path / "raw")
    addon = capture_addon.AlfCaptureAddon()
    addon.response(_flow("www.google.com", "/ignored"))
    addon.response(_flow("lfhub.net", "/api/v1/home/abc/device?x=1"))
    addon.response(_flow("auth.lfhub.net", "/token", method="POST",
                         req_ct="application/x-www-form-urlencoded", req_body=b"a=b",
                         resp_ct="text/html", resp_body=b"<p>hi</p>"))

    files = sorted(p.name for p in (tmp_path / "raw").iterdir())
    assert files == ["0001_GET__api_v1_home_abc_device.json", "0002_POST__token.json"]
    first = json.loads((tmp_path / "raw" / files[0]).read_text(encoding="utf-8"))
    assert first["path"] == "/api/v1/home/abc/device"  # query string stripped
    assert first["url"].endswith("?x=1")
    assert first["response"]["body"] == {"ok": True}
    assert first["request"]["body"] is None
    second = json.loads((tmp_path / "raw" / files[1]).read_text(encoding="utf-8"))
    assert second["request"]["body"] == "a=b"
    assert second["response"]["body"] == "<p>hi</p>"


def test_parse_body_invalid_json_falls_back_to_text():
    assert parse_body("application/json; charset=utf-8", b"{broken") == "{broken"
    assert parse_body("APPLICATION/JSON", b"[1]") == [1]
