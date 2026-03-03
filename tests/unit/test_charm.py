from unittest.mock import MagicMock

import pytest
from charmlibs import snap
from ops import testing

import debarchive
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


def test_start_no_version(monkeypatch: pytest.MonkeyPatch):
    """Test that the start hook handles a missing version gracefully."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    monkeypatch.setattr("charm.debarchive.start", MagicMock())
    monkeypatch.setattr("charm.debarchive.get_version", lambda: None)

    state_in = testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)

    assert state_out.workload_version == ""

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


def test_config_changed_success_covers_ports(monkeypatch: pytest.MonkeyPatch):
    """Test the 'happy path' where the snap is present and ports need closing."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    mock_snap = MagicMock()
    mock_snap.present = True

    mock_cache = MagicMock()
    mock_cache.__getitem__.return_value = mock_snap
    monkeypatch.setattr("charm.snap.SnapCache", lambda: mock_cache)

    state_in = testing.State(config={"server-port": 8080}, opened_ports=[testing.TCPPort(8000)])

    state_out = ctx.run(ctx.on.config_changed(), state_in)

    mock_snap.set.assert_called_once_with({"deb.archive.server.port": "8080"})
    mock_snap.restart.assert_called_once()

    opened_ports = {p.port for p in state_out.opened_ports}
    assert 8080 in opened_ports
    assert 8000 not in opened_ports


def test_config_changed_snap_error_during_restart(monkeypatch: pytest.MonkeyPatch):
    """Test simulating a failure while modifying the snap."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    mock_snap = MagicMock()
    mock_snap.present = True

    mock_snap.restart.side_effect = snap.SnapError("Simulated snap failure")

    mock_cache = MagicMock()
    mock_cache.__getitem__.return_value = mock_snap
    monkeypatch.setattr("charm.snap.SnapCache", lambda: mock_cache)

    state_in = testing.State(config={"server-port": 8080})
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    assert state_out.unit_status == testing.BlockedStatus("Failed to apply configuration")


def test_config_changed_snap_not_present(monkeypatch: pytest.MonkeyPatch):
    """Test the 'False' branch of the `if my_snap.present` statement."""
    ctx = testing.Context(DebarchiveOperatorCharm)

    mock_snap = MagicMock()
    mock_snap.present = False

    mock_cache = MagicMock()
    mock_cache.__getitem__.return_value = mock_snap
    monkeypatch.setattr("charm.snap.SnapCache", lambda: mock_cache)

    state_in = testing.State(config={"server-port": 8080})
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    mock_snap.set.assert_not_called()
    mock_snap.restart.assert_not_called()
    assert state_out.unit_status == testing.ActiveStatus()


def test_install_snap_packages_installs_and_configures_debarchive(monkeypatch: pytest.MonkeyPatch):
    """Test that snaps are correctly ensured and debarchive-specific settings are applied."""
    fake_snaps = [
        ("core24", {"channel": "stable"}),
        ("landscape-debarchive", {"channel": "latest/stable"}),
    ]
    monkeypatch.setattr(debarchive, "SNAPS_TO_INSTALL", fake_snaps)

    class MockSnap:
        def __init__(self):
            self.present = False
            self.ensured = False
            self.set_called = {}
            self.restarted = False

        def ensure(self, state, channel=None):
            self.ensured = True

        def set(self, config):
            self.set_called = config

        def restart(self):
            self.restarted = True

    mock_snap_inst = MockSnap()

    class MockCache:
        def __getitem__(self, name):
            return mock_snap_inst

    monkeypatch.setattr(snap, "SnapCache", MockCache)
    monkeypatch.setattr(debarchive, "logger", MagicMock())
    debarchive.install()

    assert mock_snap_inst.ensured is True
    assert mock_snap_inst.restarted is True
    assert mock_snap_inst.set_called["deb.archive.server.host"] == "0.0.0.0"


def test_install_snap_packages_skips(monkeypatch: pytest.MonkeyPatch):
    """Test that snaps are not re-installed or misconfigured when conditions are not met."""
    fake_snaps = [
        ("core24", {"channel": "stable"}),
        ("other", {}),
        ("not-landscape", {"channel": "s"}),
    ]
    monkeypatch.setattr(debarchive, "SNAPS_TO_INSTALL", fake_snaps)

    class FakeSnap:
        def __init__(self, name):
            self.name = name
            self.present = name == "core24"
            self.ensure_called = False
            self.set_called = False

        def ensure(self, state, channel=None):
            self.ensure_called = True

        def set(self, config):
            self.set_called = True

        def restart(self):
            pass

    class FakeCache:
        def __init__(self):
            self.instances = {}

        def __getitem__(self, name):
            if name not in self.instances:
                self.instances[name] = FakeSnap(name)
            return self.instances[name]

    shared_cache = FakeCache()
    monkeypatch.setattr(snap, "SnapCache", lambda: shared_cache)

    debarchive.install()

    assert shared_cache["core24"].ensure_called is False
    assert shared_cache["other"].ensure_called is False
    assert shared_cache["not-landscape"].set_called is False


def test_install_snap_packages_error_path(monkeypatch: pytest.MonkeyPatch):
    """Test the error handling logic when snap installation fails."""
    monkeypatch.setattr(debarchive, "SNAPS_TO_INSTALL", [("any", {})])

    def fail_init(*args, **kwargs):
        raise snap.SnapError("Simulated Failure")

    monkeypatch.setattr(snap, "SnapCache", fail_init)

    class MockLog:
        def error(self, msg, *args):
            pass

    monkeypatch.setattr(debarchive, "logger", MockLog())

    with pytest.raises(snap.SnapError):
        debarchive.install()


def test_get_version_debarchive():
    """Test that debarchive `get_version` returns expected value."""
    version = debarchive.get_version()

    assert version is None
    assert isinstance(version, (str, type(None)))
