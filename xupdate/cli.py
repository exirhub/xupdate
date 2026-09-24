from __future__ import annotations
import argparse
import fcntl
import http.client
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from .core import ConfigError, inspect, prepare, public_summary
from . import deploy

def main():
    project = Path(__file__).resolve().parent.parent
    defaults = json.loads((project/"deployment-defaults.json").read_text())
    bundled_db = project/"x-ui.db"
    if not bundled_db.is_file() and (project/"private/x-ui.db").is_file():
        bundled_db = project/"private/x-ui.db"
    p = argparse.ArgumentParser(prog="xupdate")
    commands = p.add_subparsers(dest="action", required=True)
    for name in ("inspect", "render", "install"):
        sub = commands.add_parser(name)
        sub.add_argument("--db", type=Path, default=bundled_db)
        sub.add_argument("--domain", default=defaults.get("domain", ""))
        sub.add_argument("--public-address", default=defaults.get("public_address", ""))
        sub.add_argument("--backend-port", type=int, default=defaults.get("backend_port", 10001))
        if name == "render":
            sub.add_argument("--output", type=Path, required=True)
            sub.add_argument("--legacy-nginx", action="store_true")
        if name == "install":
            sub.add_argument("--archive", type=Path, help="Offline verified 3x-ui release archive")
            sub.add_argument("--clean-install", action="store_true",
                             help="Remove the previous x-ui/XUPDATE installation without backup")
    doc = commands.add_parser("doctor")
    doc.add_argument("--public", action="store_true", help="Also probe the real proxied hostname")
    commands.add_parser("refresh")
    commands.add_parser("rollback")
    args = p.parse_args()
    os.umask(0o077)
    try:
        if args.action in ("install", "refresh", "rollback") and os.geteuid() == 0:
            operation_lock = open("/run/lock/xupdate-operation.lock", "a")
            try:
                fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ConfigError("Another XUPDATE operation is active.") from error
        if args.action in ("inspect", "render", "install"):
            kw = dict(domain=args.domain, advertised=args.public_address, backend_port=args.backend_port)
            if args.action == "inspect":
                result = public_summary(inspect(args.db, **kw))
            elif args.action == "render":
                result = public_summary(prepare(args.db, args.output, project,
                                               modern=not args.legacy_nginx, **kw))
            else:
                result = deploy.install(project, args.db, offline=args.archive,
                                        clean_install=args.clean_install, **kw)
        elif args.action == "doctor":
            result = deploy.health(deploy.state_read()["plan"], public=args.public)
        elif args.action == "refresh":
            result = deploy.refresh()
        else:
            result = deploy.rollback()
        print(json.dumps(result, indent=2))
        return 0
    except (ConfigError, OSError, ValueError, KeyError, sqlite3.Error,
            http.client.HTTPException, subprocess.TimeoutExpired) as error:
        if isinstance(error, ConfigError):
            message = str(error)
        else:
            message = f"{type(error).__name__}: operation failed; no secret-bearing detail was printed."
        print("XUPDATE: "+message, file=sys.stderr)
        return 1
