from unittest.mock import MagicMock

import pytest
from charmlibs import snap
from ops import testing

from charm import DebarchiveOperatorCharm


def test_install(monkeypatch: pytest.MonkeyPatch):
    """Test that the install hook properly installs and configures the snap."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    mock_snap = MagicMock()
    mock_snap.present = False

    mock_cache = MagicMock()
    mock_cache.__getitem__.return_value = mock_snap

    monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

    state_in = testing.State()
    _ = ctx.run(ctx.on.install(), state_in)

    mock_snap.ensure.assert_called_once_with(snap.SnapState.Latest, channel="edge")
    mock_snap.set.assert_called_once_with({"deb.archive.server.host": "0.0.0.0"})
    mock_snap.restart.assert_called_once()


def test_start(monkeypatch: pytest.MonkeyPatch):
    """Test that the start hook opens the default port and sets the version/status."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    monkeypatch.setattr("charm.debarchive.start", MagicMock())
    monkeypatch.setattr("charm.debarchive.get_version", lambda: "1.0.0")

    state_in = testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)

    assert state_out.workload_version == "1.0.0"
    assert state_out.unit_status == testing.ActiveStatus()
    opened_ports = {p.port for p in state_out.opened_ports}
    assert 8000 in opened_ports


def test_config_changed_success(monkeypatch: pytest.MonkeyPatch):
    """Test that changing the port config updates the snap and firewall correctly."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    mock_snap = MagicMock()
    mock_snap.present = True

    mock_cache = MagicMock()
    mock_cache.__getitem__.return_value = mock_snap
    monkeypatch.setattr("charm.snap.SnapCache", lambda: mock_cache)

    port_8000 = testing.TCPPort(protocol="tcp", port=8000)
    state_in = testing.State(config={"server-port": 8080}, opened_ports=[port_8000])

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    mock_snap.set.assert_called_once_with({"deb.archive.server.port": "8080"})
    mock_snap.restart.assert_called_once()

    opened_ports = {p.port for p in state_out.opened_ports}
    assert 8080 in opened_ports
    assert 8000 not in opened_ports

    assert state_out.unit_status == testing.ActiveStatus()


def test_config_changed_snap_error(monkeypatch: pytest.MonkeyPatch):
    """Test that a SnapError during config-changed puts the unit into BlockedStatus."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    mock_cache = MagicMock()
    mock_cache.__getitem__.side_effect = snap.SnapError("Mock failure")
    monkeypatch.setattr("charm.snap.SnapCache", lambda: mock_cache)

    state_in = testing.State(config={"server-port": 8080})
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert state_out.unit_status == testing.BlockedStatus("Failed to apply configuration")
