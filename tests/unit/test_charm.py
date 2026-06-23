from unittest.mock import MagicMock

import pytest
from charmlibs import snap
from ops import testing
from ops.model import ModelError

import debarchive
from charm import DebarchiveOperatorCharm


class TestCharmInstallAndStartup:
    def test_install(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the install hook properly installs and configures the snap."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_snap.present = False

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap

        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)
        monkeypatch.setattr(
            debarchive,
            "SNAPS_TO_INSTALL",
            [(debarchive.DEBARCHIVE_SNAP_NAME, {"channel": "edge", "revision": "258"})],
        )

        state_in = testing.State()
        _ = ctx.run(ctx.on.install(), state_in)

        mock_snap.ensure.assert_called_once_with(
            snap.SnapState.Latest, channel="edge", revision="258"
        )
        # The snap is pinned to a specific revision, so it is held after install.
        mock_snap.hold.assert_called_once_with()

        # install() sets a generated pagination secret. The host is refreshed
        # when haproxy route requirements are provided.
        pagination_call = next(
            call.args[0]
            for call in mock_snap.set.call_args_list
            if "deb.archive.pagination.secret" in call.args[0]
        )
        assert list(pagination_call) == ["deb.archive.pagination.secret"]
        assert pagination_call["deb.archive.pagination.secret"]
        assert mock_snap.set.call_count == 1
        mock_snap.restart.assert_not_called()

    def test_start(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the start hook opens the default port and sets the version/status."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr("charm.debarchive.start", MagicMock())
        monkeypatch.setattr("charm.debarchive.get_version", lambda: "1.0.0")

        state_in = testing.State()
        state_out = ctx.run(ctx.on.start(), state_in)

        assert state_out.workload_version == "1.0.0"
        assert state_out.unit_status == testing.ActiveStatus()

        assert not state_out.opened_ports

    def test_start_no_version(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the start hook handles a missing version gracefully."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr("charm.debarchive.start", MagicMock())
        monkeypatch.setattr("charm.debarchive.get_version", lambda: None)

        state_in = testing.State()
        state_out = ctx.run(ctx.on.start(), state_in)

        assert state_out.workload_version == ""

        assert state_out.unit_status == testing.ActiveStatus()

        assert not state_out.opened_ports


class TestCharmUpgrade:
    def test_upgrade_charm_refreshes_snap(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the upgrade-charm hook refreshes the snap and updates the version."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        refresh = MagicMock()
        monkeypatch.setattr("charm.debarchive.refresh", refresh)
        monkeypatch.setattr("charm.debarchive.get_version", lambda: "256")

        state_in = testing.State()
        state_out = ctx.run(ctx.on.upgrade_charm(), state_in)

        refresh.assert_called_once_with()
        assert state_out.workload_version == "256"
        assert state_out.unit_status == testing.ActiveStatus()

    def test_upgrade_charm_no_version(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the upgrade-charm hook handles a missing version gracefully."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr("charm.debarchive.refresh", MagicMock())
        monkeypatch.setattr("charm.debarchive.get_version", lambda: None)

        state_in = testing.State()
        state_out = ctx.run(ctx.on.upgrade_charm(), state_in)

        assert state_out.workload_version == ""
        assert state_out.unit_status == testing.ActiveStatus()

    def test_upgrade_charm_snap_error_blocks(self, monkeypatch: pytest.MonkeyPatch):
        """Test that a SnapError during upgrade-charm puts the unit into BlockedStatus."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr(
            "charm.debarchive.refresh",
            MagicMock(side_effect=snap.SnapError("Simulated failure")),
        )

        state_in = testing.State()
        state_out = ctx.run(ctx.on.upgrade_charm(), state_in)

        assert state_out.unit_status == testing.BlockedStatus("Failed to refresh debarchive snap")


class TestCharmConfigChanged:
    def test_config_changed_success(self, monkeypatch: pytest.MonkeyPatch):
        """Test that changing config updates the debarchive snap settings."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_snap.present = True

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        port_8000 = testing.TCPPort(protocol="tcp", port=8000)
        state_in = testing.State(
            config={
                "gateway-port": 8080,
                "log-level": "debug",
                "log-human-readable": True,
            },
            opened_ports=[port_8000],
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        mock_snap.set.assert_called_once_with(
            {
                "deb.archive.server.gateway-port": "8080",
                "deb.archive.logging.level": "debug",
                "deb.archive.logging.human-readable": "true",
            }
        )
        mock_snap.restart.assert_not_called()

        opened_ports = {p.port for p in state_out.opened_ports}
        assert opened_ports == {8000}

        assert state_out.unit_status == testing.ActiveStatus()

    def test_config_changed_snap_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test that a SnapError during config-changed puts the unit into BlockedStatus."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_cache = MagicMock()
        mock_cache.__getitem__.side_effect = snap.SnapError("Mock failure")
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        state_in = testing.State(
            config={"gateway-port": 8080, "log-level": "info", "log-human-readable": False}
        )
        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.BlockedStatus("Failed to apply configuration")

    def test_config_changed_normalizes_log_level(self, monkeypatch: pytest.MonkeyPatch):
        """Test that supported log levels are normalized before being applied."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_snap.present = True

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        state_in = testing.State(
            config={"gateway-port": 8101, "log-level": "TRACE", "log-human-readable": False},
            opened_ports=[testing.TCPPort(8000)],
        )

        state_out = ctx.run(ctx.on.config_changed(), state_in)

        mock_snap.set.assert_called_once_with(
            {
                "deb.archive.server.gateway-port": "8101",
                "deb.archive.logging.level": "trace",
                "deb.archive.logging.human-readable": "false",
            }
        )
        mock_snap.restart.assert_not_called()

        opened_ports = {p.port for p in state_out.opened_ports}
        assert opened_ports == {8000}

    def test_config_changed_snap_error_during_set(self, monkeypatch: pytest.MonkeyPatch):
        """Test simulating a failure while modifying the snap."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_snap.present = True

        mock_snap.set.side_effect = snap.SnapError("Simulated snap failure")

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        state_in = testing.State(
            config={"gateway-port": 8080, "log-level": "warn", "log-human-readable": False}
        )
        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.BlockedStatus("Failed to apply configuration")

    def test_config_changed_invalid_log_level(self):
        """Test that unsupported log levels put the unit into BlockedStatus."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        state_in = testing.State(
            config={"gateway-port": 8080, "log-level": "verbose", "log-human-readable": False}
        )
        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.BlockedStatus(
            f"Invalid log-level; expected {', '.join(debarchive.LOG_LEVELS)}"
        )

    def test_config_changed_uses_value_error_message(self, monkeypatch: pytest.MonkeyPatch):
        """Test that config validation failures report their own error messages."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr(
            debarchive,
            "configure",
            MagicMock(side_effect=ValueError("gateway-port must be greater than zero")),
        )

        state_in = testing.State(
            config={"gateway-port": 0, "log-level": "info", "log-human-readable": False}
        )
        state_out = ctx.run(ctx.on.config_changed(), state_in)

        assert state_out.unit_status == testing.BlockedStatus(
            "gateway-port must be greater than zero"
        )

    def test_config_changed_snap_not_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test the 'False' branch of the `if my_snap.present` statement."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_snap.present = False

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        state_in = testing.State(
            config={"gateway-port": 8080, "log-level": "info", "log-human-readable": False}
        )
        state_out = ctx.run(ctx.on.config_changed(), state_in)

        mock_snap.set.assert_not_called()
        mock_snap.restart.assert_not_called()
        assert state_out.unit_status == testing.ActiveStatus()


class TestDebarchiveArchitecture:
    @pytest.mark.parametrize(
        ("machine", "expected"),
        [
            ("x86_64", "amd64"),
            ("amd64", "amd64"),
            ("AMD64", "amd64"),
            ("aarch64", "arm64"),
            ("arm64", "arm64"),
        ],
    )
    def test_get_architecture(self, monkeypatch: pytest.MonkeyPatch, machine: str, expected: str):
        """Test that supported machine names are normalized to snap architectures."""
        monkeypatch.setattr("debarchive.platform.machine", lambda: machine)

        assert debarchive.get_architecture() == expected

    def test_get_architecture_unsupported(self, monkeypatch: pytest.MonkeyPatch):
        """Test that an unsupported architecture raises a ValueError."""
        monkeypatch.setattr("debarchive.platform.machine", lambda: "riscv64")

        with pytest.raises(ValueError, match="Unsupported architecture: riscv64"):
            debarchive.get_architecture()

    @pytest.mark.parametrize(
        ("machine", "expected_revision"),
        [
            ("x86_64", "258"),
            ("aarch64", "259"),
        ],
    )
    def test_snaps_to_install_uses_architecture_revision(
        self, monkeypatch: pytest.MonkeyPatch, machine: str, expected_revision: str
    ):
        """Test that the snap revision is selected based on the architecture."""
        monkeypatch.setattr("debarchive.platform.machine", lambda: machine)

        assert debarchive._snaps_to_install() == [
            (
                debarchive.DEBARCHIVE_SNAP_NAME,
                {"channel": debarchive.DEBARCHIVE_SNAP_CHANNEL, "revision": expected_revision},
            )
        ]


class TestDebarchiveInstall:
    def test_install_snap_packages_installs_and_configures_debarchive(
        self, monkeypatch: pytest.MonkeyPatch
    ):
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

            def ensure(self, state, channel=None, revision=None):
                self.ensured = True

            def set(self, config):
                self.set_called.update(config)

        mock_snap_inst = MockSnap()

        class MockCache:
            def __getitem__(self, name):
                return mock_snap_inst

        monkeypatch.setattr(snap, "SnapCache", MockCache)
        monkeypatch.setattr(debarchive, "logger", MagicMock())
        debarchive.install()

        assert mock_snap_inst.ensured is True
        assert mock_snap_inst.set_called["deb.archive.pagination.secret"]

    def test_install_snap_packages_skips(self, monkeypatch: pytest.MonkeyPatch):
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

            def ensure(self, state, channel=None, revision=None):
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

    def test_install_snap_packages_error_path(self, monkeypatch: pytest.MonkeyPatch):
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


class TestDebarchiveRefresh:
    def test_refresh_unholds_ensures_and_holds_pinned_snap(self, monkeypatch: pytest.MonkeyPatch):
        """Test that refresh unholds, refreshes to the pinned revision, then re-holds."""
        monkeypatch.setattr(
            debarchive,
            "SNAPS_TO_INSTALL",
            [("landscape-debarchive", {"channel": "beta", "revision": "256"})],
        )

        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.held = True

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.refresh()

        mock_snap.unhold.assert_called_once_with()
        mock_snap.ensure.assert_called_once_with(
            snap.SnapState.Latest, channel="beta", revision="256"
        )
        mock_snap.hold.assert_called_once_with()

    def test_refresh_skips_unhold_when_not_held(self, monkeypatch: pytest.MonkeyPatch):
        """Test that refresh does not unhold a snap that is not currently held."""
        monkeypatch.setattr(
            debarchive,
            "SNAPS_TO_INSTALL",
            [("landscape-debarchive", {"channel": "beta", "revision": "256"})],
        )

        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.held = False

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.refresh()

        mock_snap.unhold.assert_not_called()
        mock_snap.ensure.assert_called_once_with(
            snap.SnapState.Latest, channel="beta", revision="256"
        )
        mock_snap.hold.assert_called_once_with()

    def test_refresh_ensures_even_when_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test that refresh re-ensures a snap that is already installed."""
        monkeypatch.setattr(
            debarchive,
            "SNAPS_TO_INSTALL",
            [("landscape-debarchive", {"channel": "beta", "revision": "256"})],
        )

        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.held = False

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.refresh()

        mock_snap.ensure.assert_called_once()

    def test_refresh_error_path(self, monkeypatch: pytest.MonkeyPatch):
        """Test that refresh propagates snap errors."""
        monkeypatch.setattr(
            debarchive,
            "SNAPS_TO_INSTALL",
            [("landscape-debarchive", {"channel": "beta", "revision": "256"})],
        )

        mock_cache = MagicMock()
        mock_cache.__getitem__.side_effect = snap.SnapError("Simulated Failure")
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)
        monkeypatch.setattr(debarchive, "logger", MagicMock())

        with pytest.raises(snap.SnapError):
            debarchive.refresh()


class TestDebarchiveConfig:
    def test_get_version_debarchive_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test that `get_version` returns the snap revision as a string when installed."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.revision = 42

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        version = debarchive.get_version()

        assert version == "42"
        assert isinstance(version, str)

    def test_get_version_debarchive_not_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test that `get_version` returns None when the snap is not installed."""
        mock_snap = MagicMock()
        mock_snap.present = False

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        version = debarchive.get_version()

        assert version is None

    def test_get_version_debarchive_snap_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test that `get_version` returns None when snapd raises a SnapError."""
        mock_cache = MagicMock()
        mock_cache.__getitem__.side_effect = snap.SnapError("snapd unavailable")
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.get_version() is None

    def test_get_version_info(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_version_info returns snap version metadata."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.revision = 42
        mock_snap.version = "1.2.3"
        mock_snap.channel = "beta"

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.get_version_info() == {
            "installed": True,
            "revision": "42",
            "version": "1.2.3",
            "channel": "beta",
        }

    def test_get_config(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_config returns all typed snap config with secrets redacted."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.get.return_value = {
            "deb": {
                "archive": {
                    "server": {"gateway-port": 8100},
                    "database": {"user": "user", "password": "pass"},
                    "jwt": {"secret": "jwt-secret"},
                    "logging": {"level": "info", "human-readable": False},
                }
            }
        }

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.get_config() == {
            "deb": {
                "archive": {
                    "server": {"gateway-port": 8100},
                    "database": {"user": "user", "password": "<redacted>"},
                    "jwt": {"secret": "<redacted>"},
                    "logging": {"level": "info", "human-readable": False},
                }
            }
        }
        mock_snap.get.assert_called_once_with(None, typed=True)

    def test_get_config_snap_not_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_config returns no config when the snap is absent."""
        mock_snap = MagicMock()
        mock_snap.present = False
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.get_config() == {}
        mock_snap.get.assert_not_called()

    def test_check_health_healthy(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check_health reports healthy when the debarchive service is active."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.services = {
            "debarchive": {"active": True},
            "worker": {"active": False},
        }
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.check_health() == {
            "installed": True,
            "healthy": True,
            "message": "debarchive snap service is active",
        }

    def test_check_health_inactive_service(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check_health reports an inactive debarchive service."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.services = {
            "debarchive": {"active": False},
            "worker": {"active": True},
        }
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.check_health() == {
            "installed": True,
            "healthy": False,
            "message": "debarchive snap service is not active",
        }

    def test_check_health_snap_not_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check_health reports an absent snap."""
        mock_snap = MagicMock()
        mock_snap.present = False
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.check_health() == {
            "installed": False,
            "healthy": False,
            "message": "debarchive snap is not installed",
        }

    def test_check_health_no_services(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check_health reports when the debarchive service is absent."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.services = {"worker": {"active": True}}
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.check_health() == {
            "installed": True,
            "healthy": False,
            "message": "debarchive snap has no debarchive service",
        }

    def test_restart(self, monkeypatch: pytest.MonkeyPatch):
        """Test that restart restarts the debarchive snap."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.restart()

        mock_snap.restart.assert_called_once_with()

    def test_restart_snap_not_present(self, monkeypatch: pytest.MonkeyPatch):
        """Test that restart raises when the debarchive snap is absent."""
        mock_snap = MagicMock()
        mock_snap.present = False
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        with pytest.raises(snap.SnapNotFoundError):
            debarchive.restart()

    def test_configure_database(self, monkeypatch: pytest.MonkeyPatch):
        """Test that configure_database sets the correct snap keys."""
        mock_snap = MagicMock()
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.configure_database("10.0.0.1", "5432", "user", "pass", "debarchive", "disable")

        mock_snap.set.assert_called_once_with(
            {
                "deb.archive.database.host": "10.0.0.1",
                "deb.archive.database.port": "5432",
                "deb.archive.database.user": "user",
                "deb.archive.database.password": "pass",
                "deb.archive.database.name": "debarchive",
                "deb.archive.database.ssl": "disable",
                "deb.archive.database.driver": "pgx",
            }
        )
        mock_snap.restart.assert_not_called()

    def test_configure(self, monkeypatch: pytest.MonkeyPatch):
        """Test that configure sets the application snap keys."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.configure(8101, "ERROR", True)

        mock_snap.set.assert_called_once_with(
            {
                "deb.archive.server.gateway-port": "8101",
                "deb.archive.logging.level": "error",
                "deb.archive.logging.human-readable": "true",
            }
        )
        mock_snap.restart.assert_not_called()

    def test_configure_skips_unchanged_config(self, monkeypatch: pytest.MonkeyPatch):
        """Test that configure does not write snap keys that already match."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.get.side_effect = {
            "deb.archive.server.gateway-port": "8101",
            "deb.archive.logging.level": "error",
            "deb.archive.logging.human-readable": True,
        }.__getitem__
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.configure(8101, "ERROR", True)

        mock_snap.set.assert_not_called()
        mock_snap.restart.assert_not_called()

    def test_configure_sets_only_changed_config(self, monkeypatch: pytest.MonkeyPatch):
        """Test that configure only writes snap keys whose values changed."""
        mock_snap = MagicMock()
        mock_snap.present = True
        mock_snap.get.side_effect = {
            "deb.archive.server.gateway-port": "8101",
            "deb.archive.logging.level": "error",
            "deb.archive.logging.human-readable": False,
        }.__getitem__
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.configure(8101, "ERROR", True)

        mock_snap.set.assert_called_once_with({"deb.archive.logging.human-readable": "true"})
        mock_snap.restart.assert_not_called()

    def test_configure_rejects_invalid_log_level(self):
        """Test that configure rejects unsupported log levels."""
        with pytest.raises(ValueError, match="Invalid log-level"):
            debarchive.configure(8100, "verbose", False)

    def test_set_secret_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test that set_secret_token writes the JWT secret."""
        mock_snap = MagicMock()
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.set_secret_token({"secret-token": "jwt-secret"})

        mock_snap.set.assert_called_once_with({"deb.archive.jwt.secret": "and0LXNlY3JldA=="})
        mock_snap.restart.assert_not_called()

    def test_set_pagination_secret(self, monkeypatch: pytest.MonkeyPatch):
        """Test that set_pagination_secret writes the pagination secret."""
        mock_snap = MagicMock()
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.set_pagination_secret()

        mock_snap.set.assert_called_once()
        (config,) = mock_snap.set.call_args.args
        assert list(config.keys()) == ["deb.archive.pagination.secret"]
        assert config["deb.archive.pagination.secret"]
        mock_snap.restart.assert_not_called()

    def test_set_host(self, monkeypatch: pytest.MonkeyPatch):
        """Test that set_host writes the debarchive server host."""
        mock_snap = MagicMock()
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.set_host("10.1.2.3")

        mock_cache.__getitem__.assert_called_once_with("landscape-debarchive")
        mock_snap.set.assert_called_once_with({"deb.archive.server.host": "10.1.2.3"})
        mock_snap.restart.assert_not_called()

    def test_set_host_skips_unchanged_config(self, monkeypatch: pytest.MonkeyPatch):
        """Test that set_host does not write the host when it already matches."""
        mock_snap = MagicMock()
        mock_snap.get.return_value = "10.1.2.3"
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        debarchive.set_host("10.1.2.3")

        mock_cache.__getitem__.assert_called_once_with("landscape-debarchive")
        mock_snap.set.assert_not_called()
        mock_snap.restart.assert_not_called()

    def test_get_port(self, monkeypatch: pytest.MonkeyPatch):
        """Test that get_port reads and returns the configured snap port as an integer."""
        mock_snap = MagicMock()
        mock_snap.get.return_value = "8100"
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        assert debarchive.get_port() == 8100
        mock_cache.__getitem__.assert_called_once_with("landscape-debarchive")
        mock_snap.get.assert_called_once_with("deb.archive.server.gateway-port")


class TestCharmActions:
    def test_show_config_action(self, monkeypatch: pytest.MonkeyPatch):
        """Test that show-config returns redacted snap configuration."""
        monkeypatch.setattr(
            "charm.debarchive.get_config",
            lambda: {"deb": {"archive": {"logging": {"level": "info"}}}},
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            output = harness.run_action("show-config")

            assert output.results == {"deb": {"archive": {"logging": {"level": "info"}}}}
        finally:
            harness.cleanup()

    def test_show_config_action_failure(self, monkeypatch: pytest.MonkeyPatch):
        """Test that show-config reports snap failures."""
        monkeypatch.setattr(
            "charm.debarchive.get_config",
            MagicMock(side_effect=snap.SnapError("snapd unavailable")),
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            with pytest.raises(
                testing.ActionFailed, match="Failed to read debarchive configuration"
            ):
                harness.run_action("show-config")
        finally:
            harness.cleanup()

    def test_check_health_action(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check-health returns health information."""
        monkeypatch.setattr(
            "charm.debarchive.check_health",
            lambda: {"installed": True, "healthy": True, "message": "ok"},
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            output = harness.run_action("check-health")

            assert output.results == {"installed": True, "healthy": True, "message": "ok"}
        finally:
            harness.cleanup()

    def test_check_health_action_fails_when_unhealthy(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check-health fails the action when debarchive is unhealthy."""
        monkeypatch.setattr(
            "charm.debarchive.check_health",
            lambda: {
                "installed": True,
                "healthy": False,
                "message": "debarchive snap service is not active",
            },
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            with pytest.raises(
                testing.ActionFailed, match="debarchive snap service is not active"
            ):
                harness.run_action("check-health")
        finally:
            harness.cleanup()

    def test_check_health_action_failure(self, monkeypatch: pytest.MonkeyPatch):
        """Test that check-health reports snap failures."""
        monkeypatch.setattr(
            "charm.debarchive.check_health",
            MagicMock(side_effect=snap.SnapError("snapd unavailable")),
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            with pytest.raises(testing.ActionFailed, match="Failed to check debarchive health"):
                harness.run_action("check-health")
        finally:
            harness.cleanup()

    def test_show_version_action(self, monkeypatch: pytest.MonkeyPatch):
        """Test that show-version returns snap version information."""
        monkeypatch.setattr(
            "charm.debarchive.get_version_info",
            lambda: {"installed": True, "revision": "42", "version": "1.2.3", "channel": "beta"},
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            output = harness.run_action("show-version")

            assert output.results == {
                "installed": True,
                "revision": "42",
                "version": "1.2.3",
                "channel": "beta",
            }
        finally:
            harness.cleanup()

    def test_show_version_action_failure(self, monkeypatch: pytest.MonkeyPatch):
        """Test that show-version reports snap failures."""
        monkeypatch.setattr(
            "charm.debarchive.get_version_info",
            MagicMock(side_effect=snap.SnapError("snapd unavailable")),
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            with pytest.raises(testing.ActionFailed, match="Failed to read debarchive version"):
                harness.run_action("show-version")
        finally:
            harness.cleanup()

    def test_restart_snap_action(self, monkeypatch: pytest.MonkeyPatch):
        """Test that restart-snap restarts debarchive."""
        restart = MagicMock()
        monkeypatch.setattr("charm.debarchive.restart", restart)
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            output = harness.run_action("restart-snap")

            restart.assert_called_once_with()
            assert output.results == {"restarted": True}
        finally:
            harness.cleanup()

    def test_restart_snap_action_failure(self, monkeypatch: pytest.MonkeyPatch):
        """Test that restart-snap reports snap failures."""
        monkeypatch.setattr(
            "charm.debarchive.restart", MagicMock(side_effect=snap.SnapError("snapd unavailable"))
        )
        harness = testing.Harness(DebarchiveOperatorCharm)
        harness.begin()
        try:
            with pytest.raises(testing.ActionFailed, match="Failed to restart debarchive snap"):
                harness.run_action("restart-snap")
        finally:
            harness.cleanup()


class TestDatabaseRelation:
    def test_database_created(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm processes the database credentials and configures the snap."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_snap.present = True

        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        db_rel = testing.Relation(
            endpoint="database",
            interface="postgresql_client",
            remote_app_data={
                "endpoints": "db-host:5432",
                "username": "testuser",
                "password": "testpassword",
                "database": "debarchive",
                "tls": "True",
            },
        )
        state_in = testing.State(relations=[db_rel])

        state_out = ctx.run(ctx.on.relation_changed(db_rel), state_in)

        mock_snap.set.assert_called_once_with(
            {
                "deb.archive.database.host": "db-host",
                "deb.archive.database.port": "5432",
                "deb.archive.database.user": "testuser",
                "deb.archive.database.password": "testpassword",
                "deb.archive.database.name": "debarchive",
                "deb.archive.database.ssl": "require",
                "deb.archive.database.driver": "pgx",
            }
        )
        mock_snap.restart.assert_not_called()
        assert state_out.unit_status == testing.ActiveStatus()

    def test_database_created_missing_info_defers(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm defers the event if database relation properties are missing."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_snap = MagicMock()
        mock_cache = MagicMock()
        mock_cache.__getitem__.return_value = mock_snap
        monkeypatch.setattr("debarchive.snap.SnapCache", lambda: mock_cache)

        db_rel = testing.Relation(
            endpoint="database",
            interface="postgresql_client",
            remote_app_data={
                "endpoints": "",
                "username": "",
                "password": "",
                "database": "",
            },
        )
        state_in = testing.State(relations=[db_rel])

        state_out = ctx.run(ctx.on.relation_changed(db_rel), state_in)

        assert len(state_out.deferred) == 1
        mock_snap.set.assert_not_called()

    def test_database_created_configure_exception(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the charm sets BlockedStatus when configure_database fails."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr(
            "charm.debarchive.configure_database", MagicMock(side_effect=Exception("snap error"))
        )

        db_rel = testing.Relation(
            endpoint="database",
            interface="postgresql_client",
            remote_app_data={
                "endpoints": "db-host:5432",
                "username": "testuser",
                "password": "testpass",
                "database": "debarchive",
            },
        )
        state_in = testing.State(relations=[db_rel])

        state_out = ctx.run(ctx.on.relation_changed(db_rel), state_in)

        assert state_out.unit_status == testing.BlockedStatus(
            "Failed to configure database connection"
        )


class TestLandscapeServerRelation:
    def test_landscape_server_relation_stores_hostname(self, monkeypatch: pytest.MonkeyPatch):
        """Test that hostname is stored and the shared secret token is configured."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_secret = MagicMock()
        mock_set_host = MagicMock()
        mock_get_port = MagicMock(return_value=8100)
        monkeypatch.setattr("charm.debarchive.set_secret_token", mock_set_secret)
        monkeypatch.setattr("charm.debarchive.set_host", mock_set_host)
        monkeypatch.setattr("charm.debarchive.get_port", mock_get_port)

        secret = testing.Secret(tracked_content={"secret-token": "jwt-secret"})
        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={
                "hostname": "landscape.example.com",
                "secret-token-id": secret.id,
            },
        )
        state_in = testing.State(relations=[rel], secrets=[secret])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        stored = state_out.get_stored_state("_stored", owner_path="DebarchiveOperatorCharm")
        assert stored.content["hostname"] == "landscape.example.com"
        assert stored.content["secret_token"] == "jwt-secret"
        mock_set_secret.assert_called_once_with({"secret-token": "jwt-secret"})
        mock_set_host.assert_called_once_with("192.0.2.0")
        mock_get_port.assert_called_once_with()

    def test_landscape_server_relation_no_app(self, monkeypatch: pytest.MonkeyPatch):
        """Test that nothing is stored when the relation-changed event has no remote app."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_secret = MagicMock()
        monkeypatch.setattr("charm.debarchive.set_secret_token", mock_set_secret)

        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={},
        )
        state_in = testing.State(relations=[rel])

        with ctx(ctx.on.relation_changed(rel), state_in) as manager:
            event = MagicMock()
            event.app = None
            manager.charm._on_landscape_server_changed(event)

            assert manager.charm._stored.hostname is None

        mock_set_secret.assert_not_called()

    def test_landscape_server_relation_no_data(self, monkeypatch: pytest.MonkeyPatch):
        """Test missing relation data does not store values and defers the event."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_secret = MagicMock()
        monkeypatch.setattr("charm.debarchive.set_secret_token", mock_set_secret)

        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={},
        )
        state_in = testing.State(relations=[rel])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        stored = state_out.get_stored_state("_stored", owner_path="DebarchiveOperatorCharm")
        assert stored.content["hostname"] is None
        mock_set_secret.assert_not_called()
        # Without a secret-token-id the event is deferred so it can be retried.
        assert len(state_out.deferred) == 1

    def test_landscape_server_relation_secret_without_hostname(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that the secret token is configured even when no hostname is published yet."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_secret = MagicMock()
        monkeypatch.setattr("charm.debarchive.set_secret_token", mock_set_secret)

        secret = testing.Secret(tracked_content={"secret-token": "jwt-secret"})
        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={
                "secret-token-id": secret.id,
            },
        )
        state_in = testing.State(relations=[rel], secrets=[secret])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        # The token is set despite the hostname being absent (they are decoupled).
        stored = state_out.get_stored_state("_stored", owner_path="DebarchiveOperatorCharm")
        assert stored.content["hostname"] is None
        assert stored.content["secret_token"] == "jwt-secret"
        mock_set_secret.assert_called_once_with({"secret-token": "jwt-secret"})

    def test_landscape_server_relation_token_already_stored(self, monkeypatch: pytest.MonkeyPatch):
        """Test that repeated relation events still write the relation token."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_secret = MagicMock()
        mock_set_host = MagicMock()
        mock_get_port = MagicMock(return_value=8100)
        monkeypatch.setattr("charm.debarchive.set_secret_token", mock_set_secret)
        monkeypatch.setattr("charm.debarchive.set_host", mock_set_host)
        monkeypatch.setattr("charm.debarchive.get_port", mock_get_port)

        secret = testing.Secret(tracked_content={"secret-token": "jwt-secret"})
        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={
                "hostname": "landscape.example.com",
                "secret-token-id": secret.id,
            },
        )
        stored = testing.StoredState(
            owner_path="DebarchiveOperatorCharm",
            name="_stored",
            content={"hostname": "landscape.example.com", "secret_token": "jwt-secret"},
        )
        state_in = testing.State(relations=[rel], secrets=[secret], stored_states=[stored])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        assert state_out.unit_status == testing.ActiveStatus()
        stored = state_out.get_stored_state("_stored", owner_path="DebarchiveOperatorCharm")
        assert stored.content["secret_token"] == "jwt-secret"
        mock_set_secret.assert_called_once_with({"secret-token": "jwt-secret"})
        mock_set_host.assert_called_once_with("192.0.2.0")
        mock_get_port.assert_called_once_with()

    def test_landscape_server_relation_secret_not_found(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the unit blocks when the advertised secret cannot be read."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_host = MagicMock()
        mock_get_port = MagicMock(return_value=8100)
        monkeypatch.setattr("charm.debarchive.set_host", mock_set_host)
        monkeypatch.setattr("charm.debarchive.get_port", mock_get_port)

        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={
                "hostname": "landscape.example.com",
                "secret-token-id": "secret:doesnotexist",
            },
        )
        state_in = testing.State(relations=[rel])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        assert state_out.unit_status == testing.BlockedStatus("no secret token")
        mock_set_host.assert_called_once_with("192.0.2.0")
        mock_get_port.assert_called_once_with()

    def test_landscape_server_relation_secret_missing_token(self, monkeypatch: pytest.MonkeyPatch):
        """Test that a readable secret without secret-token blocks cleanly."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        mock_set_secret = MagicMock()
        mock_set_host = MagicMock()
        mock_get_port = MagicMock(return_value=8100)
        monkeypatch.setattr("charm.debarchive.set_secret_token", mock_set_secret)
        monkeypatch.setattr("charm.debarchive.set_host", mock_set_host)
        monkeypatch.setattr("charm.debarchive.get_port", mock_get_port)

        secret = testing.Secret(tracked_content={"other-key": "jwt-secret"})
        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={
                "hostname": "landscape.example.com",
                "secret-token-id": secret.id,
            },
        )
        state_in = testing.State(relations=[rel], secrets=[secret])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        assert state_out.unit_status == testing.BlockedStatus("no secret token")
        mock_set_secret.assert_not_called()
        mock_set_host.assert_called_once_with("192.0.2.0")
        mock_get_port.assert_called_once_with()

    def test_landscape_server_relation_configure_secret_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that snap failures while applying the token do not fail the hook."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        monkeypatch.setattr(
            "charm.debarchive.set_secret_token",
            MagicMock(side_effect=snap.SnapError("snapd unavailable")),
        )
        mock_set_host = MagicMock()
        mock_get_port = MagicMock(return_value=8100)
        monkeypatch.setattr("charm.debarchive.set_host", mock_set_host)
        monkeypatch.setattr("charm.debarchive.get_port", mock_get_port)

        secret = testing.Secret(tracked_content={"secret-token": "jwt-secret"})
        rel = testing.Relation(
            endpoint="landscape-server",
            interface="landscape-debarchive",
            remote_app_data={
                "hostname": "landscape.example.com",
                "secret-token-id": secret.id,
            },
        )
        state_in = testing.State(relations=[rel], secrets=[secret])

        state_out = ctx.run(ctx.on.relation_changed(rel), state_in)

        assert state_out.unit_status == testing.BlockedStatus("Failed to configure secret token")
        stored = state_out.get_stored_state("_stored", owner_path="DebarchiveOperatorCharm")
        assert stored.content["secret_token"] is None
        mock_set_host.assert_called_once_with("192.0.2.0")
        mock_get_port.assert_called_once_with()


class TestHaproxyRouteRelation:
    def test_relation_joined_defers_without_landscape_hostname(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test that joining the haproxy-route relation defers without a Landscape hostname."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        provide = MagicMock()
        monkeypatch.setattr(
            "charm.HaproxyRouteRequirer.provide_haproxy_route_requirements", provide
        )

        haproxy_rel = testing.Relation(
            endpoint="debarchive-haproxy-route", interface="haproxy-route"
        )
        network = testing.Network(
            "debarchive-haproxy-route",
            bind_addresses=[testing.BindAddress([testing.Address("10.1.2.3")])],
        )
        state_in = testing.State(relations=[haproxy_rel], networks={network})

        state_out = ctx.run(ctx.on.relation_joined(haproxy_rel), state_in)

        assert len(state_out.deferred) == 1
        provide.assert_not_called()

    def test_relation_uses_landscape_hostname(self, monkeypatch: pytest.MonkeyPatch):
        """Test that the haproxy-route relation uses the Landscape hostname when available."""
        ctx = testing.Context(DebarchiveOperatorCharm)
        mock_set_host = MagicMock()
        mock_get_port = MagicMock(return_value=8100)
        monkeypatch.setattr("charm.debarchive.set_host", mock_set_host)
        monkeypatch.setattr("charm.debarchive.get_port", mock_get_port)

        captured = {}

        def fake_provide(self, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(
            "charm.HaproxyRouteRequirer.provide_haproxy_route_requirements", fake_provide
        )

        haproxy_rel = testing.Relation(
            endpoint="debarchive-haproxy-route", interface="haproxy-route"
        )
        network = testing.Network(
            "debarchive-haproxy-route",
            bind_addresses=[testing.BindAddress([testing.Address("10.1.2.3")])],
        )
        stored = testing.StoredState(
            owner_path="DebarchiveOperatorCharm",
            name="_stored",
            content={"hostname": "landscape.example.com", "secret_token": None},
        )
        state_in = testing.State(
            relations=[haproxy_rel], networks={network}, stored_states=[stored]
        )

        ctx.run(ctx.on.relation_joined(haproxy_rel), state_in)

        assert captured["unit_address"] == "10.1.2.3"
        assert captured["hostname"] == "landscape.example.com"
        assert captured["ports"] == [8100]
        assert captured["paths"] == ["/debarchive"]
        assert captured["path_rewrite_expressions"] == [r"%[path,regsub(^/debarchive/?,/)]"]
        assert captured["service"].startswith("landscape-debarchive-")
        mock_set_host.assert_called_once_with("10.1.2.3")
        mock_get_port.assert_called_once_with()

    def test_unit_ip_no_binding(self, monkeypatch: pytest.MonkeyPatch):
        """Test that unit_ip is None and the route is not published without a binding."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        with ctx(ctx.on.start(), testing.State()) as manager:
            manager.run()
            charm = manager.charm
            monkeypatch.setattr(charm.model, "get_binding", lambda name: None)
            provide = MagicMock()
            monkeypatch.setattr(
                charm.debarchive_haproxy_route, "provide_haproxy_route_requirements", provide
            )

            assert charm.unit_ip is None

            charm._provide_haproxy_route_requirements()
            provide.assert_not_called()

    def test_route_not_published_without_unit_ip(self, monkeypatch: pytest.MonkeyPatch):
        """Test that route requirements are not published without a unit IP."""
        ctx = testing.Context(DebarchiveOperatorCharm)
        stored = testing.StoredState(
            owner_path="DebarchiveOperatorCharm",
            name="_stored",
            content={"hostname": "landscape.example.com", "secret_token": None},
        )

        with ctx(ctx.on.start(), testing.State(stored_states=[stored])) as manager:
            manager.run()
            charm = manager.charm
            monkeypatch.setattr(charm.model, "get_binding", lambda name: None)
            provide = MagicMock()
            monkeypatch.setattr(
                charm.debarchive_haproxy_route, "provide_haproxy_route_requirements", provide
            )

            assert charm._provide_haproxy_route_requirements() is False
            provide.assert_not_called()

    def test_unit_ip_model_error(self, monkeypatch: pytest.MonkeyPatch):
        """Test that unit_ip returns None when reading the bind address raises ModelError."""
        ctx = testing.Context(DebarchiveOperatorCharm)

        class FakeNetwork:
            @property
            def bind_address(self):
                raise ModelError("no bind address")

        class FakeBinding:
            network = FakeNetwork()

        with ctx(ctx.on.start(), testing.State()) as manager:
            manager.run()
            charm = manager.charm
            monkeypatch.setattr(charm.model, "get_binding", lambda name: FakeBinding())

            assert charm.unit_ip is None
