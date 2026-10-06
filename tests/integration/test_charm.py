import os
from pathlib import Path

import jubilant
import pytest

APP_NAME = "landscape-debarchive"
SNAP_NAME = "landscape-debarchive"
HAPROXY_APP = "haproxy"
# Provisioning an LXD machine alone takes ~3m, which is jubilant's default wait.
WAIT_TIMEOUT = 15 * 60


@pytest.fixture(scope="module")
def juju():
    """Create a temporary Juju model for the test run and destroy it after."""
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju):
    """Deploy the charm using the Snap-safe common directory."""
    charm_env = os.environ.get("CHARM_PATH")
    assert charm_env, "CHARM_PATH environment variable is not set"

    charm_path = Path(charm_env).resolve()
    assert charm_path.exists(), f"Charm not found at CHARM_PATH: {charm_env}"

    juju.deploy(str(charm_path))
    juju.wait(jubilant.all_active, timeout=WAIT_TIMEOUT)


def test_snap_is_installed(juju):
    """Verify that the snap was actually installed on the unit."""
    task = juju.exec(f"snap list {SNAP_NAME}", unit=f"{APP_NAME}/0")

    assert SNAP_NAME in task.stdout, f"Snap {SNAP_NAME} not found in output: {task.stdout}"


def test_database_relation(juju):
    """Test that debarchive and postgres charms can be related."""
    juju.deploy("postgresql", channel="16/stable")
    juju.wait(jubilant.all_active, timeout=WAIT_TIMEOUT)
    juju.integrate(APP_NAME, "postgresql")

    juju.wait(jubilant.all_active, timeout=WAIT_TIMEOUT)

    relations = set(juju.status().apps[SNAP_NAME].relations)

    assert "database" in relations


def test_haproxy_route_relation(juju):
    """Test that debarchive can be related to haproxy over the haproxy-route interface."""
    juju.deploy(HAPROXY_APP, channel="2.8/stable")
    juju.integrate(
        f"{APP_NAME}:debarchive-haproxy-route",
        f"{HAPROXY_APP}:haproxy-route",
    )

    def _relation_ready(status: jubilant.Status) -> bool:
        app = status.apps[APP_NAME]
        relation_present = "debarchive-haproxy-route" in app.relations
        debarchive_active = all(
            unit.workload_status.current == "active" for unit in app.units.values()
        )
        return relation_present and debarchive_active

    juju.wait(_relation_ready, timeout=WAIT_TIMEOUT)

    relations = set(juju.status().apps[APP_NAME].relations)

    assert "debarchive-haproxy-route" in relations


def test_multiple_units_blocked(juju):
    """Scaling beyond one unit blocks every unit, and scaling back down clears it."""
    juju.add_unit(APP_NAME)

    def _all_blocked(status: jubilant.Status) -> bool:
        units = status.apps[APP_NAME].units
        return len(units) == 2 and all(
            unit.workload_status.current == "blocked"
            and "does not support multiple units" in unit.workload_status.message
            for unit in units.values()
        )

    def _debarchive_active(status: jubilant.Status) -> bool:
        # haproxy is left unconfigured by this test module and stays blocked,
        # so scope the check to debarchive rather than using jubilant.all_active.
        units = status.apps[APP_NAME].units
        return len(units) == 1 and all(
            unit.workload_status.current == "active" for unit in units.values()
        )

    # The pre-existing unit only re-evaluates its status on its next hook, so
    # shorten the update-status interval instead of waiting the default 5m.
    juju.model_config({"update-status-hook-interval": "10s"})
    try:
        juju.wait(_all_blocked, timeout=WAIT_TIMEOUT)

        juju.remove_unit(f"{APP_NAME}/1")
        juju.wait(_debarchive_active, timeout=WAIT_TIMEOUT)
    finally:
        juju.model_config({"update-status-hook-interval": "5m"})
