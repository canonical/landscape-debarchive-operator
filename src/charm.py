#!/usr/bin/env python3
"""Charm the service."""

import logging

import ops
from charmlibs import snap
from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseRequires,
)
from charms.haproxy.v1.haproxy_route import HaproxyRouteRequirer
from ops.charm import (
    RelationChangedEvent,
    RelationJoinedEvent,
)
from ops.model import ModelError

import debarchive

logger = logging.getLogger(__name__)

HAPROXY_ROUTE_RELATION = "debarchive-haproxy-route"
DEBARCHIVE_ROUTE_PREFIX = "/debarchive"
DEBARCHIVE_PATH_REWRITE = r"%[path,regsub(^/debarchive/?,/)]"


class DebarchiveOperatorCharm(ops.CharmBase):
    """Charm the application."""

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self._stored.set_default(hostname=None, secret_token=None)

        self.database = DatabaseRequires(
            self, relation_name="database", database_name="debarchive"
        )

        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.database.on.database_created, self._on_database_configured)
        framework.observe(self.database.on.endpoints_changed, self._on_database_configured)
        framework.observe(
            self.on.landscape_server_relation_joined, self._on_landscape_server_changed
        )
        framework.observe(
            self.on.landscape_server_relation_changed, self._on_landscape_server_changed
        )

        self.debarchive_haproxy_route = HaproxyRouteRequirer(
            self, relation_name=HAPROXY_ROUTE_RELATION
        )
        framework.observe(
            self.on[HAPROXY_ROUTE_RELATION].relation_joined,
            self._on_haproxy_route_relation_joined,
        )
        framework.observe(
            self.on[HAPROXY_ROUTE_RELATION].relation_changed,
            self._on_haproxy_route_relation_joined,
        )

    @property
    def unit_ip(self) -> str | None:
        """Return the IP address bound to the haproxy-route endpoint."""
        network_binding = self.model.get_binding(HAPROXY_ROUTE_RELATION)
        if network_binding is None:
            return None

        try:
            bind_address = network_binding.network.bind_address
        except ModelError as e:
            logger.warning(f"No bind address found for `{HAPROXY_ROUTE_RELATION}`: {e}")
            return None

        return str(bind_address) if bind_address else None

    def _on_install(self, event: ops.InstallEvent):
        """Install the workload on the machine."""
        debarchive.install()

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("starting workload")
        debarchive.start()
        version = debarchive.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event):
        """Represent an example of what the config would look like for the snap.

        We would ideally do this in `src/debarchive.py` or something more organized.
        """
        port = self.config["server-port"]

        self.unit.status = ops.MaintenanceStatus(f"Configuring port to {port}...")

        try:
            cache = snap.SnapCache()
            my_snap = cache["landscape-debarchive"]

            if my_snap.present:
                my_snap.set({"deb.archive.server.gateway-port": str(port)})

        except snap.SnapError:
            self.unit.status = ops.BlockedStatus("Failed to apply configuration")
            return

        self._provide_haproxy_route_requirements()

        self.unit.status = ops.ActiveStatus()

    def _on_database_configured(self, event):
        """Update database information for relation in the snap."""
        endpoints_str = event.endpoints or ""
        username = event.username or ""
        password = event.password or ""
        database = event.database or ""
        endpoint = endpoints_str.split(",")[0] if endpoints_str else ""

        if not all([endpoint, username, password, database]):
            event.defer()
            return

        host, port = endpoint.split(":") if ":" in endpoint else (endpoint, "5432")
        ssl = "require" if str(event.tls).lower() == "true" else "disable"

        self.unit.status = ops.MaintenanceStatus("Configuring database connection...")

        try:
            debarchive.configure_database(host, port, username, password, database, ssl)
        except Exception:
            self.unit.status = ops.BlockedStatus("Failed to configure database connection")
            return

        self.unit.status = ops.ActiveStatus()

    def _on_haproxy_route_relation_joined(
        self, event: RelationJoinedEvent | RelationChangedEvent
    ) -> None:
        """Provide the haproxy-route requirements when the relation changes."""
        if not self._provide_haproxy_route_requirements():
            event.defer()

    def _provide_haproxy_route_requirements(self) -> bool:
        """Publish this unit's haproxy-route requirements to the related haproxy."""
        if not self._stored.hostname:
            return False

        unit_ip = self.unit_ip
        if not unit_ip:
            return False

        debarchive.set_host(unit_ip)
        port = debarchive.get_port()

        self.debarchive_haproxy_route.provide_haproxy_route_requirements(
            service=f"landscape-debarchive-{self.model.uuid}",
            ports=[port],
            paths=[DEBARCHIVE_ROUTE_PREFIX],
            protocol="http",
            check_path=DEBARCHIVE_ROUTE_PREFIX,
            path_rewrite_expressions=[DEBARCHIVE_PATH_REWRITE],
            header_rewrite_expressions=[("X-Forwarded-Proto", "https")],
            allow_http=True,
            unit_address=unit_ip,
            hostname=self._stored.hostname,
        )
        return True

    def _on_landscape_server_changed(self, event):
        """Store data published by the Landscape Server charm."""
        if event.app is None:
            logger.warning("landscape-server relation-changed fired without an app; deferring")
            event.defer()
            return

        app_data = event.relation.data[event.app]
        logger.info("landscape-server relation data keys: %s", sorted(app_data.keys()))

        hostname = app_data.get("hostname")
        if hostname:
            self._stored.hostname = hostname
            logger.info("Stored Landscape hostname: %s", hostname)
            self._provide_haproxy_route_requirements()
        else:
            logger.info("landscape-server has not published a hostname yet")

        # The secret token is independent of the hostname: set it whenever a
        # secret-token-id is available, even if the hostname hasn't been published.
        secret_id = app_data.get("secret-token-id")
        if not secret_id:
            logger.info("landscape-server has not published a secret-token-id yet; deferring")
            event.defer()
            return

        try:
            secret = self.model.get_secret(id=secret_id)
            content = secret.get_content(refresh=True)
        except (ops.SecretNotFoundError, ops.ModelError):
            logger.warning("no secret token for secret-token-id %s", secret_id)
            self.unit.status = ops.BlockedStatus("no secret token")
            return

        secret_token = content.get("secret-token")
        if not secret_token:
            logger.warning("secret-token-id %s does not contain a secret-token", secret_id)
            self.unit.status = ops.BlockedStatus("no secret token")
            return

        try:
            debarchive.set_secret_token(content)
        except (snap.SnapError, snap.SnapNotFoundError):
            logger.exception("failed to configure debarchive secret token")
            self.unit.status = ops.BlockedStatus("Failed to configure secret token")
            return

        self._stored.secret_token = secret_token
        self.unit.status = ops.ActiveStatus()
        logger.info("Set debarchive secret token from secret-token-id %s", secret_id)


if __name__ == "__main__":  # pragma: nocover
    ops.main(DebarchiveOperatorCharm)
