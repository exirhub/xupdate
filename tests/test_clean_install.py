"""Exercise destructive cleanup only inside temporary directories; systemd is simulated."""
from pathlib import Path
import subprocess
import socket
import tempfile
import unittest
from unittest.mock import patch

from xupdate import deploy
from xupdate.core import ConfigError


class CleanInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root/"old-x-ui"
        self.old.mkdir()
        (self.old/"x-ui.db").write_bytes(b"old database")
        self.unit = self.root/"x-ui.service"
        self.unit.write_text("old service")
        self.seed = self.root/"checkout/x-ui.db"
        self.seed.parent.mkdir()
        self.seed.write_bytes(b"bundled database remains unchanged")
        self.link = self.root/"x-ui-cli"
        self.link.symlink_to(self.seed)
        self.events = []
        self.run = self.enter(patch.object(deploy.subprocess, "run", side_effect=self.systemctl))
        self.command = self.enter(patch.object(deploy, "command", side_effect=self.checked))
        self.enter(patch.object(deploy, "CLEAN_PATHS", tuple(map(str, (self.old, self.unit, self.link)))))
        self.ports = self.enter(patch.object(deploy, "available_ports", side_effect=self.free_ports))
        self.snapshot = self.enter(patch.object(deploy, "snapshot", side_effect=AssertionError("Unexpected backup")))

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def systemctl(self, args, **kw):
        self.events.append(tuple(args))
        if args[1] == "show":
            stdout = ("LoadState=loaded\nActiveState=active\n" if args[2] == "x-ui.service"
                      else "LoadState=not-found\nActiveState=inactive\n")
        else:
            stdout = ""
        return subprocess.CompletedProcess(args, 0, stdout, "")

    def checked(self, args, **kw):
        self.events.append(tuple(args))
        return ""

    def free_ports(self, ports):
        self.assertEqual(ports, [80, 443, 10001, 8144, 2096])
        self.assertIn(("systemctl", "stop", "x-ui.service"), self.events)
        self.assertTrue((self.old/"x-ui.db").is_file(), "Files must survive until ports are checked")
        self.events.append(("ports-free",))

    def clean(self):
        deploy.clean_previous_installation([80, 443, 10001, 8144, 2096])

    def test_removes_previous_installation_without_backup_and_preserves_seed(self):
        seed = self.seed.read_bytes()
        self.clean()
        self.assertFalse(self.old.exists())
        self.assertFalse(self.unit.exists())
        self.assertFalse(self.link.is_symlink())
        self.assertEqual(self.seed.read_bytes(), seed)
        self.snapshot.assert_not_called()
        self.assertIn(("systemctl", "disable", "x-ui.service"), self.events)
        self.assertIn(("systemctl", "daemon-reload"), self.events)

    def test_port_conflict_preserves_files_and_restarts_previously_active_service(self):
        self.ports.side_effect = ConfigError("Port 443 is occupied")
        with self.assertRaisesRegex(ConfigError, "occupied"):
            self.clean()
        self.assertEqual((self.old/"x-ui.db").read_bytes(), b"old database")
        self.assertTrue(self.unit.is_file())
        self.assertIn(("systemctl", "start", "x-ui.service"), self.events)
        self.assertNotIn(("systemctl", "disable", "x-ui.service"), self.events)

    def test_stop_failure_does_not_delete_files(self):
        self.command.side_effect = ConfigError("Service did not stop")
        with self.assertRaisesRegex(ConfigError, "did not stop"):
            self.clean()
        self.assertTrue(self.old.is_dir())
        self.assertTrue(self.unit.is_file())
        self.ports.assert_not_called()

    def test_removes_leftover_directory_when_no_service_exists(self):
        self.run.side_effect = lambda args, **kw: subprocess.CompletedProcess(
            args, 0, "LoadState=not-found\nActiveState=inactive\n", "")
        self.ports.side_effect = None
        self.clean()
        self.assertFalse(self.old.exists())
        self.assertEqual(self.seed.read_bytes(), b"bundled database remains unchanged")

    def test_clean_mode_failure_cleanup_creates_no_database_backup(self):
        with patch.object(deploy, "OWNED", (str(self.old),)):
            deploy.cleanup_owned([str(self.old)], None)
        self.assertFalse(self.old.exists())
        self.snapshot.assert_not_called()
        self.assertTrue(self.seed.is_file())


class PortCheckTests(unittest.TestCase):
    def test_rejects_live_listener_but_allows_port_after_connection_shutdown(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            server.listen(1)
            with self.assertRaises(ConfigError):
                deploy.available_ports([port])
            with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                accepted, _ = server.accept()
                with accepted:
                    accepted.shutdown(socket.SHUT_WR)
                    self.assertEqual(client.recv(1), b"")
        deploy.available_ports([port])


if __name__ == "__main__":
    unittest.main()
