"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import logging

from charmlibs import snap

logger = logging.getLogger(__name__)

SNAPS_TO_INSTALL = [("landscape-debarchive", {"channel": "beta"})]


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


def configure_database(
    host: str, port: str, user: str, password: str, database: str, ssl: str = "disable"
) -> None:
    """Set the database connection parameters in the snap configuration."""
    debarchive_snap = snap.SnapCache()["landscape-debarchive"]
    debarchive_snap.set(
        {
            "deb.archive.database.host": host,
            "deb.archive.database.port": port,
            "deb.archive.database.user": user,
            "deb.archive.database.password": password,
            "deb.archive.database.name": database,
            "deb.archive.database.ssl": ssl,
            "deb.archive.database.driver": "pgx",
        }
    )
    debarchive_snap.restart()


def get_version() -> str | None:
    """Get the running version of the workload."""
    try:
        debarchive_snap = snap.SnapCache()["landscape-debarchive"]
    except (snap.SnapError, snap.SnapNotFoundError) as e:
        logger.warning("Unable to query landscape-debarchive snap version: %s", e)
        return None

    return str(debarchive_snap.revision) if debarchive_snap.present else None
