#!/usr/bin/env bash
# Sourced by install.sh; keep dependency failures ahead of destructive cleanup.
xupdate_install_dependencies() {
    if ! DEBIAN_FRONTEND=noninteractive apt-get \
        -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 --error-on=any update; then
        cat >&2 <<'MESSAGE'
APT repository refresh failed. Dependency installation and x-ui cleanup have not started.
If APT reported "Temporary failure resolving", fix the server's DNS first.
See "APT / DNS troubleshooting" in README.md or the DNS section in README.fa.md.
For other APT errors, fix the reported repository or network problem before retrying.
MESSAGE
        return 1
    fi
    if ! DEBIAN_FRONTEND=noninteractive apt-get \
        -o DPkg::Lock::Timeout=120 -o Acquire::Retries=3 install -y \
        ca-certificates curl python3 openssl nginx iproute2; then
        cat >&2 <<'MESSAGE'
APT dependency installation failed. XUPDATE has not started x-ui cleanup.
Fix the package or network error shown above, then rerun the same install command.
MESSAGE
        return 1
    fi
}
