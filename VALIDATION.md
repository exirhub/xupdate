# Validation record — 2026-09-25

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
| Nine health diagnostic tests: individual service checks, refused ports, timeout, protocol/TLS errors, panel/public failures, and success | Passed with simulated services and network probes |
| Eleven cloud bootstrap tests: fresh install, repeat startup, existing-panel guard, explicit clean mode, APT failures, seed corruption, commit pinning, installer failure, download retries, concurrent execution, and embedded payload | Passed with a local Git fixture and simulated APT/installer; no host services or packages changed |
| Complete Python test suite after cloud deployment additions | Passed: 39 tests |
| Generated cloud-config compared with the standalone bootstrap | Exact match; 7,328 bytes, below EC2's 16 KiB raw user-data limit |
| Cloud-config YAML parse, embedded Bash content, permission/owner fields, and runcmd arguments | Passed with PyYAML; `write_files` and `runcmd` field types also reviewed against the upstream cloud-init schema |
| Real first boot on each documented cloud provider | Not run; provider instructions checked against official documentation |
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

## Cloud deployment scope

`cloud-init/xupdate.yaml` embeds `scripts/bootstrap.sh` and invokes it once through cloud-init's final-stage user script. Provider Bash startup fields and SSH installations use the same script. The tests execute its actual Git checkout, checksum, lock, and cleanup logic against temporary fixtures; APT and the inner installer are simulated. They do not provision cloud resources or establish provider-specific network connectivity. The cloud-init executable is unavailable in this build environment, so no claim is made of a live cloud-init module run.

The bootstrap accepts an optional source commit and explicit clean-install flag, skips an existing completed installation before downloads, records a successful source commit, and propagates failed installation exit codes. It leaves DNS, SSH, network configuration, and firewall policy to the existing image and provider setup. The supplied root database still has Git blob SHA `1d014b4e1736f77f7661d0dc7c9e86cb6a4ad3e6`.
