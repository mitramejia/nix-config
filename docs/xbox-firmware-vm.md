# Official Xbox firmware maintenance VM

Home Manager packages `xbox-firmware-vm` on NixOS. This is a **manual-boundary
wizard**, not unattended flashing: Windows
installation/licensing/sign-in, physical USB actions and Xbox Accessories remain
human steps. It never clicks Update, downloads firmware separately, captures
credentials or bypasses Windows requirements. No system rebuild is performed by
the launcher.

## Start from zero

After installing the Home Manager configuration normally, run as your regular
desktop user in a real terminal:

```sh
xbox-firmware-vm dry-run       # no changes, no sudo
xbox-firmware-vm --help
xbox-firmware-vm wizard
# Optional separate private directory; NEVER point at an existing unrelated VM:
xbox-firmware-vm wizard "$HOME/.local/share/my-xbox-maintenance"
```

Requires x86_64 Linux, accessible `/dev/kvm` (kvm group membership), systemd/logind,
working user-session libvirt/KVM, sufficient RAM/storage, sudo and a graphical
desktop. Packages include libvirt, QEMU, swtpm, Microsoft-key OVMF, virt-viewer and
desktop open/notify tools; no dependency on a particular window manager. The
launcher uses **qemu:///session**, not system libvirt. It does not enable system
libvirtd. A pre-existing session daemon may need restarting **only when no VMs or
maintenance sessions are running** if it cannot find newly installed QEMU/swtpm.
Failure to start the VM is not permission to bypass Secure Boot/TPM checks.

The five stages:

1. Automatically select the current **consumer Windows 11 multi-edition x64**
   ISO, English (United States), on [Microsoft's download page][iso]. A fresh,
   sandboxed headless Chromium session performs the ordinary edition/language
   selections and reads the matching **Verify download** publisher SHA256. No
   copy/paste, hardcoded edition/SKU IDs, mirror or third-party hash. The
   browser blocks requests/redirects outside HTTPS Microsoft subdomains and
   Microsoft's Ajax CDN before navigation; unsupported browser rules fail closed.
   The ISO downloader accepts only the two official Microsoft download hosts and checks
   every redirect before following it. SHA256 is mandatory before VM creation.
   Expiring signed links are not persisted or printed. Microsoft restrictions,
   missing hashes, ambiguous media and schema changes fail closed; no CAPTCHA,
   automation-detection, network-location or access restriction bypass is used.
2. Create/start the isolated owned VM and viewer. Complete Windows/OOBE, updates
   and legitimate licensing manually. In **Windows**, open Win+R:
   `ms-windows-store://pdp/?ProductId=9NBLGGH30XJ3`. Install official **Xbox
   Accessories**, publisher Microsoft Corporation. Do not start Update yet.
3. Choose the exact serial and directly connected physical port. Consent to
   dedicate that socket exclusively. The root guard refuses other xpad users or
   connected xpad devices, inhibits xpad autoload temporarily, unloads **only
   xpad**, and grants per-new-node ACLs on the exact full PCI/sysfs path. Unplug
   fully for ten seconds while xpad is absent; the launcher adds a physical-port
   QMP capture while disconnected, then asks you to reconnect. Restoring xpad
   before QEMU captures was a proven failure mode and is deliberately avoided.
4. Prove **another physical unplug/reconnect** is automatically recaptured with
   no attach/ACL intervention and recognized by Accessories. Require generation
   >=3 (initial node, cold reconnect, reconnect test), exact serial, xpad absent
   and all controller interfaces usbfs-owned. Record the current full firmware
   version. New VMs have a packaged read-only **XBOX_TOOLS** CD containing
   `guest-tools.cmd` and `guest-awake.ps1`: inspect them in Windows and explicitly
   run the command file to open the official Store listing and show the awake
   command. No autorun, guest-agent execution or security-policy changes.
   Run the reviewed awake script in Windows PowerShell with your consent.
   Existing VMs are never redefined; without the disc, transfer the printed
   packaged helper yourself.
   Keep that **same window/thread** running. It uses SetThreadExecutionState,
   checks failure and restores thread-scoped flags on exit, not permanent power
   preferences. Do not bypass execution policy; stop if protection cannot run.
5. Arm **FLASH-ACTIVE before clicking Update**. Follow only the official app.
   Verify explicit success **and reread full version/no-update status**; 100%,
   USB disappearance or a changed USB descriptor alone are not success. Confirm
   safe completion, detach the tracked QMP device and stop the root guard. Check
   `phase=stopped`; only then end the guest awake window. VM/disk are retained.

## State, customization and ownership

Default private state: `${XDG_DATA_HOME:-~/.local/share}/xbox-firmware-maintenance`.
Default name: `xbox-firmware-maintenance`. These intentionally **do not adopt or
touch any pre-existing successful firmware VM**. VM name collisions, unowned
disks and UUID/metadata mismatches are refused. Repeated provisioning reuses only
the VM owned by that state. No delete/reset/undefine command is provided.

`wizard.env` remembers public name/port/serial, never sourced as shell code.
`iso-provenance.json` records the publisher page, edition/SKU, language,
architecture and expected publisher SHA256 only after successful verification.
A cached ISO is rehashed against that receipt before reuse (even offline);
this reuses the originally verified release, not necessarily today's latest ISO.
Signed links are never cached. Fresh discovery validates their expiry with a
five-minute safety margin; discovery has bounded waits and a 150-second process
limit, with no retry loops on Microsoft rejection. If a link expires during a
download, no VM is created: rerun to request a fresh session/link.
`vm.json` tracks ownership UUID and direct-QMP attachment intent, including an
interrupted attach. Both live in your private directory; do not edit them to
bypass guards. The only root state is root-owned mode-0700
`/run/xbox-firmware-usb`, not user-writable configuration or executable code.
The global guard intentionally permits only one maintenance session at a time.

For resource overrides, provision first, then choose reuse in the wizard:

```sh
xbox-firmware-vm --state "$HOME/.local/share/my-xbox-maintenance" provision \
  --name my-xbox-maintenance --iso /absolute/path/official.iso \
  --sha256 COPY_MICROSOFT_SHA256 --cpus 4 --memory 8192 --disk 80
```

Automatic metadata-only diagnostic (no ISO download, VM, USB or sudo):

```sh
xbox-firmware-vm resolve-iso
xbox-firmware-vm resolve-iso --language 'English (United Kingdom)'
```

Optional automatic provisioning with another language (downloads the ISO):

```sh
xbox-firmware-vm provision --language 'English (United Kingdom)'
```

The default `wizard`/`provision` needs no URL or hash. `--language` uses the
exact Microsoft language name (default `English` means US). The explicit
`--iso` **and** `--sha256` pair remains an escape hatch if Microsoft restricts
automated requests; obtain that hash from Microsoft's matching language table,
not from a local computed digest. Chromium, matching chromedriver, Selenium and
the immutable tools ISO are packaged by Nix; no pip/browser-driver downloads at
runtime. Nothing installs software in Windows without your execution/consent.

Defaults: KVM q35, 4 vCPU (one socket, four cores, one thread per core),
8192 MiB, sparse 80 GiB qcow2, Secure Boot with
Microsoft-enrolled keys, emulated TPM2, SATA/e1000e inbox drivers, user networking
and local-only SPICE Unix socket. No network listener, USB auto-redirect, whole
hub/controller passthrough, persistent driver blacklist or udev pre-probe claim.
Use supported host CPU/Windows requirements; no EULA, OOBE or activation bypass.

## Recovery and safe cleanup

**If anything is ambiguous during an update, keep FLASH-ACTIVE, host power,
controller cable/port, VM and guest awake window unchanged. Do not activate a new
host configuration or garbage-collect the packaged helpers during maintenance.
Do not reboot,
force-stop, unload drivers, detach, reset USB, delete runtime files or blindly
retry.** The terminal is not the supervisor: the independent transient root
service holds a host sleep/idle inhibitor around a persistent supervisor. Failed
USB monitor workers retry after one second without exiting that supervisor or
releasing its inhibitor, including USB-node/ACL re-enumeration failures. Repeated
or unexpected failures are logged; unreadable state retains the inhibitor rather
than assuming completion. Inspect the journal if monitoring cannot recover.
Active state survives service restart, but killing the supervisor/inhibitor can
release protection until restart; systemd restart is not a continuity guarantee.
SIGINT/SIGTERM, wizard exit and cleanup refuse to restore
xpad or revoke access while active. There is deliberately **no automatic timeout**
that could interrupt an unfinished update. Kernel panic, power loss, SIGKILL,
logind/admin-forced suspend, or reboot cannot be made safe by a script; `/run`
state and transient services do not survive host reboot.

Use a second **real terminal** as the same user; include `--state DIR` if custom:

```sh
xbox-firmware-vm status          # nonprivileged, includes tracked QMP intent
xbox-firmware-vm usb-status      # bounded terminal sudo, root guard details
systemctl status xbox-firmware-usb.service
journalctl -u xbox-firmware-usb.service
systemd-inhibit --list
```

Do not rerun the full wizard into an existing USB session. If the viewer closed
but the VM is still running, `xbox-firmware-vm open` reopens it without restart or
reattach. Guard restart automatically resumes ACL monitoring. Inspect logs and
the official app before any next action. An unknown result needs diagnosis;
this tool does not claim to repair interrupted firmware.

**Only after confirmed no firmware operation is running** (explicit verified
success, or independently confirmed safe cancellation/failure), release the
marker with the deliberate typed confirmation, then request cleanup:

```sh
xbox-firmware-vm flash-complete  # asks SAFE-NO-UPDATE-RUNNING; never clears on timeout
xbox-firmware-vm usb-stop        # refuses if still active; safe to repeat
xbox-firmware-vm usb-status      # require phase=stopped, active=false
```

`usb-stop` first atomically excludes further arming, detaches only its tracked
QMP alias, waits for disappearance, then asks the root service to restore the
current node's original ACL, remove its exact temporary modprobe file, refresh
udev and restore xpad only if originally loaded. Disappeared USB nodes need no
ACL restoration. It keeps historical root ACL records for inspection; the next
safe session replaces stopped records. **Direct QMP `usb-host` devices are not
in libvirt XML**: an empty XML hostdev list does not establish detachment.

Setup failures before flash invoke this same bounded cleanup path independently;
if terminal sudo is unavailable, run `usb-stop` yourself in a real terminal.
If the VM unexpectedly shut down, first diagnose and explicitly confirm no
update is running before releasing the marker. `usb-stop` then accepts verified
`shut off` state (QEMU and its device are gone), without querying a dead monitor.
Other transitional/ambiguous VM states refuse cleanup. Never edit JSON to bypass
these checks. No actual firmware success is claimed by tests.

## Browser network boundary

Automatic metadata discovery starts a temporary loopback-only allowlist proxy
before Chromium and keeps it alive until the browser exits. It accepts only
HTTPS CONNECT to the same Microsoft metadata hosts and Ajax CDN; it does not
intercept TLS, change requests, use an upstream proxy, or bypass access controls.
Chromium uses a fixed proxy without direct fallback or the usual loopback
exemption. QUIC, HTTP/2 authority coalescing and non-proxied WebRTC UDP are disabled.
CDP Fetch still checks individual requests and redirects. If that connection
fails, the independent proxy continues refusing forbidden destinations, then
revokes all tunnels and quits the browser without waiting for context exit.

This is a browser-configured destination boundary, not a host firewall or a
network namespace, and depends on packaged Chromium honoring its proxy settings.
It is not protection against a compromised browser or another local process.
Allowed requests already in flight can reach their allowed host before loss is
detected; revocation cannot recall sent bytes. TLS certificate verification and
the browser sandbox remain enabled in production.

## Development verification

```sh
bash -n modules/home/nixos/scripts/xbox-firmware-vm/wizard.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s modules/home/nixos/scripts/xbox-firmware-vm -p 'test_*.py' -v
alejandra modules/home/nixos/virtualisation.nix
```

Tests mock hardware, privileges, VM operations and downloads. They do not unload
drivers, create VMs, download a multi-GB ISO, or flash anything. A fresh live cold
handoff/reconnect/Accessories acceptance test is still required before use on a
different host/controller. The runtime procedure motivating this tool succeeded
through multiple same-port re-enumerations; that is evidence for the design,
not a guarantee for other hardware or Windows versions.

### Primary references

Live checks on 2026-11-18: the official page exposed a current consumer x64
edition and the language/hash table. A plain API UUID request returned HTTP-200
`ErrorSettings.SentinelReject` (type 8). The ordinary sandboxed Chromium flow
and packaged `resolve-iso` both successfully obtained a signed official link
for `Windows11_Client_x64_en-us_26300_9457.iso` and Microsoft's matching hash
`BD4307DF32BC8AF33B39CCECB1174AEB345386630F89A2B86C7A4E36B55EA650`.
This is discovery evidence only: no ISO bytes were downloaded, VM started,
USB permissions changed or firmware flashed. An initial probe rejected the new
filename shape; the strict validator now covers this observed shape and the
older `Win11_*_x64.iso` shape. Future schema changes still stop safely.
Network-guard probes also rejected CDP `setBlockedURLs` (it did not block
main-frame navigation) and packaged Selenium 4.40 BiDi interception (command
timeouts). The final implementation uses CDP **Fetch** interception, including
every redirect hop, without changing requests or imitating anti-abuse replies.
The opt-in `XBOX_BROWSER_TEST=1` regression uses a loopback-only redirect server
and matching packaged Selenium/Chromium (`XBOX_CHROMIUM`, `XBOX_CHROMEDRIVER`);
it proves disallowed initial requests and redirect targets are never contacted.
`test_browser_network.py` additionally tests the persistent proxy without CDP,
and disconnects CDP during an active paused navigation while deliberately
holding its reader: the forbidden loopback server receives no request before
failure notification. Releasing the reader must revoke the network and stop
chromedriver before the interception context exits. Its local TLS fixture needs
`openssl` (or `XBOX_OPENSSL=/path/to/openssl`); fixture-only certificate exceptions
are not used by the resolver. No external servers are contacted by these tests.

- [Selenium Chrome options and service](https://www.selenium.dev/documentation/webdriver/browsers/chrome/).
- [Chrome pre-request/redirect interception](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)
  (checked against the packaged Chromium; no permissive fallback).

- [Microsoft Windows 11 download/Verify download][iso] (checked 2026-11-18).
- [libvirt secure boot](https://libvirt.org/kbase/secureboot.html),
  [domain XML](https://libvirt.org/formatdomain.html),
  [virsh qemu-monitor-command](https://libvirt.org/manpages/virsh.html#qemu-monitor-command).
- [QEMU USB hostbus/hostport](https://www.qemu.org/docs/master/system/devices/usb.html#using-host-usb-devices-on-a-linux-host):
  matches any device on a physical socket. This is why exclusive socket consent,
  full sysfs-path validation, normal serial checks and refusal of hubs matter.

[iso]: https://www.microsoft.com/software-download/windows11
