"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import base64
import logging
import secrets

from charmlibs import snap

logger = logging.getLogger(__name__)

DEBARCHIVE_SNAP_NAME = "landscape-debarchive"
SNAPS_TO_INSTALL = [(DEBARCHIVE_SNAP_NAME, {"channel": "beta"})]


def install() -> None:
    """Handle installing anything debarchive specific (e.g., temporal snap, etc,..)."""
    _install_snap_packages()
    set_pagination_secret()


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

            # TODO: if we want a specific revision of the snap (to match charm revisions to
            # snap revisions) handle here, then hold the package
        except (snap.SnapError, snap.SnapNotFoundError) as e:
            logger.error("An exception occurred when installing %s. Reason: %s", snap_name, str(e))
            raise


def configure_database(
    host: str, port: str, user: str, password: str, database: str, ssl: str = "disable"
) -> None:
    """Set the database connection parameters in the snap configuration."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
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


def get_version() -> str | None:
    """Get the running version of the workload."""
    try:
        debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    except (snap.SnapError, snap.SnapNotFoundError) as e:
        logger.warning(f"Unable to query {DEBARCHIVE_SNAP_NAME} snap version: %s", e)
        return None

    return str(debarchive_snap.revision) if debarchive_snap.present else None


def set_secret_token(content: dict[str, str]) -> None:
    """Set the jwt secret token in the snap configuration."""
    secret_token = content["secret-token"]
    encoded_secret_token = base64.b64encode(secret_token.encode("utf-8")).decode("utf-8")
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    debarchive_snap.set(
        {
            "deb.archive.jwt.secret": encoded_secret_token,
        }
    )


def set_pagination_secret() -> None:
    """Set the pagination secret in the snap configuration."""
    raw_bytes = secrets.token_bytes(32)
    pagination_secret = base64.urlsafe_b64encode(raw_bytes).decode("utf-8")
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    debarchive_snap.set(
        {
            "deb.archive.pagination.secret": pagination_secret,
        }
    )


def set_host(host: str) -> None:
    """Set the host for the debarchive server."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    debarchive_snap.set({"deb.archive.server.host": host})


def get_port() -> int:
    """Get the gateway port for the debarchive server."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    return int(debarchive_snap.get("deb.archive.server.gateway-port"))
