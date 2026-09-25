#!/usr/bin/env bash
# Read-only checks; does not restart services or change network/database settings.
set -uo pipefail
if [[ "$EUID" != 0 ]]; then
    echo "Run with sudo: sudo bash scripts/diagnose.sh" >&2
    exit 1
fi
failed=0
if command -v cloud-init >/dev/null 2>&1; then
    cloud-init status --long || failed=1
fi
if [[ -f /var/lib/xupdate-bootstrap/source-commit.txt ]]; then
    printf 'Last successful bootstrap source commit: '
    cat /var/lib/xupdate-bootstrap/source-commit.txt
fi
for host in github.com security.ubuntu.com deb.debian.org; do
    printf 'DNS lookup: %s\n' "$host"
    timeout 15 getent ahosts "$host" || failed=1
done
if id _apt >/dev/null 2>&1; then
    printf 'APT user resolver access: '
    if runuser -u _apt -- test -r /etc/resolv.conf; then
        echo readable
    else
        echo unreadable
        failed=1
    fi
fi
systemctl status x-ui.service xupdate-nginx.service --no-pager -l || failed=1
ss -lntp '( sport = :80 or sport = :443 or sport = :10001 or sport = :8144 or sport = :2096 )' || failed=1
if [[ -x /usr/local/bin/xupdate && -f /etc/xupdate/installed.json ]]; then
    /usr/local/bin/xupdate doctor || failed=1
else
    echo "The installed XUPDATE command or installation state is missing."
    failed=1
fi
for log in /var/log/xupdate-bootstrap.log /var/log/cloud-init-output.log; do
    if [[ -f "$log" ]]; then
        printf 'Recent output: %s\n' "$log"
        tail -n 40 "$log"
    fi
done
journalctl -u x-ui.service -u xupdate-nginx.service -n 60 --no-pager -o cat || failed=1
exit "$failed"
