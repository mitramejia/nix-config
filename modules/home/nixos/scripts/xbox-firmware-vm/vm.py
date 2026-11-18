"""Unprivileged session VM provisioning and exact QMP maintenance operations."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

URI = 'qemu:///session'
QMP_ID = 'xbox-firmware-port'
MARKER = 'https://nix-config.local/xbox-firmware-vm/v1'
DEFAULT = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'xbox-firmware-maintenance'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    require(not check or result.returncode == 0, result.stderr.strip() or str(args))
    return result.stdout.strip()


def virsh(*args, check=True):
    return run('virsh', '-c', URI, *args, check=check)


def save(base, state):
    temp = base / 'vm.next'
    temp.write_text(json.dumps(state, indent=2))
    temp.replace(base / 'vm.json')


def read_state(base):
    return json.loads((base / 'vm.json').read_text())


@contextlib.contextmanager
def locked(base, create=False):
    if create:
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not base.is_symlink() and base.is_dir() and base.stat().st_uid == os.getuid()
            and base.stat().st_mode & 0o077 == 0, 'State must be your private, non-symlink directory (0700)')
    with (base / 'launcher.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another launcher is operating on this state') from error
        yield


def official_url(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname in
            ('software.download.prss.microsoft.com', 'software-download.microsoft.com')
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment,
            'Only HTTPS links issued by Microsoft’s official ISO download page are accepted')


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        official_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def discover_iso(language):
    # Dedicated immutable resolver, bounded lifetime and no signed URL in logs.
    with subprocess.Popen([os.environ['XBOX_ISO_RESOLVER'], '--language', language],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=150)
        except BaseException:
            # Include Chromium/driver grandchildren, not just the Python parent.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise RuntimeError('Microsoft discovery interrupted/timed out; no ISO download or VM creation') from None
        require(process.returncode == 0, stderr.strip() or 'Microsoft discovery failed')
    metadata = json.loads(stdout)
    official_url(metadata['url'])
    require(metadata['language'] == language and metadata['architecture'] == 'x64'
            and metadata['publisher_page'] == 'https://www.microsoft.com/en-us/software-download/windows11'
            and time.time() + 300 < metadata['expires_at'] <= time.time() + 25 * 3600
            and re.fullmatch('[0-9a-f]{64}', metadata['sha256']), 'Invalid publisher metadata')
    return metadata


def automatic_iso(base, language):
    receipt = base / 'iso-provenance.json'
    require(not receipt.is_symlink(), 'Refusing symlink ISO receipt')
    if receipt.exists():
        metadata = json.loads(receipt.read_text())
        if (metadata.get('language') == language and metadata.get('architecture') == 'x64'
                and metadata.get('publisher_page') == 'https://www.microsoft.com/en-us/software-download/windows11'
                and (base / 'windows.iso').is_file()):
            checksum(base / 'windows.iso', metadata['sha256'])
            print('Reusing cached official ISO after publisher SHA256 re-verification.')
            return base / 'windows.iso'
    print('Resolving official consumer Windows 11 x64 link and publisher SHA256 automatically.', flush=True)
    metadata = discover_iso(language)
    iso = obtain_iso(base, metadata.pop('url'), metadata['sha256'])
    # Only verified bytes get a receipt. Never persist expiring signed URLs.
    metadata['verified_at'] = int(time.time())
    receipt.write_text(json.dumps(metadata, indent=2))
    return iso


def checksum(path, expected):
    require(re.fullmatch(r'[0-9a-fA-F]{64}', expected) is not None,
            'Paste the full Microsoft SHA256 for this edition/language')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    require(digest.hexdigest() == expected.lower(), 'ISO SHA256 mismatch; no VM was created')


def obtain_iso(base, source, expected):
    require(re.fullmatch(r'[0-9a-fA-F]{64}', expected) is not None,
            'Paste the full Microsoft SHA256 before downloading')
    if source.startswith('https:'):
        official_url(source)
        destination = base / 'windows.iso'
        if destination.exists():
            checksum(destination, expected)
            return destination
        partial = base / 'windows.iso.partial'
        require(not partial.is_symlink(), 'Refusing symlink download destination')
        opener = urllib.request.build_opener(OfficialRedirect())
        try:
            print('Downloading official Windows ISO (several GiB); SHA256 verification follows.', flush=True)
            with opener.open(source, timeout=60) as response, partial.open('wb') as output:
                official_url(response.url)
                shutil.copyfileobj(response, output, 4 * 1024 * 1024)
            checksum(partial, expected)
            partial.replace(destination)
        except BaseException:
            partial.unlink(missing_ok=True)
            raise
        return destination
    source = Path(source).expanduser().resolve(strict=True)
    require(source.is_file(), 'ISO must be a regular file')
    checksum(source, expected)
    return source


def domain_xml(base, state, iso, cpus, memory):
    # ElementTree escapes paths and names: no shell/XML interpolation.
    domain = ET.Element('domain', type='kvm')

    def add(parent, tag, text=None, **attributes):
        element = ET.SubElement(parent, tag, attributes)
        element.text = text
        return element

    add(domain, 'name', state['name'])
    add(domain, 'uuid', state['uuid'])
    metadata = add(domain, 'metadata')
    add(metadata, '{' + MARKER + '}owner', state['uuid'])
    add(domain, 'memory', str(memory), unit='MiB')
    add(domain, 'vcpu', str(cpus))
    os_xml = add(domain, 'os')
    add(os_xml, 'type', 'hvm', arch='x86_64', machine='q35')
    firmware = Path(os.environ['XBOX_OVMF'])
    add(os_xml, 'loader', str(firmware / 'OVMF_CODE.ms.fd'), readonly='yes', secure='yes', type='pflash')
    add(os_xml, 'nvram', str(base / 'OVMF_VARS.fd'), template=str(firmware / 'OVMF_VARS.ms.fd'))
    add(os_xml, 'boot', dev='cdrom')
    add(os_xml, 'boot', dev='hd')
    add(os_xml, 'bootmenu', enable='yes')
    features = add(domain, 'features')
    add(features, 'acpi')
    add(features, 'apic')
    add(features, 'smm', state='on')
    cpu = add(domain, 'cpu', mode='host-passthrough')
    add(cpu, 'topology', sockets='1', cores=str(cpus), threads='1')
    add(domain, 'clock', offset='localtime')
    pm = add(domain, 'pm')
    add(pm, 'suspend-to-mem', enabled='no')
    add(pm, 'suspend-to-disk', enabled='no')
    devices = add(domain, 'devices')
    add(devices, 'emulator', os.environ['XBOX_QEMU'])
    media = [('disk', base / 'windows.qcow2', 'sda'), ('cdrom', iso, 'sdb')]
    if os.environ.get('XBOX_GUEST_TOOLS'):
        media.append(('cdrom', Path(os.environ['XBOX_GUEST_TOOLS']), 'sdc'))
    for device, path, target in media:
        disk = add(devices, 'disk', type='file', device=device)
        add(disk, 'driver', name='qemu', type='qcow2' if device == 'disk' else 'raw')
        add(disk, 'source', file=str(path))
        add(disk, 'target', dev=target, bus='sata')
        if device == 'cdrom':
            add(disk, 'readonly')
    add(devices, 'controller', type='usb', model='qemu-xhci', index='0')
    interface = add(devices, 'interface', type='user')
    add(interface, 'model', type='e1000e')
    add(devices, 'input', type='tablet', bus='usb')
    tpm = add(devices, 'tpm', model='tpm-crb')
    add(tpm, 'backend', type='emulator', version='2.0')
    graphics = add(devices, 'graphics', type='spice')
    add(graphics, 'listen', type='socket', socket=str(base / 'spice.sock'))
    add(graphics, 'clipboard', copypaste='no')
    add(graphics, 'filetransfer', enable='no')
    video = add(devices, 'video')
    add(video, 'model', type='vga')
    return ET.tostring(domain, encoding='unicode')


def owned_xml(xml, state):
    root = ET.fromstring(xml)
    return root.findtext('uuid') == state['uuid'] and \
        root.findtext('metadata/{' + MARKER + '}owner') == state['uuid']


def check_owned(state):
    xml = virsh('dumpxml', state['name'])
    require(owned_xml(xml, state), 'Refusing an unowned VM (UUID/metadata mismatch)')
    return xml


def provision(base, args):
    require(platform.machine() == 'x86_64' and os.access('/dev/kvm', os.R_OK | os.W_OK),
            'Requires x86_64 Linux with working KVM access (kvm group; log in again if needed)')
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}', args.name), 'Invalid VM name')
    require(2 <= args.cpus <= 64 and 4096 <= args.memory <= 131072 and 64 <= args.disk <= 2048,
            'Use 2–64 vCPU, 4096–131072 MiB RAM, 64–2048 GiB disk')
    names = virsh('list', '--all', '--name').splitlines()
    existing = (base / 'vm.json').exists()
    if existing:
        state = read_state(base)
        require(state['name'] == args.name, 'This state directory already owns a different name')
        if args.name in names:
            check_owned(state)
            print('Reusing owned VM; no disk or definition changes.')
            return
        require(state['phase'] == 'creating', 'Owned definition disappeared; inspect state, no automatic recreation')
    else:
        require(args.name not in names, 'VM name already exists; refusing to adopt or overwrite it')
        require(not (base / 'windows.qcow2').exists(), 'Unowned disk exists; refusing overwrite')
        state = dict(name=args.name, uuid=str(uuid.uuid4()), phase='creating', qmp=None)
    # Verification is mandatory before committing any VM/disk creation.
    require(bool(args.iso) == bool(args.sha256), 'Use --iso and --sha256 together, or neither for automatic discovery')
    iso = obtain_iso(base, args.iso, args.sha256) if args.iso else automatic_iso(base, args.language)
    save(base, state)
    disk = base / 'windows.qcow2'
    if not disk.exists():
        run('qemu-img', 'create', '-f', 'qcow2', str(disk), f'{args.disk}G')
    else:
        require(not disk.is_symlink(), 'Refusing symlink disk')
        info = json.loads(run('qemu-img', 'info', '--output=json', str(disk)))
        require(info['format'] == 'qcow2' and not info.get('backing-filename'), 'Unexpected existing disk')
    xml_path = base / 'domain.xml'
    xml_path.write_text(domain_xml(base, state, iso, args.cpus, args.memory))
    virsh('define', str(xml_path))
    check_owned(state)
    state['phase'] = 'ready'
    save(base, state)
    print('Owned session VM created. ISO verified. No USB forwarding configured.')


def qmp(state, execute, arguments=None):
    command = dict(execute=execute)
    if arguments is not None:
        command['arguments'] = arguments
    result = json.loads(virsh('qemu-monitor-command', state['name'], json.dumps(command)))
    require('error' not in result, f'QMP: {result.get("error")}')
    return result['return']


def guard(action, *args):
    require(os.isatty(0), 'Use a real terminal for bounded sudo USB operations')
    # Nix-store sudo is deliberately not setuid. Use NixOS's privileged wrapper,
    # not a runtimeInputs sudo binary or a user-controlled PATH entry.
    process = subprocess.run(['/run/wrappers/bin/sudo', '--', os.environ['XBOX_USB_GUARD'], action, *args],
                             text=True, stdout=subprocess.PIPE)
    require(process.returncode == 0, 'USB guard operation failed; inspect status/recovery instructions')
    return json.loads(process.stdout)


def usb_start(base, state, port, serial):
    check_owned(state)
    require(virsh('domstate', state['name']) == 'running', 'Start the owned VM first')
    require(not state.get('qmp'), 'Existing QMP capture tracked; use recovery/status, never blindly reattach')
    # A previous untracked device (e.g. interruption) is not silently replaced.
    tree = qmp(state, 'human-monitor-command', {'command-line': 'info qtree'})
    require(QMP_ID not in tree, 'QMP device already exists; recover using tracked state')
    print(f'Reserve physical socket {port} ONLY for controller serial {serial}. '
          'Unknown-mode IDs at this socket are accepted; no other device may be plugged there. '
          'xpad will be temporarily inhibited globally.')
    require(input('Type DEDICATED-CONTROLLER-ONLY to consent: ') == 'DEDICATED-CONTROLLER-ONLY',
            'Dedicated socket consent not given')
    # Record pre-guard intent too: a crash after root start but before return
    # must not leave an invisible privileged session.
    state['qmp'] = dict(id=QMP_ID, port=port, phase='start-intent')
    save(base, state)
    root = guard('start', port, serial, 'DEDICATED-CONTROLLER-ONLY', state['uuid'])
    # Persist intent BEFORE attachment, so interrupted QMP calls remain cleanup-aware.
    state['qmp'] = dict(id=QMP_ID, port=root['port'], physical=root['physical'], phase='guard-started')
    save(base, state)


def usb_attach(base, state):
    check_owned(state)
    tracked = state.get('qmp')
    require(tracked and tracked['phase'] == 'guard-started', 'No pending cold handoff')
    root = guard('status')
    require(root['ready'] and not root['active'] and not root['disarming']
            and root['phase'] == 'running' and root['physical'] == tracked['physical']
            and root['session'] == state['uuid'], 'Guard not ready or belongs to a different VM')
    require(not Path('/sys/module/xpad').exists(), 'xpad must remain absent until after capture')
    require(not (Path('/sys/bus/usb/devices') / root['port']).exists(),
            'Unplug controller fully before adding cold capture; do not just unbind it')
    bus, port = root['port'].split('-')
    tracked['phase'] = 'attach-intent'
    save(base, state)
    qmp(state, 'device_add', dict(driver='usb-host', id=QMP_ID,
                                 hostbus=int(bus), hostport=port, bus='usb.0', port='4'))
    tracked['phase'] = 'attached'
    save(base, state)
    print('Cold QMP port capture added. Reconnect ONLY the selected controller to that exact socket.')


def usb_stop(base, state):
    root = guard('status')
    tracked = state.get('qmp')
    if root['session'] != state.get('uuid') and tracked and tracked['phase'] == 'start-intent':
        # Root start was refused before ownership was established. No device_add
        # can have happened in this phase; clear only our local intent, never
        # touch another session's service, policy, marker or QMP devices.
        check_owned(state)
        state['qmp'] = None
        save(base, state)
        print('Cleared unstarted local intent; other/absent root guard left untouched.')
        return
    require(not root['active'], 'ACTIVE FLASH: detach and cleanup refused')
    require(root['session'] == state.get('uuid'), 'Guard belongs to another VM/state directory; refusing cleanup')
    guard('disarm')  # Atomic flash-active exclusion must precede any QMP detach.
    if tracked:
        check_owned(state)
        vm_status = virsh('domstate', state['name'])
        require(vm_status in ('running', 'shut off'), 'VM transition in progress; keep guard and inspect')
        if vm_status == 'running':
            tree = qmp(state, 'human-monitor-command', {'command-line': 'info qtree'})
            if QMP_ID in tree:
                qmp(state, 'device_del', {'id': QMP_ID})
                for _ in range(50):
                    tree = qmp(state, 'human-monitor-command', {'command-line': 'info qtree'})
                    if QMP_ID not in tree:
                        break
                    time.sleep(0.1)
                require(QMP_ID not in tree, 'QMP detach not yet acknowledged; guard kept running')
        # shut off means the QEMU process and its direct device are gone; this
        # recovery is permitted ONLY after the root active marker was released.
        state['qmp'] = None
        save(base, state)
    guard('stop')
    for _ in range(100):
        if run('systemctl', 'is-active', 'xbox-firmware-usb.service', check=False) not in ('active', 'activating', 'deactivating'):
            print('Guard stopped; inspect USB status to confirm phase=stopped and policy restored.')
            return
        time.sleep(0.1)
    raise RuntimeError('Cleanup still running: inspect journal; do not force-stop the service')


def main():
    require(os.geteuid() != 0, 'Never run the launcher as root')
    parser = argparse.ArgumentParser(prog='xbox-firmware-vm', description=__doc__,
                                     epilog='Interactive guided flow: xbox-firmware-vm wizard [private-state-directory]')
    parser.add_argument('--state', type=Path, default=DEFAULT)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'status', 'dry-run', 'controllers', 'open', 'usb-status', 'usb-attach',
                 'flash-active', 'flash-complete', 'usb-stop'):
        commands.add_parser(name)
    setup = commands.add_parser('provision')
    setup.add_argument('--name', default='xbox-firmware-maintenance')
    setup.add_argument('--iso', help='Explicit official ISO path/HTTPS override; requires --sha256')
    setup.add_argument('--sha256', help='Matching Microsoft publisher SHA256 for explicit --iso')
    setup.add_argument('--language', default='English', help='Microsoft language name; English is US (automatic mode)')
    setup.add_argument('--cpus', type=int, default=4)
    setup.add_argument('--memory', type=int, default=8192)
    setup.add_argument('--disk', type=int, default=80)
    probe = commands.add_parser('resolve-iso', help='Live metadata probe only; no ISO download, VM or sudo')
    probe.add_argument('--language', default='English')
    start = commands.add_parser('usb-start')
    start.add_argument('--port', required=True)
    start.add_argument('--serial', required=True)
    args = parser.parse_args()
    base = args.state.expanduser().absolute()
    require('\n' not in str(base), 'Invalid state directory')
    if args.command == 'dry-run':
        print(f'No changes. State: {base}\nSession KVM/q35, secure MS UEFI, TPM2, SATA/e1000e, local SPICE; '
              '4 vCPU/8192 MiB/sparse 80 GiB defaults.\nAutomatic Microsoft consumer x64 ISO/link + publisher SHA256; English (US). '
              'Manual Windows/OOBE/Accessories. Explicit exact-port USB consent and reconnect test before update.')
        return
    if args.command == 'resolve-iso':
        metadata = discover_iso(args.language)
        metadata.pop('url')
        print(json.dumps(dict(metadata, official_link_obtained=True), indent=2))
        return
    if args.command == 'controllers':
        print('Direct Microsoft USB devices (verify controller product; never select a receiver/hub):')
        for target in sorted(Path('/sys/bus/usb/devices').glob('*')):
            if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*', target.name):
                continue
            try:
                if (target / 'idVendor').read_text().strip() == '045e':
                    print(target.name, 'product=' + (target / 'idProduct').read_text().strip(),
                          'serial=' + (target / 'serial').read_text().strip(),
                          'label=' + (target / 'product').read_text().strip(), str(target.resolve()))
            except FileNotFoundError:
                continue
        return
    if args.command == 'status':
        if (base / 'vm.json').exists():
            state = read_state(base)
            print(json.dumps(state, indent=2))
            check_owned(state)
            print(virsh('domstate', state['name']))
        else:
            print('No owned VM in this state directory.')
        print('USB service:', run('systemctl', 'is-active', 'xbox-firmware-usb.service', check=False))
        print('Root details: usb-status (terminal sudo). Direct QMP devices are NOT in libvirt XML.')
        return
    with locked(base, create=args.command in ('init', 'provision')):
        if args.command == 'init':
            print(base)
        elif args.command == 'provision':
            provision(base, args)
        elif args.command == 'usb-status':
            print(json.dumps(guard('status'), indent=2))
        elif args.command == 'flash-complete':
            root = guard('status')
            require(root['session'] == read_state(base)['uuid'], 'Guard belongs to another VM/state directory')
            require(input('Only after explicit success/version check OR confirmed no update running. '
                          'Type SAFE-NO-UPDATE-RUNNING: ') == 'SAFE-NO-UPDATE-RUNNING', 'Completion not confirmed')
            guard('complete')
        elif args.command == 'usb-stop':
            state = read_state(base) if (base / 'vm.json').exists() else {}
            usb_stop(base, state)
        else:
            state = read_state(base)
            if args.command == 'open':
                check_owned(state)
                status = virsh('domstate', state['name'])
                require(status in ('running', 'shut off'), 'VM is not in a safe open/start state')
                if status == 'shut off':
                    require(not state.get('qmp'), 'Previous USB session tracked; inspect recovery before restarting')
                    virsh('start', state['name'])
                subprocess.Popen(['virt-viewer', '--connect', URI, '--attach', '--reconnect',
                                  '--spice-usbredir-auto-redirect-filter=-1,-1,-1,-1,0',
                                  '--spice-usbredir-redirect-on-connect=-1,-1,-1,-1,0', state['name']],
                                 start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif args.command == 'usb-start':
                usb_start(base, state, args.port, args.serial)
            elif args.command == 'usb-attach':
                usb_attach(base, state)
            elif args.command == 'flash-active':
                require((state.get('qmp') or {}).get('phase') == 'attached', 'No completed QMP handoff tracked')
                check_owned(state)
                require(QMP_ID in qmp(state, 'human-monitor-command', {'command-line': 'info qtree'}),
                        'QMP capture missing')
                root = guard('status')
                require(root['generation'] >= 3 and root['physical'] == state['qmp']['physical']
                        and root['session'] == state['uuid'],
                        'Cold reconnect and SECOND unplug/reconnect must be proven before flash')
                guard('active')
                print('FLASH ACTIVE: cleanup/stop disabled. Do not close guest awake loop or interrupt VM/power/USB.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, ET.ParseError) as error:
        print(f'xbox-firmware-vm: {error}', file=sys.stderr)
        sys.exit(1)
