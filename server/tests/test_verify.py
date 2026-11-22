import pytest

from server.signals import BLOCK, STEP_UP
from server.verify import (DecodeError, GoogleDecoder, InvalidTransfer, MockDecoder, Transfer, assess_integrity,
                           check_payload, mint_mock_token, mock_payload)

NOW_MS = 1_800_000_000_000
PKG = "com.demo.wallet"


def tx(**kw):
    d = {"account": "acc-001", "payeeId": "ana", "amountCents": 20000, "currency": "EUR",
         "nonce": "00ff", "actor": "assistant"}
    d.update(kw)
    return Transfer.from_json(d)


def codes(signals):
    return {s.code for s in signals}


def test_canonical_matches_app_test_vector():
    t = tx()
    assert t.canonical() == "v1|acc-001|ana|20000|EUR|00ff|assistant"
    assert t.request_hash() == "e71ee40ea59a74ba0232bcfbe5fa606d85704fb673068c4cfbc81e32a8b71ca8"


@pytest.mark.parametrize("bad", [
    {"amountCents": 0}, {"amountCents": -5}, {"amountCents": "200"}, {"amountCents": True},
    {"payeeId": "a|b"}, {"actor": "robot"}, {"nonce": ""},
])
def test_rejects_malformed_transfers(bad):
    with pytest.raises(InvalidTransfer):
        tx(**bad)


def test_missing_field_named():
    with pytest.raises(InvalidTransfer, match="nonce"):
        Transfer.from_json({"account": "acc-001", "payeeId": "ana", "amountCents": 1, "actor": "user"})


def check(profile, hash_=None, **kw):
    t = tx()
    p = mock_payload(profile, hash_ or t.request_hash(), kw.pop("package", PKG), kw.pop("ts", NOW_MS))
    return check_payload(p, t.request_hash(), PKG, 300, NOW_MS)


def test_device_ok_verdict_passes():
    assert codes(check("device_ok")) == {"verified", "testing_response"}


@pytest.mark.lab2
def test_hash_bound_to_other_transfer_is_blocked():
    other = tx(amountCents=99900).request_hash()
    [s] = check("device_ok", hash_=other)
    assert (s.code, s.floor) == ("hash_mismatch", BLOCK)


@pytest.mark.lab2
def test_token_for_other_package_is_blocked():
    [s] = check("device_ok", package="com.evil.app")
    assert (s.code, s.floor) == ("package_mismatch", BLOCK)


@pytest.mark.lab2
def test_stale_and_future_verdicts_step_up():
    assert "stale" in codes(check("device_ok", ts=NOW_MS - 301_000))
    assert "stale" in codes(check("device_ok", ts=NOW_MS + 120_000))
    assert "stale" not in codes(check("device_ok", ts=NOW_MS - 299_000))


def test_emulator_profile_is_what_attendees_get():
    s = check("emulator")
    assert {"device_none", "app_unrecognized", "unlicensed"} <= codes(s)
    assert any(x.floor == STEP_UP for x in s)


def test_basic_integrity_is_scored_not_floored():
    [s] = [x for x in check("basic") if x.code == "device_basic"]
    assert s.points == 20 and s.floor is None


def test_unknown_controlling_app_steps_up():
    [s] = [x for x in check("controlled") if x.code == "unknown_controlling"]
    assert s.floor == STEP_UP


def test_unevaluated_payload_fails_closed():
    t = tx()
    p = {"requestDetails": {"requestPackageName": PKG, "requestHash": t.request_hash(), "timestampMillis": NOW_MS}}
    assert {"app_unrecognized", "device_none"} <= codes(check_payload(p, t.request_hash(), PKG, 300, NOW_MS))


def assess(integrity, client_hash=None, mode="mock", profile="emulator", required=True, decoder=None):
    return assess_integrity(integrity, tx(), client_hash, decoder or MockDecoder(), mode=mode, mock_profile=profile,
                            package_name=PKG, max_age_s=300, required=required, now_ms=NOW_MS)


def test_absent_integrity_steps_up_unless_not_required():
    [s] = assess(None)
    assert (s.code, s.floor) == ("missing", STEP_UP)
    [s] = assess(None, required=False)
    assert s.code == "not_sent" and s.points == 0


def test_error_without_token_steps_up_in_none_profile_and_google_mode():
    [s] = assess({"token": None, "error": "NOT_CONFIGURED"}, profile="none")
    assert s.code == "missing" and "NOT_CONFIGURED" in s.detail
    [s] = assess({"token": None, "error": "REQUEST:StandardIntegrityException:-2: x"}, mode="google",
                 decoder=GoogleDecoder(PKG, session=object()))
    assert s.code == "missing" and "REQUEST" in s.detail


@pytest.mark.lab2
def test_mock_mode_simulates_a_verdict_bound_to_the_client_hash():
    assert "verified" in codes(assess({"token": None, "error": "NOT_CONFIGURED"}, client_hash=tx().request_hash(),
                                      profile="device_ok"))
    # body changed after the device hashed it → the simulated token no longer matches
    tampered = assess({"token": None, "error": "NOT_CONFIGURED"}, client_hash="ab" * 32, profile="device_ok")
    assert [s.code for s in tampered] == ["hash_mismatch"]


def test_mock_mode_needs_a_client_hash_to_simulate():
    for bad in (None, "", "xyz", "AB" * 32):
        [s] = assess({"token": None, "error": "NOT_CONFIGURED"}, client_hash=bad, profile="device_ok")
        assert (s.code, s.floor) == ("missing", STEP_UP)


@pytest.mark.lab2
def test_explicit_mock_token_is_decoded_and_checked():
    t = tx()
    good = mint_mock_token(mock_payload("device_ok", t.request_hash(), PKG, NOW_MS))
    assert "verified" in codes(assess({"token": good, "error": None}))
    lifted = mint_mock_token(mock_payload("device_ok", tx(amountCents=1).request_hash(), PKG, NOW_MS))
    assert [s.code for s in assess({"token": lifted, "error": None})] == ["hash_mismatch"]


def test_garbage_token_steps_up():
    [s] = assess({"token": "eyJhbGciOi.not-a-mock", "error": None})
    assert (s.code, s.floor) == ("token_invalid", STEP_UP)
    with pytest.raises(DecodeError):
        MockDecoder().decode("mock.!!!")


class FakeResponse:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        return self.response


def test_google_decoder_calls_decode_endpoint():
    payload = {"requestDetails": {"requestPackageName": PKG}}
    s = FakeSession(FakeResponse(200, {"tokenPayloadExternal": payload}))
    assert GoogleDecoder(PKG, session=s).decode("REAL.TOKEN") == payload
    assert s.calls == [("https://playintegrity.googleapis.com/v1/com.demo.wallet:decodeIntegrityToken",
                        {"integrityToken": "REAL.TOKEN"})]


@pytest.mark.parametrize("token,response", [
    ("mock.e30", FakeResponse(200, {})),                  # mock token refused in google mode
    ("REAL", FakeResponse(400, {"error": "bad token"})),  # Google rejects
    ("REAL", FakeResponse(200, {"nothing": 1})),          # unexpected shape
])
def test_google_decoder_failures(token, response):
    with pytest.raises(DecodeError):
        GoogleDecoder(PKG, session=FakeSession(response)).decode(token)
