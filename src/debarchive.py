"""Functions for managing and interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import base64
import logging
import secrets
from typing import Any

from charmlibs import snap

logger = logging.getLogger(__name__)

DEBARCHIVE_SNAP_NAME = "landscape-debarchive"
SNAPS_TO_INSTALL = [(DEBARCHIVE_SNAP_NAME, {"channel": "beta"})]
LOG_LEVELS = frozenset({"debug", "warn", "error", "info", "trace", "fatal"})
SENSITIVE_CONFIG_FIELDS = frozenset({"password", "secret"})


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


def configure(gateway_port: int, log_level: str, log_human_readable: bool) -> None:
    """Set debarchive application parameters in the snap configuration."""
    normalized_level = log_level.lower()
    if normalized_level not in LOG_LEVELS:
        raise ValueError(f"unsupported log level: {log_level}")

    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    if not debarchive_snap.present:
        return

    debarchive_snap.set(
        {
            "deb.archive.server.gateway-port": str(gateway_port),
            "deb.archive.logging.level": normalized_level,
            "deb.archive.logging.human-readable": str(log_human_readable).lower(),
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


def get_version_info() -> dict[str, str | bool | None]:
    """Get debarchive snap version information."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    return {
        "installed": debarchive_snap.present,
        "revision": str(debarchive_snap.revision) if debarchive_snap.present else None,
        "version": debarchive_snap.version if debarchive_snap.present else None,
        "channel": debarchive_snap.channel if debarchive_snap.present else None,
    }


def get_config() -> dict[str, Any]:
    """Get redacted debarchive snap configuration."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    if not debarchive_snap.present:
        return {}

    config = debarchive_snap.get(None, typed=True)
    return _redact_config(config)


def _redact_config(config: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive values from snap configuration."""
    redacted = {}
    for key, value in config.items():
        if key in SENSITIVE_CONFIG_FIELDS:
            redacted[key] = "<redacted>"
        elif isinstance(value, dict):
            redacted[key] = _redact_config(value)
        else:
            redacted[key] = value
    return redacted


def check_health() -> dict[str, bool | str]:
    """Check whether the debarchive snap is installed and its services are active."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    installed = debarchive_snap.present
    services = debarchive_snap.services if installed else {}
    services_active = (
        all(service["active"] for service in services.values()) if services else False
    )
    healthy = installed and services_active

    if not installed:
        message = "debarchive snap is not installed"
    elif not services:
        message = "debarchive snap has no services"
    elif not services_active:
        inactive_services = sorted(
            service_name for service_name, service in services.items() if not service["active"]
        )
        message = f"inactive services: {', '.join(inactive_services)}"
    else:
        message = "debarchive snap services are active"

    return {"installed": installed, "healthy": healthy, "message": message}


def restart() -> None:
    """Restart debarchive snap services."""
    debarchive_snap = snap.SnapCache()[DEBARCHIVE_SNAP_NAME]
    if not debarchive_snap.present:
        raise snap.SnapNotFoundError(DEBARCHIVE_SNAP_NAME)
    debarchive_snap.restart()


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
