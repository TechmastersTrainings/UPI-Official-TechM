import pytest

from app.core import validators as v


@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "9876543210"), ("+91 98765 43210", "9876543210"), ("919876543210", "9876543210"),
    ("09876543210", "9876543210"),
])
def test_mobile_ok(raw, expected):
    assert v.normalize_mobile(raw) == expected


@pytest.mark.parametrize("raw", ["12345", "5876543210", "98765432101"])
def test_mobile_bad(raw):
    with pytest.raises(ValueError):
        v.normalize_mobile(raw)


def test_ifsc_pan_gstin_pin_vpa():
    assert v.normalize_ifsc(" sbin0001234 ") == "SBIN0001234"
    assert v.normalize_pan("abcde1234f") == "ABCDE1234F"
    assert v.normalize_gstin("29abcde1234f1z5") == "29ABCDE1234F1Z5"
    assert v.normalize_pin("560001") == "560001"
    assert v.normalize_vpa("Shop.Name@okhdfcbank") == "shop.name@okhdfcbank"
    for fn, bad in [(v.normalize_ifsc, "SBIN1234567"), (v.normalize_pan, "ABCD1234F"), (v.normalize_pin, "060001"),
                    (v.normalize_vpa, "shop@"), (v.normalize_account_number, "12345678")]:
        with pytest.raises(ValueError):
            fn(bad)


@pytest.mark.parametrize("url,env,dev,ok", [
    ("https://shop.example.com/hook", "LIVE", False, True),
    ("http://shop.example.com/hook", "LIVE", True, False),
    ("https://localhost/hook", "LIVE", True, False),
    ("https://192.168.1.10/hook", "LIVE", False, False),
    ("https://[::1]/hook", "TEST", False, False),
    ("http://localhost:9000/hook", "TEST", True, True),
    ("http://localhost:9000/hook", "TEST", False, False),
    ("http://shop.example.com/hook", "TEST", True, False),
    ("https://user:pw@shop.example.com/hook", "LIVE", False, False),
    ("ftp://shop.example.com", "LIVE", False, False),
])
def test_webhook_url_rules(url, env, dev, ok):
    if ok:
        assert v.validate_webhook_url(url, environment=env, allow_insecure_local=dev) == url
    else:
        with pytest.raises(ValueError):
            v.validate_webhook_url(url, environment=env, allow_insecure_local=dev)
