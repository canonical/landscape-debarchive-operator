import os
from pathlib import Path

import jubilant
import pytest

APP_NAME = "debarchive-operator"
SNAP_NAME = "landscape-debarchive"


@pytest.fixture(scope="module")
def juju():
    """Create a temporary Juju model for the test run and destroy it after."""
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju):
    """Deploy the charm using the Snap-safe common directory."""
    charm_env = os.environ.get("CHARM_PATH")

    if charm_env:
        charm_path = Path(charm_env).resolve()
        assert charm_path.exists(), f"Charm not found at CHARM_PATH: {charm_env}"

    juju.deploy(str(charm_path))
    juju.wait(jubilant.all_active)


def test_snap_is_installed(juju):
    """Verify that the snap was actually installed on the unit."""
    task = juju.exec(f"snap list {SNAP_NAME}", unit=f"{APP_NAME}/0")

    assert SNAP_NAME in task.stdout, f"Snap {SNAP_NAME} not found in output: {task.stdout}"
