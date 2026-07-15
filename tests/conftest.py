"""Shared fixtures for the SmartHomeSec test suite."""

import pytest
import pytest_socket

# The HA test plugin disables sockets per-test (plugins.pytest_runtest_setup ->
# pytest_socket.disable_socket). Creating Home Assistant's event loop needs a
# real socket at construction time -- notably the ProactorEventLoop self-pipe on
# Windows, which is AF_INET and so not covered by the plugin's allow_unix_socket
# exception. All real network I/O in these tests is mocked, so we neutralize the
# socket block by turning disable_socket into a no-op before any test runs.
pytest_socket.disable_socket = lambda *args, **kwargs: None

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom integration in every test."""
    yield
