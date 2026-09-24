#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--dry-run" ]]; then
    shift
    cd "$project_dir"
    exec python3 -m xupdate render "$@"
fi
if [[ "$EUID" -ne 0 ]]; then
    echo "Run with sudo on an Ubuntu 24.04+/Debian 12+ systemd server." >&2
    exit 1
fi
if [[ ! -d /run/systemd/system ]]; then
    echo "A running systemd server is required." >&2
    exit 1
fi
exec 9>/run/lock/xupdate-install.lock
flock -n 9 || { echo "Another XUPDATE installation is active." >&2; exit 1; }
if [[ -f /etc/xupdate/installed.json ]]; then
    exec /usr/local/bin/xupdate doctor
fi
for item in /etc/x-ui /usr/local/x-ui /etc/xupdate /opt/xupdate /var/www/xupdate; do
    if [[ -e "$item" ]]; then
        echo "Fresh-server installation only; existing path: $item" >&2
        exit 1
    fi
done
. /etc/os-release
case "${ID:-}" in
    ubuntu|debian) ;;
    *) echo "Ubuntu or Debian is required." >&2; exit 1 ;;
esac
nginx_was_present=0
command -v nginx >/dev/null 2>&1 && nginx_was_present=1
if [[ "$nginx_was_present" == 1 ]] && systemctl is-enabled --quiet nginx; then
    echo "An existing enabled Nginx service needs a reviewed migration." >&2
    exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 update
apt-get -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 install -y \
    ca-certificates curl python3 openssl nginx iproute2
if [[ "$nginx_was_present" == 0 ]]; then
    systemctl disable --now nginx
fi
cd "$project_dir"
exec python3 -m xupdate install "$@"

