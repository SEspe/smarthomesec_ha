"""token_info() is used in debug logs: it must never contain the token itself."""

from custom_components.smarthomesec import SmarthomesecCoordinator


def _coordinator() -> SmarthomesecCoordinator:
    return object.__new__(SmarthomesecCoordinator)


def test_no_token_is_reported_as_none():
    coord = _coordinator()
    coord.token = None
    assert coord.token_info() == "token=none"


def test_fingerprint_and_age_without_the_token_value():
    coord = _coordinator()
    secret = "eyJhbGciOiJIUzI1NiJ9.secret-part.signature"
    coord.token = secret
    coord._token_issued = 0.0  # age is measured from here; any value works

    info = coord.token_info()

    assert info.startswith("token_fp=")
    assert " age=" in info
    assert secret not in info
    assert "secret-part" not in info


def test_fingerprint_is_stable_for_the_same_token_and_differs_between_tokens():
    coord = _coordinator()
    coord.token = "token-one"
    first = coord.token_info().split()[0]
    assert coord.token_info().split()[0] == first

    coord.token = "token-two"
    assert coord.token_info().split()[0] != first


def test_age_is_unknown_before_a_login_has_been_recorded():
    coord = _coordinator()
    coord.token = "abc"
    assert "age=?" in coord.token_info()
