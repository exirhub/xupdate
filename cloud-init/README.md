# Cloud and datacenter deployment

[راهنمای فارسی](README.fa.md)

Use a standard **Ubuntu 24.04+ or Debian 12+**, **amd64 or arm64** image with systemd. Cloud-init deployment additionally requires a cloud-init-enabled image and a provider that delivers user data to it. The same database, domain, certificate, VLESS/gRPC Multi profile, and pinned 3x-ui release are used on every provider.

## Files to use

| File | Purpose |
| --- | --- |
| [`xupdate.yaml`](xupdate.yaml) | Complete cloud-config for the provider's User Data / Cloud config field |
| [`../scripts/bootstrap.sh`](../scripts/bootstrap.sh) | Standalone Bash startup script; also works over SSH |
| [`../scripts/diagnose.sh`](../scripts/diagnose.sh) | Read-only installation, DNS, listener, service, and log checks |
| [`../scripts/render-cloud-init.py`](../scripts/render-cloud-init.py) | Maintainer tool that embeds the Bash script into the YAML |

The YAML is generated from the exact same bootstrap script. There are no provider IP addresses, interface names, gateways, SSH keys, or API credentials to fill in. Provider network and account initialization remains in charge of those settings. The payload is checked against EC2's 16 KiB raw user-data limit.

## First-boot installation

1. Create a server using a supported distribution image and your usual SSH access settings.
2. Paste the **entire** [`xupdate.yaml`](xupdate.yaml), including `#cloud-config`, into the cloud-config/user-data field. Do not paste YAML into a field that expects a Bash startup script; use `scripts/bootstrap.sh` there.
3. Allow the instance to finish initialization. Connect with SSH and check:

```bash
sudo cloud-init status --wait --long
sudo tail -n 80 /var/log/xupdate-bootstrap.log
sudo xupdate doctor
sudo cat /etc/xupdate/access.txt
```

Run `cloud-init status --wait` from your SSH session, never inside user data: waiting for cloud-init from its own final-stage script would deadlock it. Some images have additional vendor initialization, so inspect both the bootstrap log and cloud-init status when one reports failure.

Bootstrap installs download prerequisites with strict APT error handling and package-lock waiting, fetches the selected Git revision with bounded retries, verifies `x-ui.db.sha256`, and invokes the normal installer. The installer verifies the pinned upstream release and performs local readiness checks. It does not switch Cloudflare DNS or test an authenticated client connection.

## Provider mapping

These are documented provisioning paths, **not a claim of live testing in every datacenter**. Region, plan, image ID, SSH key, network, and firewall choices belong to the account creating the instance.

| Provider / product | Where to supply the file | File / detail |
| --- | --- | --- |
| Hetzner Cloud | Create server → **Cloud config** | `xupdate.yaml`; choose a standard OS image |
| OVHcloud Public Cloud / compatible OpenStack | Creation-time user data; OpenStack server creation supports `--user-data` | `xupdate.yaml`; this is separate from OVH VPS and dedicated-server installation workflows |
| DigitalOcean Droplets | Additional Options → **Startup scripts**; `doctl` also accepts `--user-data-file` | `xupdate.yaml`; the chosen image must consume cloud-init user data |
| Vultr Cloud Compute | **Enable Cloud-Init User-Data** during deployment | `xupdate.yaml` on a supported Linux image |
| Akamai / Linode | **Add user data** through the Metadata service | `xupdate.yaml`; use a supported image and region. For an existing StackScript workflow, use `bootstrap.sh` |
| AWS EC2 | Advanced details → **User data** | `xupdate.yaml` on Ubuntu/Debian; paste plain text with the already-base64-encoded option off. Amazon Linux is outside this installer's OS support |
| Microsoft Azure Linux VM | **Custom data** on a cloud-init-enabled image; Azure CLI supports `--custom-data` | `xupdate.yaml` on Ubuntu/Debian |
| Google Compute Engine | **Startup script**, metadata key `startup-script` | `bootstrap.sh`, not YAML. With gcloud, the file option is `--metadata-from-file=startup-script=scripts/bootstrap.sh` on instance creation |
| RamNode, OVH VPS/dedicated, Contabo, Netcup, other VPS/dedicated providers | SSH after a supported OS is installed; use user data only if that product/image explicitly supports it | Use the standalone command below. A provider-specific cloud-init field is not assumed |

On Compute Engine, startup scripts can run again on subsequent boots. The default bootstrap recognizes an existing XUPDATE installation and exits without reinstalling it; its message says **skipped**, not healthy. Use `xupdate doctor` to check health. Do not add `--clean-install` to a recurring startup script.

## Standalone installation or retry after a failed first boot

This works on a supported server regardless of whether its provider offers cloud-init. If curl is absent, install `ca-certificates` and `curl` with APT first.

```bash
curl -fL --retry 5 --connect-timeout 15 --max-time 180 \
  https://raw.githubusercontent.com/exirhub/xupdate/main/scripts/bootstrap.sh \
  -o /tmp/xupdate-bootstrap.sh && sudo bash /tmp/xupdate-bootstrap.sh
```

Alternatively, from an existing checkout:

```bash
sudo bash scripts/bootstrap.sh
```

A completed XUPDATE deployment is skipped before downloads or package installation. An existing x-ui directory without completed XUPDATE state causes a clear stop. For an **intentional replacement without backup**, invoke this manually:

```bash
sudo bash scripts/bootstrap.sh --clean-install
```

The destructive work remains inside the existing installer, after its normal staging checks. Bootstrap itself does not remove the old panel. It does not clear cloud-init state, reboot the VM, rewrite DNS/Netplan/SSH settings, change firewall rules, or start the distribution's separate Nginx service.

## Select a reproducible source revision

Default source is the repository's `main` branch. To pin the revision from a checkout, run:

```bash
sudo bash scripts/bootstrap.sh --ref "$(git rev-parse HEAD)"
```

For cloud-init, replace the final `main` argument in the YAML's `runcmd` with the full commit SHA you selected. For a Bash startup script, set `XUPDATE_REF` before invoking it, or change its default revision. The bootstrap code itself comes from the file you submitted; download that file from the same commit when pinning the complete provisioning payload. A successful installation records its source commit at `/var/lib/xupdate-bootstrap/source-commit.txt`.

Retries are bounded; persistent DNS, package-repository, or GitHub connectivity failures require fixing the reported error and rerunning the bootstrap. `git pull` alone does not upgrade the installed copy under `/opt/xupdate`, and this bootstrap is an installer, not a live deployment updater.

## Network controls and Cloudflare

| Connection | Requirement |
| --- | --- |
| Inbound origin HTTPS | TCP 443 reachable from Cloudflare through provider and host firewalls |
| Optional HTTP redirect | TCP 80 |
| Administration | Your configured SSH port and access policy |
| Package/source downloads | DNS resolution and outbound access to the configured APT mirrors, GitHub, and GitHub release assets |
| Internal services | Xray 10001, panel 8144, subscription 2096 stay on loopback |

Use the provider's firewall/security-group controls and the existing host firewall. Origin reachability requires a public address or a separately configured route reachable by Cloudflare; attaching this script to a private-only VM does not provide that route. Standard dual-stack or IPv4 connectivity is simplest; on IPv6-only servers, dependency downloads also need working reachability to every upstream endpoint.

Point the proxied `exirhub.site` record to the new **origin** IP, enable Cloudflare gRPC, and use Full (strict). `188.114.97.6` is the client profile's Cloudflare edge IP, not an origin address. Because deployments share the supplied domain/certificate/database, adding several origin records is an intentional multi-origin design decision, not a bootstrap step.

Then run `sudo xupdate doctor --public` and test real traffic with the existing VLESS/gRPC client. Read the root README for the exact profile and public-test limits.

## Diagnostics and maintenance

From a checkout:

```bash
sudo bash scripts/diagnose.sh
```

The read-only script reports cloud-init state when available, DNS and `_apt` resolver-file access, service status, expected listeners, the installed doctor's result, and recent logs. It does not repair settings automatically. Exit status is nonzero if a check fails; a completed local health check does not prove external Cloudflare or client connectivity.

When changing the bootstrap implementation, regenerate and verify the cloud-config:

```bash
python3 scripts/render-cloud-init.py
python3 scripts/render-cloud-init.py --check
python3 -m unittest discover -s tests -v
bash -n scripts/bootstrap.sh
bash -n scripts/diagnose.sh
```

## Provider references

Checked on 2026-09-25:

- [cloud-init configuration schema](https://github.com/canonical/cloud-init/blob/main/cloudinit/config/schemas/schema-cloud-config-v1.json)
- [Hetzner Cloud server creation](https://docs.hetzner.com/cloud/servers/getting-started/creating-a-server/)
- [OVHcloud Public Cloud creation-time scripts](https://help.ovhcloud.com/csm/en-au-public-cloud-compute-launch-script-at-instance-creation?id=kb_article_view&sysparm_article=KB0038632)
- [DigitalOcean user data](https://docs.digitalocean.com/products/droplets/how-to/provide-user-data/)
- [Vultr cloud-init user data](https://docs.vultr.com/how-to-deploy-a-vultr-server-with-cloudinit-userdata)
- [Akamai/Linode user data](https://techdocs.akamai.com/cloud-computing/docs/add-user-data-when-deploying-a-compute-instance)
- [EC2 user data and size limit](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html)
- [Azure cloud-init support](https://learn.microsoft.com/en-us/azure/virtual-machines/linux/using-cloud-init)
- [Compute Engine Linux startup scripts](https://docs.cloud.google.com/compute/docs/instances/startup-scripts/linux)
