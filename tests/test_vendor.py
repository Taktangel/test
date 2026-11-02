from vendor import edgar13f as e13
from vendor import ptr


def test_vendor_modules_load():
    filers = e13.load_filers()
    assert len(filers) == 23
    assert filers[0]["cik"] == "0001067983"
    assert ptr.iso("8/21/2026") == "2026-08-21"


def test_share_class_overrides_load():
    overrides = e13.load_overrides([e13.CLASSES])
    assert overrides["02079K305"] == "GOOGL"
