"""Root-only, immutable dedicated-port maintenance. Never talks to the VM.

Only /run state is trusted by this process. No user-supplied paths, programs,
environment hooks, shell evaluation, udev claims, or firmware operations.
"""

import fcntl
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
import time

RUN = Path('/run/xbox-firmware-usb')
CONF = Path('/run/modprobe.d/xbox-firmware-usb.conf')
USB = Path('/sys/bus/usb/devices')
MODULE = Path('/sys/module/xpad')
UNIT = 'xbox-firmware-usb.service'
STOPPING = False


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(*args, check=True, input=None):
    result = subprocess.run(args, text=True, input=input, capture_output=True)
    require(not check or result.returncode == 0,
            f'{args[0]} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def save(state):
    temp = RUN / 'state.next'
    temp.write_text(json.dumps(state))
    temp.replace(RUN / 'state.json')


def load():
    return json.loads((RUN / 'state.json').read_text())


def policy():
    return f'blacklist xpad\ninstall xpad {shutil.which("false")}\n'


def validate_identity(state, identity):
    physical, vendor, product, serial, device_class, bus, dev = identity
    require(physical == state['physical'], 'Physical PCI/sysfs path changed')
    require(bus == int(state['port'].split('-')[0]) and 1 <= dev <= 127,
            'Unexpected USB bus/address')
    require(device_class != '09', 'Never forward a hub')
    if (vendor, product) == (state['vendor'], state['product']):
        require(serial == state['serial'], 'Wrong normal-mode serial')
    else:
        # Explicit dedicated-socket consent allows unknown bootloader identities.
        # Never guess a bootloader PID or grant another physical socket.
        require(state['dedicated'], 'Alternate identity requires dedicated-port consent')


def current(state):
    target = USB / state['port']
    if not target.exists():
        return None

    def value(name):
        try:
            return (target / name).read_text().strip()
        except FileNotFoundError:
            if name == 'serial' and target.exists():
                return ''
            raise

    bus, dev = int(value('busnum')), int(value('devnum'))
    identity = [str(target.resolve()), value('idVendor'), value('idProduct'),
                value('serial'), value('bDeviceClass'), bus, dev]
    validate_identity(state, identity)
    node = Path(f'/dev/bus/usb/{bus:03}/{dev:03}')
    info = node.lstat()
    require(stat.S_ISCHR(info.st_mode) and
            (os.major(info.st_rdev), os.minor(info.st_rdev)) ==
            (189, (bus - 1) * 128 + dev - 1), 'Not the exact USB character node')
    # Include sysfs/node generations, not just devnum: USB addresses can wrap.
    identity.extend([target.stat().st_ino, info.st_ino])
    return identity, node


def scope(state):
    """Unloading xpad is global: refuse any other matching or bound device."""
    if MODULE.exists():
        require((MODULE / 'refcnt').read_text().strip() == '0', 'xpad is in use')
        require(not list((MODULE / 'holders').iterdir()), 'xpad has module holders')
    for interface in USB.glob('*:*'):
        own = interface.name.startswith(state['port'] + ':')
        driver = interface / 'driver'
        if driver.exists() and driver.resolve().name == 'xpad':
            require(own, 'Remove other xpad controllers before maintenance')
        alias = interface / 'modalias'
        if alias.exists():
            modules = run('modprobe', '--resolve-alias', alias.read_text().strip(), check=False)
            require(own or 'xpad' not in modules.split(),
                    'Another connected device needs xpad; remove it first')


def prepare(state):
    scope(state)
    CONF.parent.mkdir(exist_ok=True)
    if CONF.exists():
        require(CONF.read_text() == policy(), 'Conflicting runtime modprobe policy')
    else:
        with CONF.open('x') as stream:
            stream.write(policy())
    run('udevadm', 'control', '--reload')
    run('udevadm', 'settle', '--timeout=10')
    scope(state)
    if MODULE.exists():
        run('rmmod', 'xpad')  # Never unload shared ff_memless or force removal.
    require(not MODULE.exists(), 'xpad still loaded')
    require(run('modprobe', '-n', '-v', 'xpad') == f'install {shutil.which("false")}',
            'Autoload inhibition not effective')
    run('modprobe', 'xpad', check=False)
    require(not MODULE.exists(), 'Explicit xpad load was not blocked')
    config = run('modprobe', '-c').splitlines()
    require('blacklist xpad' in config and policy().splitlines()[1] in config,
            'Effective modprobe policy differs')
    state['prepared'] = True
    save(state)


def grant(state):
    now = current(state)
    if now is None:
        return
    identity, node = now
    key = json.dumps(identity)
    if key not in state['acls']:
        state['acls'][key] = run('getfacl', '-p', str(node)) + '\n'
        save(state)  # Save the original before changing permissions.
    if key not in state['granted']:
        require(current(state) == now, 'USB changed before ACL grant')
        run('setfacl', '-m', f'u:{state["uid"]}:rw', str(node))
        require(current(state) == now, 'USB changed during ACL grant')
        state['granted'].append(key)
        state['generation'] += 1
        print(f'Exact port granted: {node} {identity[1]}:{identity[2]}', flush=True)
    state['current'] = identity
    state['ready'] = True
    save(state)


def cleanup(state):
    # Caller holds control lock: active/complete cannot race cleanup.
    if state['active']:
        return False
    try:
        now = current(state)
    except FileNotFoundError:
        now = None
    if now:
        identity, _ = now
        acl = state['acls'].get(json.dumps(identity))
        if acl:
            run('setfacl', '--restore=-', input=acl)
    if CONF.exists():
        require(CONF.read_text() == policy(), 'Refusing to remove foreign policy')
        CONF.unlink()
        run('udevadm', 'control', '--reload')
    if state['xpad_loaded']:
        run('modprobe', 'xpad')
    state.update(phase='stopped', ready=False)
    save(state)
    return True


def signal_stop(_signum, _frame):
    global STOPPING
    STOPPING = True


def locked():
    stream = (RUN / 'control.lock').open('a')
    fcntl.flock(stream, fcntl.LOCK_EX)
    return stream


def monitor():
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal_stop)
    try:
        with locked():
            state = load()
            if state['phase'] == 'stopped':
                return
            if not state['prepared']:
                prepare(state)
        while True:
            with locked():
                state = load()
                if state['phase'] == 'stopped':
                    return
                if (STOPPING or state['stop']) and cleanup(state):
                    return
                require(not MODULE.exists() and CONF.read_text() == policy(),
                        'Guard policy lost; preserving active-flash state')
                try:
                    grant(state)
                except FileNotFoundError:
                    pass  # Expected sysfs teardown/re-enumeration race; retry.
            time.sleep(0.05)
    except BaseException:
        with locked():
            state = load()
            if not state['active']:
                cleanup(state)
        raise  # The persistent supervisor retries without releasing its inhibitor.


def daemon():
    """Persistent supervisor under systemd-inhibit; workers never own its lifetime.

    A worker exit or unreadable state does not establish safe completion.
    systemd restart is only last-resort recovery, not continuous protection
    against killing this supervisor or the inhibitor itself.
    """
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, signal_stop)
    while True:
        try:
            with locked():
                state = load()
                if state['phase'] == 'stopped':
                    return
                if (STOPPING or state['stop']) and not state['active'] and cleanup(state):
                    return
            worker = subprocess.run([sys.executable, '-I', str(Path(__file__).resolve()),
                                     'monitor'], check=False)
            with locked():
                state = load()
                if state['phase'] == 'stopped':
                    return
                state['ready'] = False
                save(state)
                if not state['active'] and cleanup(state):
                    return
            print(f'USB monitor exited ({worker.returncode}); retaining active state and '
                  'sleep inhibitor; retrying in 1s', file=sys.stderr, flush=True)
        except Exception as error:
            # Also covers supervisor I/O/launch failures: fail closed even when
            # state cannot be read, rather than assume flashing is inactive.
            print(f'USB supervisor: {error}; retaining sleep inhibitor; retrying in 1s',
                  file=sys.stderr, flush=True)
        time.sleep(1)


def new_state(uid, port, serial, session):
    require(re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*', port),
            'Use a directly connected physical socket, not a hub/downstream port')
    require(serial and len(serial) <= 256 and serial.isprintable(), 'Invalid serial')
    require(re.fullmatch(r'[a-f0-9-]{36}', session), 'Invalid VM session identifier')
    target = USB / port
    physical = str(target.resolve(strict=True))
    require(physical.startswith('/sys/devices/pci') and physical.endswith('/' + port),
            'Expected a full PCI-backed USB sysfs path')
    state = dict(uid=uid, port=port, physical=physical, serial=serial, session=session,
                 vendor=(target / 'idVendor').read_text().strip(),
                 product=(target / 'idProduct').read_text().strip(),
                 dedicated=True, active=False, stop=False, disarming=False, prepared=False,
                 ready=False, phase='running', acls={}, granted=[], generation=0,
                 xpad_loaded=MODULE.exists(), current=None)
    require(state['vendor'] == '045e', 'Select the exact Microsoft Xbox controller')
    now = current(state)
    require(now is not None, 'Controller absent')
    interfaces = list(USB.glob(port + ':*'))
    require(interfaces and all(not (p / 'driver').exists() or
            (p / 'driver').resolve().name == 'xpad' for p in interfaces),
            'Controller already captured or bound to another driver')
    scope(state)
    return state


def main():
    require(os.geteuid() == 0, 'Invoke the packaged helper through terminal sudo')
    action, *args = sys.argv[1:]
    if action in ('daemon', 'monitor'):
        require(not args and 'SUDO_UID' not in os.environ, 'Daemon is service-only')
        (daemon if action == 'daemon' else monitor)()
        return
    require(os.isatty(0), 'Privileged operations require a real terminal')
    uid = int(os.environ.get('SUDO_UID', '0'))
    require(uid > 0 and pwd.getpwuid(uid).pw_uid == uid, 'Use sudo as a normal user')
    require(action in ('start', 'status', 'active', 'complete', 'disarm', 'stop'), 'Unknown operation')
    # /run is root-owned; refuse pre-existing unsafe objects, even for status.
    if not RUN.exists():
        RUN.mkdir(mode=0o700)
    info = RUN.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and
            stat.S_IMODE(info.st_mode) == 0o700, 'Unsafe root state directory')
    with locked():
        if action == 'status' and not (RUN / 'state.json').exists():
            require(not args and not CONF.exists(), 'Missing state with existing runtime policy; inspect manually')
            print(json.dumps(dict(phase='absent', active=False, session=None)))
            return
        if action == 'start':
            require(len(args) == 4 and args[2] == 'DEDICATED-CONTROLLER-ONLY',
                    'Dedicated physical socket consent is required')
            require(not (RUN / 'state.json').exists() or load()['phase'] == 'stopped',
                    'A guard already exists; inspect/resume it, do not replace it')
            require(not CONF.exists(), 'Existing runtime policy; inspect before recovery')
            require(run('systemctl', 'is-active', UNIT, check=False) not in
                    ('active', 'activating', 'deactivating'), 'Previous service still running')
            state = new_state(uid, args[0], args[1], args[3])
            save(state)
            run('systemctl', 'reset-failed', UNIT, check=False)
            # All executable paths are immutable package artifacts, not user inputs.
            require(str(Path(__file__).resolve()).startswith('/nix/store/'),
                    'Privileged execution must use the packaged Nix-store helper')
            try:
                run('systemd-run', '--unit=' + UNIT, '--collect',
                    '--property=Restart=on-failure', '--property=RestartSec=200ms',
                    '--property=StartLimitIntervalSec=0',
                    '--property=TimeoutStopSec=infinity', '--property=UMask=0077',
                    '--setenv=PATH=' + os.environ['PATH'],
                    shutil.which('systemd-inhibit'), '--what=sleep:idle', '--mode=block',
                    '--who=XboxFirmware', '--why=Dedicated controller maintenance',
                    sys.executable, '-I', str(Path(__file__).resolve()), 'daemon')
            except BaseException:
                state['phase'] = 'stopped'
                save(state)
                raise
        else:
            require(not args, 'Unexpected arguments')
            state = load()
            require(state['uid'] == uid, 'Guard belongs to another user')
            if action == 'active':
                require(state['phase'] == 'running' and state['ready'] and not state['stop']
                        and not state['disarming'],
                        'Guard not ready')
                require(run('systemctl', 'is-active', UNIT) == 'active', 'Service not active')
                require(not MODULE.exists() and CONF.read_text() == policy(), 'Policy lost')
                now = current(state)
                require(now is not None and now[0][1:4] ==
                        [state['vendor'], state['product'], state['serial']],
                        'Exact normal-mode controller must be present before arming')
                interfaces = list(USB.glob(state['port'] + ':*'))
                require(interfaces and all((p / 'driver').exists() and
                        (p / 'driver').resolve().name == 'usbfs' for p in interfaces),
                        'QEMU must own every controller interface before arming')
                state['active'] = True
            elif action == 'complete':
                # Only after explicit user confirmation in the launcher, including recovery.
                state['active'] = False
            elif action == 'disarm':
                require(not state['active'], 'ACTIVE FLASH: detach and cleanup refused')
                # Atomically exclude later arming BEFORE the launcher detaches QMP.
                state['disarming'] = True
            elif action == 'stop':
                require(not state['active'], 'ACTIVE FLASH: stop/cleanup refused')
                state['stop'] = True
                if run('systemctl', 'is-active', UNIT, check=False) != 'active':
                    cleanup(state)  # Independent setup-failure cleanup.
            save(state)
        print(json.dumps(state, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as error:
        print(f'USB guard: {error}', file=sys.stderr)
        sys.exit(1)
