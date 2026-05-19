#!/usr/bin/env python3
"""Charm the service."""

import logging

import ops
from charmlibs import snap
from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseRequires,
)

import debarchive

logger = logging.getLogger(__name__)


class DebarchiveOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)

        self.database = DatabaseRequires(
            self, relation_name="database", database_name="debarchive"
        )

        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.database.on.database_created, self._on_database_created)
        framework.observe(self.database.on.endpoints_changed, self._on_database_created)

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
        self.unit.open_port("tcp", 8000)
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
                my_snap.set({"deb.archive.server.port": str(port)})
                my_snap.restart()

                for opened_port in self.unit.opened_ports():
                    self.unit.close_port(opened_port.protocol, opened_port.port)

                self.unit.open_port("tcp", int(port))

        except snap.SnapError:
            self.unit.status = ops.BlockedStatus("Failed to apply configuration")
            return

        self.unit.status = ops.ActiveStatus()

    def _on_database_created(self, event):
        """Update database information for relation in the snap."""
        endpoints_str = event.endpoints or ""
        username = event.username or ""
        password = event.password or ""
        database = event.database or ""
        endpoint = endpoints_str.split(",")[0] if endpoints_str else ""

        if not endpoint or not username or not password or not database:
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


if __name__ == "__main__":  # pragma: nocover
    ops.main(DebarchiveOperatorCharm)
