import shutil
from pathlib import Path

import jubilant
import pytest

APP_NAME = "debarchive-operator"
SNAP_NAME = "landscape-debarchive"
CHARM_PATH = str(Path("../../debarchive-operator_ubuntu@24.04-amd64.charm").resolve())


@pytest.fixture(scope="module")
def juju():
    """Create a temporary Juju model for the test run and destroy it after."""
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju):
    """Deploy the charm using the Snap-safe common directory."""
    charm_files = list(Path(".").glob("*.charm"))
    assert charm_files, "No .charm file found."
    original_charm_path = charm_files[0].resolve()

    # NOTE: This is only needed for corporate laptops because of the permission
    # issues with the UID generated. Unsure if this should be kept or for real testing
    # we just use the normal path?
    safe_charm_path = Path("/var/snap/juju/common/charm-tests/debarchive.charm")
    shutil.copy(original_charm_path, safe_charm_path)
    juju.deploy(str(safe_charm_path))
    juju.wait(jubilant.all_active)


def test_snap_is_installed(juju):
    """Verify that the snap was actually installed on the unit."""
    task = juju.exec(f"snap list {SNAP_NAME}", unit=f"{APP_NAME}/0")

    assert SNAP_NAME in task.stdout, f"Snap {SNAP_NAME} not found in output: {task.stdout}"
