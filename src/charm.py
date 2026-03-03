#!/usr/bin/env python3
"""Charm the service."""

import ops
from charmlibs import snap

import debarchive


class DebarchiveOperatorCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)

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


if __name__ == "__main__":  # pragma: nocover
    ops.main(DebarchiveOperatorCharm)
