"""Health diagnostics distinguish services and failed network stages."""
import ssl
import unittest
from unittest.mock import patch

from xupdate import deploy
from xupdate.core import ConfigError


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.plan = {"domain": "example.com", "backend_port": 10001,
                     "panel_port": 8144, "panel_path": "/private-panel/"}
        self.states = {"x-ui": True, "xupdate-nginx": True}
        self.command = self.enter(patch.object(deploy, "command", side_effect=self.systemctl))
        self.frontend = self.enter(patch.object(deploy, "origin_connection"))
        self.frontend.return_value.__enter__.return_value.selected_alpn_protocol.return_value = "h2"
        self.backend = self.enter(patch.object(deploy.socket, "create_connection"))
        self.backend.return_value.__enter__.return_value.recv.return_value = bytes.fromhex("000000040000000000")
        self.http = self.enter(patch.object(deploy, "origin_http", side_effect=self.http_reply))
        self.public = self.enter(patch.object(deploy.urllib.request, "urlopen"))

    def enter(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def systemctl(self, args, **kwargs):
        # Model systemctl's real ANY-active semantics to catch grouped checks.
        if not any(self.states.get(unit, False) for unit in args[3:]):
            raise ConfigError("systemctl failed (exit 3); inspect the service journal locally.")
        return ""

    def http_reply(self, plan, path):
        if path == "/healthz":
            return 200, b"ok\n"
        if path == "/":
            return 200, b"XUPDATE"
        return 200, b"panel"

    def test_each_required_service_must_be_active(self):
        for stopped in self.states:
            with self.subTest(stopped=stopped):
                self.states = {unit: unit != stopped for unit in self.states}
                with self.assertRaisesRegex(ConfigError, f"service {stopped}:"):
                    deploy.health(self.plan)
        self.frontend.assert_not_called()

    def test_refused_frontend_identifies_443(self):
        self.frontend.side_effect = ConnectionRefusedError("sensitive error detail")
        with self.assertRaisesRegex(ConfigError, r"frontend TLS .*127\.0\.0\.1:443.*connection refused") as result:
            deploy.health(self.plan)
        self.assertNotIn("sensitive", str(result.exception))

    def test_refused_backend_identifies_10001(self):
        self.backend.side_effect = ConnectionRefusedError()
        with self.assertRaisesRegex(ConfigError, r"Xray gRPC backend .*10001.*connection refused"):
            deploy.health(self.plan)

    def test_backend_timeout_names_stage(self):
        self.backend.return_value.__enter__.return_value.recv.side_effect = TimeoutError()
        with self.assertRaisesRegex(ConfigError, r"Xray gRPC backend .*timed out"):
            deploy.health(self.plan)

    def test_wrong_backend_protocol_is_reported(self):
        self.backend.return_value.__enter__.return_value.recv.return_value = b"HTTP/1.1 "
        with self.assertRaisesRegex(ConfigError, r"Xray gRPC backend .*HTTP/2 SETTINGS"):
            deploy.health(self.plan)

    def test_tls_failure_names_frontend_without_raw_details(self):
        self.frontend.side_effect = ssl.SSLError("sensitive TLS detail")
        with self.assertRaisesRegex(ConfigError, r"frontend TLS .*TLS negotiation") as result:
            deploy.health(self.plan)
        self.assertNotIn("sensitive", str(result.exception))

    def test_panel_failure_names_route_port_and_status_not_private_path(self):
        self.http.side_effect = [(200, b"ok\n"), (200, b"XUPDATE"), (502, b"private response")]
        with self.assertRaisesRegex(ConfigError, r"panel route .*8144.*HTTP 502") as result:
            deploy.health(self.plan)
        self.assertNotIn("private", str(result.exception))

    def test_public_failure_is_distinct_from_local_checks(self):
        self.public.side_effect = OSError("private network detail")
        with self.assertRaisesRegex(ConfigError, r"public HTTPS /healthz: OSError") as result:
            deploy.health(self.plan, public=True)
        self.assertNotIn("private", str(result.exception))

    def test_success_retains_end_to_end_test_limitation(self):
        result = deploy.health(self.plan)
        self.assertEqual(result["services"], "active")
        self.assertEqual(result["authenticated_vless_end_to_end"], "not tested")
        self.assertEqual(result["public_cdn"], "not checked")
        self.public.assert_not_called()


if __name__ == "__main__":
    unittest.main()
