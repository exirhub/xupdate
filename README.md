# XUPDATE

A standalone installer for the supplied 3x-ui database, preserving its **VLESS / gRPC Multi / TLS / 443** public connection profile. Nginx serves an HTML5/Tailwind website and forwards the existing gRPC service to a loopback Xray inbound. The old `xrm-1` project is only an installation reference; this project does not access or alter it during installation.

## Install from GitHub

The supplied database is included as `x-ui.db` at the repository root. The installer uses it automatically:

```bash
git clone https://github.com/exirhub/xupdate.git
cd xupdate
sudo bash install.sh
```

The bundled `x-ui.db` is a byte-for-byte copy of `57.128.162.236_2026-09-24_171935.db`, published at the owner's explicit request with its existing embedded certificate, key, accounts, and settings. Check its checksum with `sha256sum -c x-ui.db.sha256`. The installer opens this seed read-only and prepares a separate runtime copy. See [the Persian guide](README.fa.md) and [the validation record](VALIDATION.md).

## Requirements and alternative database

Use Ubuntu 24.04+ or Debian 12+ with systemd, amd64 or arm64, and outbound access to the distribution package repositories and GitHub release downloads. Existing x-ui installations can be removed with the clean-install option below.

To use a different local database, override the bundled file explicitly:

```bash
sudo bash install.sh --db /root/x-ui.db
```

Previously downloaded installation bundles with `private/x-ui.db` remain supported: that file is used when the root `x-ui.db` is absent. The earlier source-only archive predates the bundled database and still needs `--db`.

The installer pins 3x-ui **v3.8.5** and verifies the upstream archive SHA-256 from `upstream.lock.json`. It extracts the official binaries without executing an upstream remote installation script. It installs the required OS packages and its own systemd units.

## Clean installation over an existing panel

If `/etc/x-ui` already exists, run these commands from the checkout:

```bash
git pull --ff-only
sudo bash install.sh --clean-install
```

This explicitly deletes the previous x-ui/XUPDATE installation and creates **no database backup**. The replacement uses the repository's bundled `x-ui.db`, or the file selected with `--db`. Previous server accounts and settings are removed with the old database.

The installer first prepares the supplied database, verifies the release and core configuration, and checks Nginx syntax. It then stops the known x-ui/XUPDATE services and checks the required ports before removing standard installation directories, service units/drop-ins, old CLI wrappers, and x-ui/XUPDATE logs. The source checkout and bundled database must be outside those installation directories. A separate Nginx service or unrelated process is not removed; a port conflict stops cleanup before old files are deleted.

Clean mode also works when only a leftover `/etc/x-ui` directory exists. If installation fails after deletion, incomplete new files are cleaned up; the previous panel is not restored. `xupdate rollback` after a clean installation removes the new deployment without creating a database backup. Earlier backups already on the server are not deleted.

## Exact deployment profile

| Setting | Value |
| --- | --- |
| Public address advertised to clients | `188.114.97.6` |
| TLS SNI and gRPC authority | `exirhub.site` |
| Public TLS port / ALPN | `443` / `h2` |
| Protocol / transport | `VLESS` / `gRPC` |
| Service / mode | `google.internal.analytics.v1.Tracker` / `multi` |
| Client fingerprint metadata | `chrome` |
| Nginx gRPC upstream | `grpc://127.0.0.1:10001` |
| Panel listener | `127.0.0.1:8144` |
| Subscription listener | `127.0.0.1:2096` |

The database's existing panel path, login, client UUIDs, subscription IDs, quotas, counters, and routing template remain intact. Read the private panel URL after installation:

```bash
sudo cat /etc/xupdate/access.txt
```

The public address above is the Cloudflare edge address from the working client profile; it is **not** the new server's origin IP. In Cloudflare, the proxied DNS record for `exirhub.site` must point to the new server. Keep gRPC enabled and the origin TLS mode at Full (strict). The installer does not change Cloudflare DNS, WAF settings, firewall rules, or the existing server. Enable inbound TCP 443, and optionally 80 for redirects, through your server's network controls. Verify connectivity before switching production DNS.

## What changes in the runtime copy

The input file is opened read-only and remains untouched. The installer creates a separate SQLite snapshot for `/etc/x-ui/x-ui.db` and changes only the fields required for the frontend:

1. The existing inbound listens on `127.0.0.1:10001` using gRPC/h2c. Nginx terminates origin TLS on 443 using the same embedded certificate and private key, extracted into protected files.
2. A panel Host record and external-proxy metadata advertise the original public TLS endpoint, so generated links do not expose the internal port or downgrade clients to plaintext.
3. Panel and subscription HTTP listeners move to loopback. Their existing routes are forwarded through HTTPS by Nginx. Public subscription URLs use `https://exirhub.site`.

No new inbound is created. No transport conversion, client replacement, key generation, credential reset, or traffic reset occurs. The original inbound ID, service name, authority, multi-mode setting, and remark remain as supplied. A misleading display name containing `XHTTP` is left intact; it does not determine the transport.

TLS between Nginx and the core is unnecessary on the same host's loopback interface. Client-to-Cloudflare and Cloudflare-to-origin connections still use TLS. The original key is stored at `/etc/xupdate/tls/origin.key` with mode `0600`. Normal installation backups live in `/var/backups/xupdate/`; clean mode creates no backup.

## Preview, operate, and recover

Render an isolated migration preview without installing packages or changing services:

```bash
bash install.sh --dry-run --output /root/xupdate-preview
```

The output contains a private staged database, generated Nginx configurations, a core validation configuration, extracted certificate files, and a migration plan. Choose a new output directory each time. Do not publish that directory.

```bash
sudo xupdate doctor
sudo xupdate doctor --public
sudo systemctl status x-ui xupdate-nginx
sudo journalctl -u x-ui -u xupdate-nginx --since '10 minutes ago'
```

`doctor` checks service state, the exact local TLS certificate, ALPN `h2`, the backend HTTP/2 SETTINGS response, the website, and the panel route. `--public` additionally checks the HTTPS `/healthz` endpoint through public DNS. This is not an authenticated end-to-end VLESS traffic test; verify that with the existing client profile after DNS is ready.

`xupdate-refresh.timer` checks the managed gRPC service route every minute and validates Nginx before a supported route change is reloaded. Clients must receive a matching service name if you change it. Keep the inbound's loopback address, internal port, and TLS-off backend setting. Panel base path/port changes, new inbounds, and domain or certificate changes require a reviewed configuration update. Routine client additions, removals, quotas, and traffic accounting remain panel operations.

Rollback removes the installation's managed services and files. Normal installations first save the current runtime database; clean installations skip that backup. OS packages and logs are retained:

```bash
sudo xupdate rollback
```

For a release archive already present on the server:

```bash
sudo bash install.sh --archive /root/x-ui-linux-amd64.tar.gz
```

The archive must match the pinned version and detected architecture. SHA-256 verification is still mandatory.

## Protocol behavior and limits

Nginx uses `grpc_pass` to send HTTP/2 to the gRPC backend. Sending ordinary HTTP/1.1 proxy traffic to that socket is a protocol error; a binary HTTP/2 SETTINGS frame must not be parsed as an HTTP/1 response. The one-hour gRPC read/send timeouts are inactivity limits at Nginx, not overrides of Cloudflare limits. Header sizing uses `large_client_header_buffers`; the obsolete `http2_max_header_size` directive is intentionally absent.

A 521 response requires investigation of origin availability, TLS, and network reachability. A timeout change cannot guarantee its removal. Likewise, application `Connecting` loops alone do not prove WAF or rate limiting; correlate client/core errors with Cloudflare events and Nginx logs.

Nginx receives Cloudflare's origin-side TLS connection, not the client's original TLS handshake. The `chrome` fingerprint remains client metadata; this project does not claim native Nginx uTLS/JA4 validation. The website is served consistently to browsers and crawlers. This architecture provides ordinary HTTPS website and gRPC routing; it does not guarantee invisibility to DPI or Cloudflare.

## Development and verification

Deployment uses Python's standard library and a prebuilt stylesheet. Node.js is needed only to rebuild the website CSS:

```bash
npm ci
npm run build:css
python3 -m unittest discover -s tests -v
bash -n install.sh
```

Tests use the supplied database's schema with synthetic rows and temporary test certificates. They verify preservation, public Host overrides, certificate mismatches, route collisions, and rejection of transport conversion. Clean-install tests use temporary directories and simulated systemd calls to verify deletion scope, port-conflict handling, and absence of backups. See `VALIDATION.md` for performed and outstanding checks.

## Sources

- [3x-ui v3.8.5](https://github.com/MHSanaei/3x-ui/releases/tag/v3.8.5)
- [3x-ui Host subscription implementation](https://github.com/MHSanaei/3x-ui/blob/v3.8.5/internal/sub/host_sub.go)
- [Nginx gRPC module](https://nginx.org/en/docs/http/ngx_http_grpc_module.html)
- [Nginx HTTP/2 module](https://nginx.org/en/docs/http/ngx_http_v2_module.html)
- [Cloudflare gRPC requirements](https://developers.cloudflare.com/network/grpc-connections/)
- [Cloudflare 521 troubleshooting](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-521/)

3x-ui and its bundled components retain their upstream licenses. Tailwind CSS is MIT-licensed; its build dependencies are pinned in `package-lock.json`. Upstream binaries are downloaded during installation; the root database is the owner's supplied export.
