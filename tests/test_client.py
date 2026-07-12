import pytest

from alfcloud.auth import AlfAuth
from alfcloud.client import AlfClient
from alfcloud.errors import AlfApiError


def _token(fake, make_jwt, refresh="rt"):
    return fake.Response(payload={"access_token": make_jwt(), "refresh_token": refresh,
                                  "expires_in": 3600})


async def test_get_homes_parses_rooms(fake, make_jwt):
    session = fake.Session([
        _token(fake, make_jwt),
        fake.Response(payload=[{"id": "h1", "name": "Home", "rooms": [{"id": "r1", "name": "Kök"}]}]),
    ])
    client = AlfClient(AlfAuth("rt", "secret", session), session)
    homes = await client.async_get_homes()
    assert [h.id for h in homes] == ["h1"]
    assert homes[0].room_name("r1") == "Kök"


async def test_get_devices_sends_bearer_and_parses(fake, make_jwt):
    session = fake.Session([
        _token(fake, make_jwt),
        fake.Response(payload={"homeId": "h1", "devices": [
            {"id": "d1", "name": "P", "type": "frient.smartplug", "state": "online", "homeId": "h1",
             "features": [{"id": "smartplug.onOff", "deviceFeatureId": "d1:smartplug.onOff",
                           "current": {"value": True}}]}]}),
    ])
    client = AlfClient(AlfAuth("rt", "secret", session), session)
    devices = await client.async_get_devices("h1")
    assert devices[0].value("smartplug.onOff") is True
    get_call = next(c for c in session.calls if c["method"] == "GET")
    assert get_call["headers"]["Authorization"].startswith("Bearer ")
    assert get_call["url"].endswith("/api/v1/home/h1/device")


async def test_set_feature_posts_value_to_action_path(fake, make_jwt):
    session = fake.Session([
        _token(fake, make_jwt),
        fake.Response(status=201, payload={"deviceFeatureId": "d1:smartplug.onOff",
                                           "current": {"value": True}, "desired": {"value": False}}),
    ])
    client = AlfClient(AlfAuth("rt", "secret", session), session)
    result = await client.async_set_feature("h1", "d1:smartplug.onOff", False)
    assert result["deviceFeatureId"] == "d1:smartplug.onOff"
    action = [c for c in session.calls if c["method"] == "POST"][-1]
    assert action["url"].endswith("/home/h1/device/action/d1:smartplug.onOff")
    assert action["json"] == {"value": False}


async def test_401_triggers_refresh_then_retry(fake, make_jwt):
    session = fake.Session([
        _token(fake, make_jwt),                                    # initial refresh
        fake.Response(status=401),                                 # GET -> 401
        _token(fake, make_jwt),                                    # forced refresh
        fake.Response(payload={"homeId": "h1", "devices": []}),    # retry GET -> 200
    ])
    client = AlfClient(AlfAuth("rt", "secret", session), session)
    assert await client.async_get_devices("h1") == []


async def test_server_error_raises_api_error(fake, make_jwt):
    session = fake.Session([_token(fake, make_jwt), fake.Response(status=500)])
    client = AlfClient(AlfAuth("rt", "secret", session), session)
    with pytest.raises(AlfApiError):
        await client.async_get_devices("h1")
