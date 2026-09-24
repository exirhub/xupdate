"""Read-only inspection and deterministic deployment generation."""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time
import uuid

class ConfigError(RuntimeError):
    pass

def write_private(path: Path, data: str | bytes, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data.encode() if isinstance(data, str) else data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(path, mode)

def read_db(path: Path):
    path = path.resolve(strict=True)
    if path.read_bytes()[:16] != b"SQLite format 3\x00":
        raise ConfigError("The input is not an SQLite database.")
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA trusted_schema=OFF")
    if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        db.close()
        raise ConfigError("SQLite integrity check failed.")
    return db

def settings(db):
    return dict(db.execute("SELECT key,value FROM settings"))

def parse_json(raw, label):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"{label} is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a JSON object.")
    return value

def hostname(value: str) -> str:
    value = value.lower().rstrip(".")
    if len(value) > 253 or not re.fullmatch(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value
    ):
        raise ConfigError("A plain DNS hostname is required.")
    return value

def public_address(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
        if not address.is_global:
            raise ConfigError("The advertised address must be public.")
        return str(address)
    except ValueError:
        return hostname(value)

def route_path(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"/[A-Za-z0-9_./-]+", value):
        raise ConfigError(f"{label} contains unsupported path characters.")
    if ".." in value or "//" in value or value == "/":
        raise ConfigError(f"{label} must be a non-root, unambiguous path.")
    return value.rstrip("/") + "/"

def grpc_route(transport):
    service = transport.get("serviceName", "")
    if not isinstance(service, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", service):
        raise ConfigError("A conventional gRPC serviceName is required.")
    return route_path("/" + service + "/", "gRPC service path")

def check_routes(paths):
    if any(a.startswith(b) or b.startswith(a) for i, a in enumerate(paths) for b in paths[i+1:]):
        raise ConfigError("Panel, subscription, and transport routes overlap.")
    for forbidden in ("/assets/", "/healthz/", "/journal/"):
        if any(forbidden.startswith(p) or p.startswith(forbidden) for p in paths):
            raise ConfigError("An application route overlaps a reserved website route.")

def run_checked(args, *, data=None, cwd=None):
    result = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd, timeout=45)
    if result.returncode:
        # Do not echo a potentially secret-bearing tool response.
        raise ConfigError(f"{Path(str(args[0])).name} failed validation (exit {result.returncode}).")
    return result.stdout

def extract_certificate(stream, cert_dir: Path, domain: str):
    certs = stream.get("tlsSettings", {}).get("certificates", [])
    if len(certs) != 1:
        raise ConfigError("This installer expects one origin certificate per inbound.")
    pair = certs[0]
    def pem(field):
        value = pair.get(field, [])
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            value = "\n".join(value)
        if not isinstance(value, str) or "-----BEGIN " not in value:
            raise ConfigError("Certificate and key must be embedded in the database.")
        return value.rstrip() + "\n"
    cert_path, key_path = cert_dir / "origin.pem", cert_dir / "origin.key"
    write_private(cert_path, pem("certificate"), 0o644)
    write_private(key_path, pem("key"))
    cert_pub_pem = run_checked(["openssl", "x509", "-in", str(cert_path), "-pubkey", "-noout"])
    cert_pub = run_checked(["openssl", "pkey", "-pubin", "-outform", "DER"], data=cert_pub_pem)
    key_pub = run_checked(["openssl", "pkey", "-in", str(key_path), "-pubout", "-outform", "DER"])
    if cert_pub != key_pub:
        raise ConfigError("The private key does not match the certificate.")
    match = run_checked(["openssl", "x509", "-in", str(cert_path), "-noout", "-checkhost", domain])
    # OpenSSL x509 may exit successfully even when -checkhost reports a mismatch.
    if f"Hostname {domain} does match certificate" not in match.decode():
        raise ConfigError("The origin certificate does not cover the configured hostname.")
    run_checked(["openssl", "x509", "-in", str(cert_path), "-noout", "-checkend", "86400"])
    dates = run_checked(["openssl", "x509", "-in", str(cert_path),
                         "-noout", "-startdate", "-enddate"]).decode()
    parsed = {}
    for line in dates.splitlines():
        label, value = line.split("=", 1)
        parsed[label] = dt.datetime.strptime(value, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
    if parsed["notBefore"] > dt.datetime.now(dt.timezone.utc):
        raise ConfigError("The origin certificate is not yet valid.")
    return {"key_matches": True, "expires": parsed["notAfter"].isoformat()}

def inspect(path: Path, domain: str = "", advertised: str = "", backend_port: int = 10001):
    if not 1024 <= backend_port <= 65535:
        raise ConfigError("Backend port must be between 1024 and 65535.")
    db = read_db(path)
    try:
        required = {"inbounds", "clients", "client_inbounds", "hosts", "settings", "users"}
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= tables:
            raise ConfigError("A normalized 3x-ui database with Hosts support is required.")
        rows = list(db.execute("SELECT * FROM inbounds WHERE enable=1"))
        if len(rows) != 1:
            raise ConfigError("Version 0.1 requires exactly one enabled local inbound.")
        row = dict(rows[0])
        if row.get("node_id") not in (None, 0) or row["port"] != 443:
            raise ConfigError("The enabled inbound must be local and use public port 443.")
        if row["protocol"] != "vless":
            raise ConfigError("This release preserves VLESS gRPC.")
        stream = parse_json(row["stream_settings"], "stream_settings")
        network = stream.get("network", stream.get("method"))
        if network != "grpc" or stream.get("security") != "tls":
            raise ConfigError("The source transport must be gRPC/TLS; conversion is not performed.")
        transport = stream.get(network + "Settings", {})
        if not isinstance(transport, dict):
            raise ConfigError("Transport settings must be an object.")
        candidate = domain or transport.get("authority") or transport.get("host") or stream.get("tlsSettings", {}).get("serverName", "")
        domain = hostname(candidate)
        advertised = public_address(advertised or domain)
        path_prefix = grpc_route(transport)
        cfg = settings(db)
        panel_path = route_path(cfg.get("webBasePath", ""), "Panel base path")
        sub_paths = []
        for enable, key, default in (
            ("subEnable", "subPath", "/sub/"),
            ("subJsonEnable", "subJsonPath", "/json/"),
            ("subClashEnable", "subClashPath", "/clash/"),
        ):
            if cfg.get(enable, "true" if enable == "subEnable" else "false").lower() == "true":
                sub_paths.append(route_path(cfg.get(key, default), key))
        paths = [panel_path, path_prefix, *sub_paths]
        check_routes(paths)
        panel_port = int(cfg.get("webPort", "8144"))
        sub_port = int(cfg.get("subPort", "2096"))
        if len({backend_port, panel_port, sub_port, 80, 443}) != 5:
            raise ConfigError("Frontend, backend, panel, and subscription ports must differ.")
        if not all(1024 <= p <= 65535 for p in (panel_port, sub_port)):
            raise ConfigError("Panel and subscription ports must be unprivileged.")
        if db.execute("SELECT count(*) FROM hosts WHERE inbound_id=?", (row["id"],)).fetchone()[0]:
            raise ConfigError("Existing Host records require a reviewed migration; none were changed.")
        counts = {table: db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                  for table in ("clients", "users", "client_inbounds", "client_traffics", "api_tokens")}
        linked = db.execute("SELECT count(*) FROM client_inbounds WHERE inbound_id=?", (row["id"],)).fetchone()[0]
        if linked < 1:
            raise ConfigError("No normalized clients are linked to the inbound.")
        fp = stream.get("tlsSettings", {}).get("settings", {}).get("fingerprint", "chrome")
        if fp not in ("chrome", "safari", "firefox", "edge", "random", "randomized"):
            raise ConfigError("Unsupported fingerprint in the import profile.")
        return {
            "inbound_id": row["id"], "tag": row["tag"], "network": network,
            "domain": domain, "public_address": advertised, "public_port": 443,
            "backend_port": backend_port, "route": path_prefix,
            "panel_port": panel_port, "panel_path": panel_path,
            "subscription_port": sub_port, "subscription_paths": sub_paths,
            "fingerprint": fp, "multi_mode": bool(transport.get("multiMode", False)),
            "counts": counts, "linked_clients": linked,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    finally:
        db.close()

def public_summary(plan):
    return {k:v for k,v in plan.items() if k not in
            {"panel_path", "subscription_paths", "source_sha256"}}

def snapshot(source: Path, target: Path):
    if target.exists():
        raise ConfigError("A snapshot destination already exists.")
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    src = read_db(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.chmod(target, 0o600)

def set_setting(db, key, value):
    rows = db.execute("SELECT id FROM settings WHERE key=? ORDER BY id", (key,)).fetchall()
    if rows:
        db.execute("UPDATE settings SET value=? WHERE key=?", (str(value), key))
    else:
        db.execute("INSERT INTO settings (key,value) VALUES (?,?)", (key, str(value)))

def transform_database(target: Path, plan):
    db = sqlite3.connect(target)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")
        row = dict(db.execute("SELECT * FROM inbounds WHERE id=?", (plan["inbound_id"],)).fetchone())
        stream = parse_json(row["stream_settings"], "stream_settings")
        stream["security"] = "none"
        # TLS keys move to private Nginx files; advertised TLS comes from Host overrides.
        stream.pop("tlsSettings", None)
        endpoint = {
            "dest": plan["public_address"], "port": 443, "forceTls": "tls",
            "sni": plan["domain"], "alpn": ["h2"], "fingerprint": plan["fingerprint"],
            "remark": row["remark"]
        }
        stream["externalProxy"] = [endpoint]
        db.execute("UPDATE inbounds SET listen=?,port=?,stream_settings=?,share_addr_strategy=?,share_addr=? WHERE id=?",
                   ("127.0.0.1", plan["backend_port"], json.dumps(stream, separators=(",", ":")),
                    "custom", plan["public_address"], plan["inbound_id"]))
        host = {
            "group_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "https://" + plan["domain"] + plan["route"])),
            "inbound_id": plan["inbound_id"], "sort_order": 0, "remark": row["remark"],
            "server_description": "XUPDATE public endpoint", "is_disabled": 0, "is_hidden": 0,
            "tags": '["XUPDATE"]', "address": plan["public_address"], "port": 443,
            "security": "tls", "sni": plan["domain"], "host_header": plan["domain"],
            "path": "", "alpn": '["h2"]', "fingerprint": plan["fingerprint"],
            "override_sni_from_address": 0, "keep_sni_blank": 0,
            "pinned_peer_cert_sha256": "[]", "verify_peer_cert_by_name": "",
            "allow_insecure": 0, "ech_config_list": "", "mux_params": "", "sockopt_params": "",
            "final_mask": "", "vless_route": "", "exclude_from_sub_types": "[]",
            "mihomo_ip_version": "", "mihomo_x25519": 0, "shuffle_host": 0, "node_guids": "[]",
            "created_at": int(time.time()*1000), "updated_at": int(time.time()*1000)
        }
        columns = {r[1] for r in db.execute("PRAGMA table_info(hosts)")}
        if not set(host) <= columns:
            raise ConfigError("The database Host schema is incompatible with the pinned panel.")
        keys = list(host)
        sql = 'INSERT INTO hosts (' + ",".join('"' + k + '"' for k in keys) + ') VALUES (' + ",".join("?" for _ in keys) + ')'
        db.execute(sql, [host[k] for k in keys])
        changes = {
            "webListen": "127.0.0.1", "webDomain": plan["domain"],
            "webCertFile": "", "webKeyFile": "", "webPort": plan["panel_port"],
            "subListen": "127.0.0.1", "subDomain": plan["domain"],
            "subCertFile": "", "subKeyFile": "", "subPort": plan["subscription_port"]
        }
        for key, default in (("subPath", "/sub/"), ("subJsonPath", "/json/"), ("subClashPath", "/clash/")):
            cfg = settings(db)
            path = cfg.get(key, default)
            if path in plan["subscription_paths"]:
                changes[key.replace("Path","URI")] = "https://" + plan["domain"] + path
                changes[key] = path
        for key, value in changes.items():
            set_setting(db, key, value)
        db.commit()
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ConfigError("The staged database failed integrity validation.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def build_core_validation(db_path: Path):
    db = read_db(db_path)
    try:
        template = parse_json(settings(db)["xrayTemplateConfig"], "xrayTemplateConfig")
        for row in db.execute("SELECT * FROM inbounds WHERE enable=1"):
            stream = parse_json(row["stream_settings"], "stream_settings")
            stream.pop("externalProxy", None)
            inbound_settings = parse_json(row["settings"], "inbound settings")
            users = []
            for c in db.execute(
                "SELECT c.uuid,c.email,c.flow,c.enable,ci.flow_override FROM clients c "
                "JOIN client_inbounds ci ON c.id=ci.client_id WHERE ci.inbound_id=?", (row["id"],)
            ):
                if not c["enable"]:
                    continue
                item = {"id": c["uuid"], "email": c["email"], "level": 0}
                flow = c["flow_override"] if c["flow_override"] is not None else c["flow"]
                if flow:
                    item["flow"] = flow
                users.append(item)
            inbound_settings["clients"] = users
            inbound_settings.pop("encryption", None)
            template.setdefault("inbounds", []).append({
                "listen": row["listen"], "port": row["port"], "protocol": row["protocol"],
                "tag": row["tag"], "settings": inbound_settings, "streamSettings": stream,
                "sniffing": parse_json(row["sniffing"], "sniffing")
            })
        return template
    finally:
        db.close()

def nginx_config(plan, prefix=Path("/"), modern=True, ipv6=True):
    def p(value):
        result = prefix / value.lstrip("/")
        if any(x in str(result) for x in ('"', "\n", "\r", "$", ";", "{", "}")):
            raise ConfigError("Unsupported deployment path.")
        return '"' + str(result) + '"'
    h2 = "http2 on;" if modern else ""
    listen = "listen 443 ssl;" if modern else "listen 443 ssl http2;"
    listen6 = ("listen [::]:443 ssl;" if modern else "listen [::]:443 ssl http2;") if ipv6 else ""
    http6 = "listen [::]:80;" if ipv6 else ""
    def app_location(path, port):
        return f'''
        location = {path.rstrip("/")} {{
            return 308 https://{plan["domain"]}{path};
        }}
        location ^~ {path} {{
            proxy_pass http://127.0.0.1:{port};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $xupdate_connection;
            proxy_connect_timeout 10s;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
            proxy_buffering off;
            proxy_cache off;
            client_max_body_size 32m;
            add_header Cache-Control "no-store" always;
        }}
'''
    apps = app_location(plan["panel_path"], plan["panel_port"])
    for path in plan["subscription_paths"]:
        apps += app_location(path, plan["subscription_port"])
    return f'''# Generated by XUPDATE. Regenerate with xupdate refresh.
user www-data;
worker_processes auto;
worker_rlimit_nofile 65536;
pid {p("/run/xupdate-nginx.pid")};
error_log {p("/var/log/xupdate/nginx-error.log")} warn;

events {{
    worker_connections 4096;
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    client_body_temp_path {p("/var/lib/xupdate/nginx/client")};
    proxy_temp_path {p("/var/lib/xupdate/nginx/proxy")};
    map $http_upgrade $xupdate_connection {{
        default upgrade;
        "" close;
    }}
    log_format xupdate escape=json
        '{{"time":"$time_iso8601","peer":"$remote_addr","cf_ray":"$http_cf_ray",'
        '"status":"$status","protocol":"$server_protocol",'
        '"upstream":"$upstream_status","duration":"$request_time"}}';
    access_log {p("/var/log/xupdate/nginx-access.log")} xupdate buffer=64k flush=5s;
    server_tokens off;
    sendfile on;
    tcp_nodelay on;
    gzip off;
    client_header_timeout 15s;
    client_header_buffer_size 4k;
    large_client_header_buffers 4 16k;
    # http2_max_header_size is obsolete; use large_client_header_buffers.
    http2_max_concurrent_streams 128;
    keepalive_timeout 75s;
    keepalive_requests 1000;
    keepalive_time 1h;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:XUPDATE:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    server {{
        listen 80;
        {http6}
        server_name {plan["domain"]};
        return 308 https://{plan["domain"]}$request_uri;
    }}

    server {{
        {listen}
        {listen6}
        {h2}
        server_name {plan["domain"]};
        ssl_certificate {p("/etc/xupdate/tls/origin.pem")};
        ssl_certificate_key {p("/etc/xupdate/tls/origin.key")};
        root {p("/var/www/xupdate")};
        index index.html;

        grpc_connect_timeout 10s;
        grpc_read_timeout 3600s;
        grpc_send_timeout 3600s;
        grpc_socket_keepalive on;
        grpc_next_upstream off;
        grpc_intercept_errors off;
        grpc_set_header Host $host;
        grpc_set_header Connection "";
        grpc_set_header TE trailers;
        grpc_set_header X-Forwarded-Proto https;

        location ^~ {plan["route"]} {{
            client_max_body_size 0;
            client_body_timeout 3600s;
            send_timeout 3600s;
            add_header Cache-Control "no-store" always;
            grpc_pass grpc://127.0.0.1:{plan["backend_port"]};
        }}
{apps}
        location = /healthz {{
            access_log off;
            default_type text/plain;
            return 200 "ok\\n";
        }}
        location ^~ /assets/ {{
            add_header Cache-Control "public, max-age=3600";
            try_files $uri =404;
        }}
        location ~ /\\. {{
            deny all;
        }}
        location / {{
            try_files $uri $uri/ =404;
            add_header X-Content-Type-Options nosniff always;
            add_header Referrer-Policy strict-origin-when-cross-origin always;
        }}
    }}
}}
'''

def prepare(source: Path, output: Path, project: Path, *, domain="", advertised="",
            backend_port=10001, modern=True, ipv6=True):
    if output.exists():
        raise ConfigError("Render directory already exists; use a new directory.")
    plan = inspect(source, domain, advertised, backend_port)
    output.mkdir(parents=True, mode=0o700)
    original, target = output/"original.db", output/"x-ui.db"
    snapshot(source, original)
    snapshot(original, target)
    db = read_db(original)
    try:
        stream = parse_json(db.execute("SELECT stream_settings FROM inbounds WHERE id=?",
                                      (plan["inbound_id"],)).fetchone()[0], "stream_settings")
    finally:
        db.close()
    plan["certificate"] = extract_certificate(stream, output/"etc/xupdate/tls", plan["domain"])
    transform_database(target, plan)
    for path in ("var/log/xupdate", "var/lib/xupdate/nginx/client",
                 "var/lib/xupdate/nginx/proxy", "run"):
        (output/path).mkdir(parents=True, exist_ok=True)
    shutil.copytree(project/"website", output/"var/www/xupdate",
                    ignore=shutil.ignore_patterns("src"))
    # A private archive extraction umask must not hide public assets from www-data.
    web_root = output/"var/www/xupdate"
    for path in [web_root, *web_root.rglob("*")]:
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    write_private(output/"nginx.preview.conf", nginx_config(plan, output, modern, ipv6))
    write_private(output/"nginx.conf", nginx_config(plan, Path("/"), modern, ipv6))
    write_private(output/"plan.json", json.dumps(plan, indent=2)+"\n")
    write_private(output/"core-validation.json", json.dumps(build_core_validation(target), indent=2)+"\n")
    write_private(output/"access.txt", f'Panel: https://{plan["domain"]}{plan["panel_path"]}\n'
                  f'Transport: {plan["network"]} / TLS / 443\n'
                  "Existing panel credentials and client identities are preserved.\n")
    if hashlib.sha256(source.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ConfigError("The source file changed during rendering; no deployment was performed.")
    return plan
