import pytest

from alfcloud.features import BINARY_KINDS, SENSOR_KINDS, SWITCH_KINDS, classify_feature


@pytest.mark.parametrize(
    ("feature_id", "kind"),
    [
        ("smokeDetector.fire", "smoke"),
        ("generic.temperature", "temperature"),
        ("smartplug.onOff", "onoff"),
        ("smartplug.demand", "power"),
        ("smartplug.summationDelivered", "energy"),
        ("waterLeakDetector.flood", "moisture"),
        ("leakbot.leak", "moisture"),
        # The 'leakbot' prefix must NOT make every feature a leak:
        ("leakbot.highFlow", "unknown"),
        ("leakbot.hotPipe", "unknown"),
        ("leakbot.onPipe", "unknown"),
        ("leakbot.hardwareProblem", "problem"),
        ("magnet.contact", "opening"),
        ("generic.humidity", "humidity"),
        ("device.tamper", "tamper"),
        ("gateway.mode", "unknown"),
    ],
)
def test_classify_feature(feature_id, kind):
    assert classify_feature(feature_id) == kind


def test_kind_sets_are_disjoint():
    assert BINARY_KINDS.isdisjoint(SENSOR_KINDS)
    assert BINARY_KINDS.isdisjoint(SWITCH_KINDS)
    assert SENSOR_KINDS.isdisjoint(SWITCH_KINDS)
