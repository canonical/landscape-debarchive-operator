import os
from pathlib import Path

import jubilant
import pytest

APP_NAME = "landscape-debarchive"
SNAP_NAME = "landscape-debarchive"


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
    juju.wait(jubilant.all_active)


def test_snap_is_installed(juju):
    """Verify that the snap was actually installed on the unit."""
    task = juju.exec(f"snap list {SNAP_NAME}", unit=f"{APP_NAME}/0")

    assert SNAP_NAME in task.stdout, f"Snap {SNAP_NAME} not found in output: {task.stdout}"


def test_database_relation(juju):
    """Test that debarchive and postgres charms can be related."""
    juju.deploy("postgresql", channel="16/stable")
    juju.wait(jubilant.all_active)
    juju.integrate(APP_NAME, "postgresql")

    juju.wait(jubilant.all_active)

    relations = set(juju.status().apps[SNAP_NAME].relations)

    assert "database" in relations
