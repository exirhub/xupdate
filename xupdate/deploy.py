"""Fresh or explicitly clean installation, operational checks, and owned-file removal."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import subprocess
import tarfile
import tempfile
import time
import urllib.request

from .core import (ConfigError, check_routes, grpc_route, nginx_config, parse_json,
                   prepare, read_db,
                   settings, snapshot, write_private)

OWNED = (
    "/etc/systemd/system/x-ui.service",
    "/etc/systemd/system/xupdate-nginx.service",
    "/etc/systemd/system/xupdate-refresh.service",
    "/etc/systemd/system/xupdate-refresh.timer",
    "/usr/local/bin/xupdate",
    "/usr/local/x-ui", "/etc/x-ui", "/etc/xupdate",
    "/opt/xupdate", "/var/www/xupdate", "/var/lib/xupdate",
)
STATE = Path("/etc/xupdate/installed.json")
CLEAN_UNITS = ("xupdate-refresh.timer", "xupdate-refresh.service", "xupdate-nginx.service", "x-ui.service")
CLEAN_PATHS = OWNED + (
    "/usr/bin/x-ui", "/usr/local/bin/x-ui",
    "/usr/lib/systemd/system/x-ui.service", "/lib/systemd/system/x-ui.service",
    "/etc/systemd/system/x-ui.service.d",
    "/usr/lib/systemd/system/x-ui.service.d", "/lib/systemd/system/x-ui.service.d",
    "/run/systemd/system/x-ui.service", "/run/systemd/system/x-ui.service.d",
    "/etc/systemd/system/xupdate-nginx.service.d",
    "/etc/systemd/system/xupdate-refresh.service.d",
    "/etc/systemd/system/xupdate-refresh.timer.d",
    "/var/log/x-ui", "/var/log/xupdate", "/etc/logrotate.d/x-ui",
)

def command(args, *, cwd=None, env=None, timeout=90):
    r = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, timeout=timeout)
    if r.returncode:
        raise ConfigError(f"{Path(str(args[0])).name} failed (exit {r.returncode}); inspect the service journal locally.")
    return r.stdout.decode(errors="replace")

def atomic_file(path: Path, data: str, mode=0o600):
    fd, temp = tempfile.mkstemp(prefix="."+path.name+".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def nginx_capabilities():
    r = subprocess.run(["nginx", "-V"], capture_output=True, text=True, timeout=15)
    output = r.stdout + r.stderr
    match = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", output)
    if r.returncode or not match:
        raise ConfigError("Unable to identify the Nginx build.")
    version = tuple(map(int, match.groups()))
    if version < (1, 20, 0) or "--with-http_v2_module" not in output or "--with-http_ssl_module" not in output:
        raise ConfigError("Nginx >=1.20 with HTTP/2 and SSL modules is required.")
    return version >= (1, 25, 1), socket.has_ipv6 and Path("/proc/net/if_inet6").exists()

def available_ports(ports):
    for port in ports:
        for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
            if family == socket.AF_INET6 and not socket.has_ipv6:
                continue
            try:
                with socket.socket(family, socket.SOCK_STREAM) as s:
                    # Recently stopped x-ui connections may leave TIME_WAIT sockets.
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    if family == socket.AF_INET6:
                        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    s.bind((address, port))
            except OSError as e:
                if family == socket.AF_INET6 and e.errno in (97, 99):
                    continue
                raise ConfigError(f"TCP port {port} is already in use; nothing was installed.") from e

def archive_arch():
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    if not arch:
        raise ConfigError("This release supports amd64 and arm64.")
    return arch

def download_release(project: Path, stage: Path, offline: Path | None):
    lock = json.loads((project/"upstream.lock.json").read_text())
    arch = archive_arch()
    asset = lock["assets"][arch]
    target = stage/asset["file"]
    if offline:
        shutil.copyfile(offline, target)
    else:
        url = f'https://github.com/{lock["repository"]}/releases/download/{lock["version"]}/{asset["file"]}'
        for attempt in range(1, 6):
            print(f"Downloading verified 3x-ui {lock['version']} ({attempt}/5)...", flush=True)
            r = subprocess.run(["curl", "--fail", "--show-error", "--location",
                "--connect-timeout", "15", "--max-time", "600", "--output", str(target), url],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode == 0 and target.is_file() and target.stat().st_size:
                break
            if attempt == 5:
                raise ConfigError("The 3x-ui archive could not be downloaded.")
            time.sleep(min(attempt*2, 8))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != asset["sha256"]:
        raise ConfigError("The release archive SHA-256 does not match upstream.lock.json.")
    dest = stage/"release"
    dest.mkdir(mode=0o700)
    with tarfile.open(target, "r:gz") as archive:
        members = archive.getmembers()
        if sum(m.size for m in members) > 1024**3:
            raise ConfigError("Unexpectedly large upstream archive.")
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ConfigError("Unsafe member in the upstream archive.")
            output = dest/name
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, output.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                os.chmod(output, 0o755 if member.mode & 0o111 else 0o644)
    release = dest/"x-ui"
    xray = release/"bin"/f"xray-linux-{arch}"
    if not (release/"x-ui").is_file() or not xray.is_file():
        raise ConfigError("The archive lacks the expected panel or core binary.")
    os.chmod(release/"x-ui", 0o755)
    os.chmod(xray, 0o755)
    return release, xray, lock["version"]

def core_test(xray: Path, config: Path):
    env = dict(os.environ, XRAY_LOCATION_ASSET=str(xray.parent))
    command([str(xray), "run", "-test", "-config", str(config)],
            cwd=xray.parent, env=env, timeout=60)

def check_assets(config: Path, assets: Path):
    raw = config.read_text()
    needed = set(re.findall(r"ext:([A-Za-z0-9_.-]+):", raw))
    for builtin in ("geoip", "geosite"):
        if builtin + ":" in raw:
            needed.add(builtin+".dat")
    missing = sorted(name for name in needed if not (assets/name).is_file())
    if missing:
        raise ConfigError("The release lacks required routing assets: " + ", ".join(missing))

def unit_files():
    return {
"x-ui.service": """[Unit]
Description=3x-ui managed by XUPDATE
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=180
StartLimitBurst=10

[Service]
Type=simple
WorkingDirectory=/usr/local/x-ui
Environment=XUI_DB_FOLDER=/etc/x-ui
Environment=XUI_LOG_FOLDER=/var/log/x-ui
Environment=XRAY_VMESS_AEAD_FORCED=false
ExecStart=/usr/local/x-ui/x-ui
ExecReload=/bin/kill -USR1 $MAINPID
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
UMask=0077

[Install]
WantedBy=multi-user.target
""",
"xupdate-nginx.service": """[Unit]
Description=XUPDATE HTTPS website and transport gateway
After=network-online.target x-ui.service
Wants=network-online.target x-ui.service

[Service]
Type=simple
ExecStartPre=/usr/sbin/nginx -t -c /etc/xupdate/nginx.conf
ExecStart=/usr/sbin/nginx -c /etc/xupdate/nginx.conf -g "daemon off;"
ExecReload=/usr/sbin/nginx -t -c /etc/xupdate/nginx.conf
ExecReload=/bin/kill -HUP $MAINPID
ExecStop=/bin/kill -QUIT $MAINPID
KillMode=mixed
TimeoutStopSec=65
Restart=on-failure
RestartSec=3
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
""",
"xupdate-refresh.service": """[Unit]
Description=Refresh XUPDATE routes after supported panel edits
After=x-ui.service xupdate-nginx.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/xupdate refresh
UMask=0077
""",
"xupdate-refresh.timer": """[Unit]
Description=Check XUPDATE managed route changes

[Timer]
OnBootSec=90s
OnUnitActiveSec=60s
RandomizedDelaySec=5s
Unit=xupdate-refresh.service

[Install]
WantedBy=timers.target
"""
    }

def certificate_der():
    return ssl.PEM_cert_to_DER_cert(Path("/etc/xupdate/tls/origin.pem").read_text())

def origin_connection(plan, alpn):
    # Exact certificate pinning on the local origin also supports Cloudflare Origin CA.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.set_alpn_protocols([alpn])
    raw = socket.create_connection(("127.0.0.1", 443), timeout=8)
    try:
        connection = context.wrap_socket(raw, server_hostname=plan["domain"])
        if connection.getpeercert(binary_form=True) != certificate_der():
            connection.close()
            raise ConfigError("Local HTTPS certificate does not match the imported certificate.")
        return connection
    except Exception:
        raw.close()
        raise

def origin_http(plan, path):
    with origin_connection(plan, "http/1.1") as conn:
        conn.sendall(f'GET {path} HTTP/1.1\r\nHost: {plan["domain"]}\r\nConnection: close\r\n\r\n'.encode())
        response = http.client.HTTPResponse(conn)
        response.begin()
        body = response.read(65536)
        return response.status, body

def recv_exact(conn, count):
    result = b""
    while len(result) < count:
        part = conn.recv(count-len(result))
        if not part:
            raise ConfigError("The HTTP/2 backend closed before its SETTINGS frame.")
        result += part
    return result

@contextmanager
def health_stage(label):
    """Name the failed probe without exposing response bodies or credentials."""
    try:
        yield
    except ConfigError as error:
        raise ConfigError(f"{label}: {error}") from error
    except ConnectionRefusedError as error:
        raise ConfigError(f"{label}: connection refused; check the listener and service journal.") from error
    except (TimeoutError, subprocess.TimeoutExpired) as error:
        raise ConfigError(f"{label}: probe timed out.") from error
    except ssl.SSLError as error:
        raise ConfigError(f"{label}: TLS negotiation or certificate verification failed.") from error
    except (OSError, http.client.HTTPException) as error:
        raise ConfigError(f"{label}: {type(error).__name__}; inspect the service journal.") from error

def health(plan, public=False):
    # is-active with multiple units succeeds when ANY unit is active.
    for unit in ("x-ui", "xupdate-nginx"):
        with health_stage(f"service {unit}"):
            command(["systemctl", "is-active", "--quiet", unit])
    with health_stage("frontend TLS (xupdate-nginx, 127.0.0.1:443)"):
        with origin_connection(plan, "h2") as conn:
            if conn.selected_alpn_protocol() != "h2":
                raise ConfigError("The frontend did not negotiate h2.")
    with health_stage(f'Xray gRPC backend (127.0.0.1:{plan["backend_port"]})'):
        with socket.create_connection(("127.0.0.1", plan["backend_port"]), timeout=8) as conn:
            conn.sendall(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"+bytes.fromhex("000000040000000000"))
            header = recv_exact(conn, 9)
            if header[3] != 4 or header[5:9] != b"\0\0\0\0":
                raise ConfigError("The backend did not provide an HTTP/2 SETTINGS frame.")
    with health_stage("local gateway HTTPS (127.0.0.1:443)"):
        status, body = origin_http(plan, "/healthz")
        if status != 200 or body != b"ok\n":
            raise ConfigError(f"Gateway health response is invalid (HTTP {status}).")
    with health_stage("website HTTPS (127.0.0.1:443)"):
        status, body = origin_http(plan, "/")
        if status != 200 or b"XUPDATE" not in body:
            raise ConfigError(f"Website response is invalid (HTTP {status}).")
    with health_stage(f'panel route (HTTPS 443 -> 127.0.0.1:{plan["panel_port"]})'):
        status, body = origin_http(plan, plan["panel_path"])
        if status not in (200, 301, 302, 303, 307, 308):
            raise ConfigError(f"The panel route returned HTTP {status}.")
    if public:
        with health_stage("public HTTPS /healthz"):
            with urllib.request.urlopen("https://"+plan["domain"]+"/healthz", timeout=15) as r:
                if r.status != 200 or r.read(64) != b"ok\n":
                    raise ConfigError(f"Public health response is invalid (HTTP {r.status}).")
    return {"services": "active", "origin_tls_pin": "matched", "frontend_alpn": "h2",
            "backend": "h2c", "website": "ok", "panel": "ok",
            "public_cdn": "checked" if public else "not checked",
            "authenticated_vless_end_to_end": "not tested"}

def clean_previous_installation(ports):
    """Remove only known x-ui/XUPDATE paths, after validation and a port check."""
    states = {}
    for unit in CLEAN_UNITS:
        result = subprocess.run(
            ["systemctl", "show", unit, "--property=LoadState", "--property=ActiveState"],
            capture_output=True, text=True, timeout=30)
        props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if props.get("LoadState") == "not-found":
            continue
        if result.returncode or not props.get("LoadState"):
            raise ConfigError(f"Unable to inspect {unit}; previous files were not removed.")
        states[unit] = props
    stopped = []
    try:
        for unit in states:
            command(["systemctl", "stop", unit])
            stopped.append(unit)
        # A separately managed web server must not cause deletion of a usable panel.
        available_ports(ports)
    except BaseException:
        for unit in reversed(stopped):
            if states[unit].get("ActiveState") in ("active", "activating", "reloading"):
                subprocess.run(["systemctl", "start", unit], capture_output=True, timeout=45)
        raise
    print("Removing the previous x-ui/XUPDATE installation without creating a backup...", flush=True)
    for unit in states:
        # Static or masked units may not support disable; their exact files are removed below.
        subprocess.run(["systemctl", "disable", unit], capture_output=True, timeout=30)
    for value in CLEAN_PATHS:
        path = Path(value)
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    command(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "reset-failed", *CLEAN_UNITS], capture_output=True, timeout=30)

def cleanup_owned(created, backup: Path | None):
    subprocess.run(["systemctl", "disable", "--now", "xupdate-refresh.timer", "xupdate-nginx", "x-ui"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    current = Path("/etc/x-ui/x-ui.db")
    if backup is not None and current.is_file():
        snapshot(current, backup/("before-rollback-"+str(time.time_ns())+".db"))
    for value in reversed(created):
        if value not in OWNED:
            raise ConfigError("The rollback list contains a path not owned by XUPDATE.")
        path = Path(value)
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    subprocess.run(["systemctl", "daemon-reload"], capture_output=True)

def install(project: Path, source: Path, *, domain="", advertised="", backend_port=10001,
            offline=None, clean_install=False):
    if os.geteuid() != 0 or not Path("/run/systemd/system").is_dir():
        raise ConfigError("Installation requires root on a systemd server.")
    if STATE.is_file() and not clean_install:
        return health(json.loads(STATE.read_text())["plan"])
    occupied = [p for p in OWNED if Path(p).exists() or Path(p).is_symlink()]
    if occupied and not clean_install:
        raise ConfigError("Existing installation found. Use --clean-install to remove it without backup. Paths: " + ", ".join(occupied))
    if clean_install:
        checkout = project.resolve()
        for value in CLEAN_PATHS:
            path = Path(value)
            if checkout == path or path in checkout.parents:
                raise ConfigError("Run clean installation from a checkout outside the old installation paths.")
    modern, ipv6 = nginx_capabilities()
    created = []
    backup = None
    with tempfile.TemporaryDirectory(prefix="xupdate-", dir="/var/tmp") as tmp:
        stage = Path(tmp)
        prepared = stage/"prepared"
        plan = prepare(source, prepared, project, domain=domain, advertised=advertised,
                       backend_port=backend_port, modern=modern, ipv6=ipv6)
        ports = [80, 443, plan["backend_port"], plan["panel_port"], plan["subscription_port"]]
        if not clean_install:
            available_ports(ports)
        release, xray, version = download_release(project, stage, offline)
        check_assets(prepared/"core-validation.json", xray.parent)
        core_test(xray, prepared/"core-validation.json")
        command(["nginx", "-t", "-c", str(prepared/"nginx.preview.conf")])
        if clean_install:
            clean_previous_installation(ports)
        else:
            backup = Path("/var/backups/xupdate")/time.strftime("%Y%m%d-%H%M%S")
            backup.mkdir(parents=True, mode=0o700)
            os.chmod(backup.parent, 0o700)
            shutil.copy2(prepared/"original.db", backup/"original.db")
            shutil.copy2(prepared/"plan.json", backup/"plan.json")
        try:
            def directory(path):
                created.append(path)
                Path(path).mkdir(parents=True, mode=0o700)
            directory("/etc/xupdate")
            directory("/etc/x-ui")
            directory("/var/lib/xupdate")
            created.append("/usr/local/x-ui")
            shutil.copytree(release, "/usr/local/x-ui")
            shutil.copy2(prepared/"x-ui.db", "/etc/x-ui/x-ui.db")
            os.chmod("/etc/x-ui/x-ui.db", 0o600)
            shutil.copytree(prepared/"etc/xupdate/tls", "/etc/xupdate/tls")
            for file in ("nginx.conf", "access.txt"):
                shutil.copy2(prepared/file, Path("/etc/xupdate")/file)
            created.append("/var/www/xupdate")
            shutil.copytree(prepared/"var/www/xupdate", "/var/www/xupdate")
            for directory_path in ("var/log/xupdate", "var/log/x-ui", "var/lib/xupdate/nginx/client",
                                   "var/lib/xupdate/nginx/proxy"):
                Path("/"+directory_path).mkdir(parents=True, exist_ok=True, mode=0o755)
            import pwd
            worker = pwd.getpwnam("www-data")
            for path in ("/var/lib/xupdate", "/var/lib/xupdate/nginx",
                         "/var/lib/xupdate/nginx/client", "/var/lib/xupdate/nginx/proxy"):
                os.chmod(path, 0o750)
                os.chown(path, 0, worker.pw_gid)
            for path in ("/var/lib/xupdate/nginx/client", "/var/lib/xupdate/nginx/proxy"):
                os.chown(path, worker.pw_uid, worker.pw_gid)
            created.append("/opt/xupdate")
            shutil.copytree(project, "/opt/xupdate",
                ignore=shutil.ignore_patterns(".git", "node_modules", "private", "build", "preview",
                                             "__pycache__", "*.db", "*.zip", "*.tar.gz"))
            created.append("/usr/local/bin/xupdate")
            write_private(Path("/usr/local/bin/xupdate"), '#!/bin/sh\ncd /opt/xupdate || exit 1\nexec python3 -m xupdate "$@"\n', 0o755)
            for filename, contents in unit_files().items():
                path = "/etc/systemd/system/"+filename
                created.append(path)
                write_private(Path(path), contents, 0o644)
            state = {"version": "0.1.0", "panel_version": version, "plan": plan,
                     "backup": str(backup) if backup else None, "clean_install": clean_install,
                     "owned": created.copy(), "modern_nginx": modern, "ipv6": ipv6}
            write_private(STATE, json.dumps(state, indent=2)+"\n")
            command(["systemctl", "daemon-reload"])
            command(["systemctl", "enable", "--now", "x-ui"])
            command(["systemctl", "enable", "--now", "xupdate-nginx"])
            last_error = None
            for attempt in range(25):
                try:
                    result = health(plan)
                    actual = Path("/usr/local/x-ui/bin/config.json")
                    if not actual.is_file():
                        raise ConfigError("The panel has not produced its runtime core configuration.")
                    core_test(Path("/usr/local/x-ui/bin")/xray.name, actual)
                    last_error = None
                    break
                except (ConfigError, OSError, http.client.HTTPException) as error:
                    last_error = error
                    time.sleep(2)
            if last_error:
                raise ConfigError("Service readiness failed; removing the incomplete new installation.") from last_error
            command(["systemctl", "enable", "--now", "xupdate-refresh.timer"])
            print("Panel URL is recorded privately in /etc/xupdate/access.txt.")
            return result
        except BaseException:
            cleanup_owned(created, backup)
            if backup:
                print("Managed changes rolled back. Database copies remain in "+str(backup), flush=True)
            else:
                print("The incomplete installation was removed. Clean mode created no backup of the previous installation.", flush=True)
            raise

def state_read():
    if not STATE.is_file():
        raise ConfigError("XUPDATE is not installed.")
    return json.loads(STATE.read_text())

def refresh():
    if os.geteuid() != 0:
        raise ConfigError("Route refresh requires root.")
    state = state_read()
    plan = copy.deepcopy(state["plan"])
    db = read_db(Path("/etc/x-ui/x-ui.db"))
    try:
        row = db.execute("SELECT * FROM inbounds WHERE id=?", (plan["inbound_id"],)).fetchone()
        if row is None or not row["enable"]:
            raise ConfigError("The managed inbound is missing or disabled.")
        stream = parse_json(row["stream_settings"], "stream_settings")
        if (row["listen"] != "127.0.0.1" or row["port"] != plan["backend_port"]
            or stream.get("security") != "none" or stream.get("network") != plan["network"]):
            raise ConfigError("The managed inbound's backend contract changed; restore its loopback settings.")
        cfg = settings(db)
        if cfg.get("webListen") != "127.0.0.1" or cfg.get("subListen") != "127.0.0.1":
            raise ConfigError("Panel and subscription listeners must stay on loopback.")
        if cfg.get("webCertFile") or cfg.get("webKeyFile") or cfg.get("subCertFile") or cfg.get("subKeyFile"):
            raise ConfigError("Management TLS belongs at Nginx; restore empty internal certificate paths.")
        plan["route"] = grpc_route(stream.get("grpcSettings", {}))
        if cfg.get("webBasePath", "").rstrip("/")+"/" != plan["panel_path"]:
            raise ConfigError("Changing the managed panel base path requires a reviewed route update.")
        all_paths = [plan["route"], plan["panel_path"], *plan["subscription_paths"]]
        check_routes(all_paths)
        if int(cfg.get("webPort", "0")) != plan["panel_port"] or int(cfg.get("subPort", "0")) != plan["subscription_port"]:
            raise ConfigError("Internal panel/subscription ports changed.")
    finally:
        db.close()
    config = Path("/etc/xupdate/nginx.conf")
    new = nginx_config(plan, modern=state["modern_nginx"], ipv6=state["ipv6"])
    old = config.read_text()
    if new == old:
        return {"changed": False}
    candidate = Path("/etc/xupdate/nginx.next.conf")
    atomic_file(candidate, new)
    try:
        command(["nginx", "-t", "-c", str(candidate)])
        atomic_file(config, new)
        try:
            command(["systemctl", "reload", "xupdate-nginx"])
        except Exception:
            atomic_file(config, old)
            command(["systemctl", "reload", "xupdate-nginx"])
            raise
        state["plan"] = plan
        atomic_file(STATE, json.dumps(state, indent=2)+"\n")
    finally:
        candidate.unlink(missing_ok=True)
    return {"changed": True, "transport": plan["network"]}

def rollback():
    if os.geteuid() != 0:
        raise ConfigError("Rollback requires root.")
    state = state_read()
    backup = Path(state["backup"]) if state.get("backup") else None
    if backup:
        backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    cleanup_owned(state["owned"], backup)
    return {"rolled_back": True, "database_backup": str(backup) if backup else None,
            "note": "Managed services removed; OS packages and logs retained. Clean mode does not restore the previous installation."}
