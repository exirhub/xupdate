# Validation record — 2026-09-24

This records checks actually performed while preparing XUPDATE 0.1.0. It is not a claim that a destination server has been deployed.

| Check | Result |
| --- | --- |
| Supplied SQLite export `quick_check` | Passed |
| Private bundle seed compared byte-for-byte with the supplied file | Passed |
| Repository root `x-ui.db` compared byte-for-byte with the supplied file | Passed |
| Default database selection with no `--db` override | Verified with the bundled seed |
| Input file SHA-256 before/after rendering | Unchanged |
| Working profile's client identity linked to the supplied enabled inbound | Confirmed |
| gRPC service name, authority, and multi-mode settings | Unchanged |
| Embedded certificate and private key public components | Match |
| Certificate covers `exirhub.site` and is currently valid | Passed; expires 2041-09-20 |
| Every row in 18 non-migration tables | Identical between the input and staged database |
| Inbound accounting, client settings, tag, ID, remark, sniffing | Preserved |
| Ten automated import/certificate/routing tests using synthetic data | Passed |
| Five clean-install tests with temporary files and simulated systemd | Passed |
| Live TCP port check rejects an active listener and permits immediate reuse after connection shutdown | Passed |
| Clean removal preserves the bundled seed, does not follow CLI symlinks, and creates no backup | Passed in the cleanup tests |
| Port-conflict/stop-failure checks prevent removal of previous files | Passed with simulated systemd |
| Three package-bootstrap tests: transient DNS error, package-download error, and success | Passed with simulated APT; failures stop continuation |
| Python source parsing | Passed |
| Bash syntax check | Passed |
| JavaScript syntax check | Passed |
| Tailwind production stylesheet build | Passed |
| Browser visual and interaction checks | Not completed; local Chromium could not start |
| Nginx syntax/runtime test | Not run here; Nginx binary unavailable |
| Pinned Xray binary configuration test | Not run here; release binary unavailable |
| systemd installation, live subscription export, and rollback | Not run on a destination server |
| Cloudflare path and authenticated VLESS traffic | Not tested from this environment |
| DNS repair on the destination server | Not run here; documented commands require execution on the server |

The installer runs `nginx -t`, the pinned core's `run -test`, certificate checks, port checks, and local service readiness checks on the destination. Failure after new installation begins removes its managed files and services. Normal mode retains database backups; explicitly selected clean mode creates no backup and does not restore the previous panel. Real systemd deletion and installation have not been exercised end-to-end in this build environment.

Only these existing inbound columns differ in the staged runtime copy: `listen`, `port`, `stream_settings`, `share_addr_strategy`, and `share_addr`. A public Host record and management listener/URL settings are added or updated. The input database is never replaced.

Before production use, verify a generated subscription and use the supplied client profile to open real traffic through the new server and Cloudflare. Monitor core, Nginx, and Cloudflare logs during sustained use. The status of a static health endpoint alone cannot establish transport stability.
