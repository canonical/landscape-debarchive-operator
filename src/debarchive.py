"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging

from charmlibs import snap

logger = logging.getLogger(__name__)

SNAPS_TO_INSTALL = [("landscape-debarchive", {"channel": "edge"})]

# Functions for managing the workload process on the local machine:


def install() -> None:
    """Handle installing anything debarchive specific (e.g., temporal snap, etc,..)."""
    _install_snap_packages()


def start() -> None:
    """Start the workload (by running a commamd, for example)."""
    # You'll need to implement this function.
    # Ideally, this function should only return once the workload is ready to use.


def _install_snap_packages():
    """Install snaps required for debarchive."""
    for snap_name, snap_version in SNAPS_TO_INSTALL:
        try:
            snap_cache = snap.SnapCache()
            snap_package = snap_cache[snap_name]

            if not snap_package.present:
                if "channel" in snap_version:
                    snap_package.ensure(snap.SnapState.Latest, channel=snap_version["channel"])

            if snap_name == "landscape-debarchive":
                snap_package.set({"deb.archive.server.host": "0.0.0.0"})
                snap_package.restart()

            # TODO: if we want a specific revision of the snap (to match charm revisions to
            # snap revisions) handle here, then hold the package
        except (snap.SnapError, snap.SnapNotFoundError) as e:
            logger.error("An exception occurred when installing %s. Reason: %s", snap_name, str(e))
            raise


# Functions for interacting with the workload, for example over HTTP:


def get_version() -> str | None:
    """Get the running version of the workload."""
    # You'll need to implement this function (or remove it if not needed).
    return None
