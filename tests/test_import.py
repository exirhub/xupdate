"""Migration tests use synthetic rows and an ephemeral self-signed certificate."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from xupdate.core import ConfigError, inspect, prepare

ROOT = Path(__file__).resolve().parents[1]
PRESERVED = ("clients", "client_inbounds", "client_traffics", "users", "api_tokens")


class ImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certs = tempfile.TemporaryDirectory()
        folder = Path(cls.certs.name)
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(folder/"key.pem"), "-out", str(folder/"cert.pem"),
            "-days", "7", "-subj", "/CN=origin.example.org",
            "-addext", "subjectAltName=DNS:origin.example.org",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cls.cert = (folder/"cert.pem").read_text().splitlines()
        cls.key = (folder/"key.pem").read_text().splitlines()

    @classmethod
    def tearDownClass(cls):
        cls.certs.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder/"input.db"
        self.stream = {
            "network": "grpc", "security": "tls",
            "grpcSettings": {"serviceName": "sample.v1.Tracker", "multiMode": True,
                             "authority": "origin.example.org"},
            "tlsSettings": {"alpn": ["h2"], "settings": {"fingerprint": "chrome"},
                            "certificates": [{"certificate": self.cert, "key": self.key}]},
        }
        with sqlite3.connect(self.source) as db:
            db.executescript((ROOT/"tests/schema.sql").read_text())
            db.execute("INSERT INTO users (id,username,password,login_epoch) VALUES (1,?,?,7)",
                       ("test-admin", "synthetic-password-hash"))
            db.execute("INSERT INTO api_tokens (name,token) VALUES (?,?)",
                       ("synthetic-token", "not-a-live-api-token"))
            db.execute("INSERT INTO inbounds (id,user_id,up,down,total,remark,enable,listen,port,protocol,settings,stream_settings,tag,sniffing) VALUES (13,1,123,456,999,?,1,'',443,'vless',?,?,?,?)",
                       ("Keep this remark", json.dumps({"clients": [], "decryption": "none"}),
                        json.dumps(self.stream), "inbound-13", '{"enabled":false}'))
            for client, enabled in ((1, 1), (2, 0)):
                db.execute("INSERT INTO clients (id,email,uuid,sub_id,flow,enable) VALUES (?,?,?,?,?,?)",
                           (client, f"test-{client}", f"00000000-0000-4000-8000-{client:012d}",
                            f"synthetic-sub-{client}", "", enabled))
                db.execute("INSERT INTO client_inbounds VALUES (?,13,NULL,123)", (client,))
                db.execute("INSERT INTO client_traffics (id,inbound_id,email,up,down) VALUES (?,13,?,100,200)",
                           (client, f"test-{client}"))
            values = {
                "webPort": "8144", "webBasePath": "/test-panel/",
                "webCertFile": "/old/cert.pem", "webKeyFile": "/old/key.pem",
                "xrayTemplateConfig": json.dumps({"inbounds": [], "outbounds": [{"protocol": "freedom"}],
                                                  "routing": {"rules": []}}),
            }
            db.executemany("INSERT INTO settings (key,value) VALUES (?,?)", values.items())

    def render(self, **kw):
        return prepare(self.source, self.folder/"render", ROOT, **kw)

    def edit_stream(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE inbounds SET stream_settings=?", (json.dumps(self.stream),))

    def test_preserves_identity_counters_and_source_bytes(self):
        before = self.source.read_bytes()
        plan = self.render()
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(plan["source_sha256"], hashlib.sha256(before).hexdigest())
        with sqlite3.connect(self.source) as original, sqlite3.connect(self.folder/"render/x-ui.db") as staged:
            for table in PRESERVED:
                self.assertEqual(original.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall(),
                                 staged.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall(), table)
            old = original.execute("SELECT up,down,total,settings,remark,tag FROM inbounds").fetchone()
            self.assertEqual(old, staged.execute("SELECT up,down,total,settings,remark,tag FROM inbounds").fetchone())
            listener, port, raw = staged.execute("SELECT listen,port,stream_settings FROM inbounds").fetchone()
            self.assertEqual((listener, port), ("127.0.0.1", 10001))
            stream = json.loads(raw)
            self.assertEqual(stream["grpcSettings"], self.stream["grpcSettings"])
            self.assertEqual(stream["network"], "grpc")
            self.assertEqual(stream["security"], "none")
            self.assertNotIn("tlsSettings", stream)
            host = staged.execute("SELECT port,security,sni,alpn,fingerprint FROM hosts").fetchone()
            self.assertEqual(host, (443, "tls", "origin.example.org", '["h2"]', "chrome"))
            cfg = dict(staged.execute("SELECT key,value FROM settings"))
            self.assertEqual(cfg["webBasePath"], "/test-panel/")
            self.assertEqual(cfg["webListen"], "127.0.0.1")
            self.assertEqual(cfg["subURI"], "https://origin.example.org/sub/")
        self.assertEqual((self.folder/"render/etc/xupdate/tls/origin.key").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.folder/"render/x-ui.db").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.folder/"render/var/www/xupdate").stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.folder/"render/var/www/xupdate/index.html").stat().st_mode & 0o777, 0o644)

    def test_validation_config_excludes_disabled_clients(self):
        self.render()
        config = json.loads((self.folder/"render/core-validation.json").read_text())
        self.assertEqual([c["email"] for c in config["inbounds"][0]["settings"]["clients"]], ["test-1"])
        self.assertNotIn("externalProxy", config["inbounds"][0]["streamSettings"])

    def test_rejects_certificate_for_different_hostname(self):
        with self.assertRaisesRegex(ConfigError, "does not cover"):
            self.render(domain="different.example.org")

    def test_rejects_mismatched_key(self):
        other = self.folder/"other.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
                        "-out", str(other)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.stream["tlsSettings"]["certificates"][0]["key"] = other.read_text().splitlines()
        self.edit_stream()
        with self.assertRaisesRegex(ConfigError, "does not match"):
            self.render()

    def test_rejects_different_transport(self):
        self.stream["network"] = "xhttp"
        self.edit_stream()
        with self.assertRaisesRegex(ConfigError, "conversion is not performed"):
            self.render()

    def test_rejects_existing_render_folder(self):
        (self.folder/"render").mkdir()
        with self.assertRaisesRegex(ConfigError, "already exists"):
            self.render()

    def test_rejects_port_collision(self):
        with self.assertRaisesRegex(ConfigError, "must differ"):
            inspect(self.source, backend_port=8144)

    def test_rejects_nginx_route_injection(self):
        self.stream["grpcSettings"]["serviceName"] = "sample; return 200;"
        self.edit_stream()
        with self.assertRaises(ConfigError):
            self.render()

    def test_rejects_management_route_overlap(self):
        self.stream["grpcSettings"]["serviceName"] = "test-panel"
        self.edit_stream()
        with self.assertRaisesRegex(ConfigError, "overlap"):
            self.render()

    def test_rejects_reserved_website_route(self):
        self.stream["grpcSettings"]["serviceName"] = "assets"
        self.edit_stream()
        with self.assertRaisesRegex(ConfigError, "reserved"):
            self.render()


if __name__ == "__main__":
    unittest.main()
