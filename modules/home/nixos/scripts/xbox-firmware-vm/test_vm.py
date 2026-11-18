"""Hardware-free regression tests. No sudo, VM, network or module operations."""

import argparse
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


vm = module('vm')
usb = module('usb_guard')


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(physical='/sys/devices/pci0000:00/example/usb7/7-4', port='7-4',
                          vendor='045e', product='1234', serial='exact', dedicated=True)
        self.identity = [self.state['physical'], '045e', '1234', 'exact', 'ff', 7, 5]

    def test_exact_normal_identity(self):
        usb.validate_identity(self.state, self.identity)

    def test_wrong_scope_serial_bus_and_hub_rejected(self):
        for position, replacement in [(0, '/sys/other/7-4'), (3, 'wrong'),
                                      (4, '09'), (5, 8), (6, 128)]:
            identity = list(self.identity)
            identity[position] = replacement
            with self.subTest(position=position), self.assertRaises(RuntimeError):
                usb.validate_identity(self.state, identity)

    def test_unknown_identity_requires_dedicated_socket_consent(self):
        self.identity[1:4] = ['ffff', 'eeee', '']
        usb.validate_identity(self.state, self.identity)
        self.state['dedicated'] = False
        with self.assertRaises(RuntimeError):
            usb.validate_identity(self.state, self.identity)

    def test_downstream_hub_port_rejected_before_any_io(self):
        with patch.object(usb, 'run') as run, self.assertRaises(RuntimeError):
            usb.new_state(1000, '7-4.1', 'exact', 'a' * 36)
        run.assert_not_called()

    def test_other_matching_xpad_device_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            interface = root / '8-2:1.0'
            interface.mkdir()
            (interface / 'modalias').write_text('usb:example')
            with patch.object(usb, 'USB', root), patch.object(usb, 'MODULE', root / 'absent'), \
                    patch.object(usb, 'run', return_value='xpad'), self.assertRaises(RuntimeError):
                usb.scope(self.state)

    def test_active_cleanup_does_nothing(self):
        with patch.object(usb, 'run') as run, patch.object(usb, 'current') as current:
            self.assertFalse(usb.cleanup(dict(active=True)))
        run.assert_not_called()
        current.assert_not_called()

    def test_reenumeration_grants_each_new_node_and_preserves_acl_first(self):
        state = dict(self.state, acls={}, granted=[], uid=1000, generation=0)
        events = []

        def save(value):
            events.append(('save', json.loads(json.dumps(value))))

        def run(*args):
            events.append(args)
            return 'original ACL'

        with patch.object(usb, 'save', side_effect=save), patch.object(usb, 'run', side_effect=run):
            for dev in (5, 6, 7, 8):
                identity = list(self.identity)
                identity[6] = dev
                now = (identity, Path(f'/dev/bus/usb/007/{dev:03}'))
                with patch.object(usb, 'current', return_value=now):
                    usb.grant(state)
                    usb.grant(state)  # No duplicate ACL snapshot or grant on steady node.
        self.assertEqual(state['generation'], 4)
        self.assertEqual(len(state['acls']), 4)
        self.assertEqual(sum(event[0] == 'setfacl' for event in events), 4)
        for index, event in enumerate(events):
            if event[0] == 'setfacl':
                self.assertEqual(events[index - 1][0], 'save')
                self.assertTrue(events[index - 1][1]['acls'])

    def test_failed_acl_grant_retries_without_overwriting_original(self):
        state = dict(self.state, acls={}, granted=[], uid=1000, generation=0)
        now = (self.identity, Path('/dev/bus/usb/007/005'))
        with patch.object(usb, 'save'), patch.object(usb, 'current', return_value=now), \
                patch.object(usb, 'run', side_effect=['original', RuntimeError('transient')]):
            with self.assertRaises(RuntimeError):
                usb.grant(state)
        with patch.object(usb, 'save'), patch.object(usb, 'current', return_value=now), \
                patch.object(usb, 'run') as run:
            usb.grant(state)
        run.assert_called_once_with('setfacl', '-m', 'u:1000:rw', '/dev/bus/usb/007/005')
        self.assertEqual(state['generation'], 1)

    def test_signal_and_fault_preserve_active_flash(self):
        state = dict(active=True, prepared=True, phase='running', stop=False)
        lock = Mock()
        lock.__enter__ = Mock(return_value=None)
        lock.__exit__ = Mock(return_value=False)
        with patch.object(usb, 'STOPPING', False), patch.object(usb, 'locked', return_value=lock), \
                patch.object(usb, 'load', return_value=state), patch.object(usb, 'run') as run, \
                patch.object(usb, 'MODULE') as mod, patch.object(usb, 'CONF') as conf, \
                patch.object(usb, 'policy', return_value='policy'), \
                patch.object(usb, 'grant'), patch.object(usb.time, 'sleep', side_effect=RuntimeError('crash')):
            mod.exists.return_value = False
            conf.read_text.return_value = 'policy'
            usb.signal_stop(None, None)
            with self.assertRaisesRegex(RuntimeError, 'crash'):
                usb.monitor()
            self.assertTrue(state['active'])
        run.assert_not_called()

    def test_setup_failure_invokes_independent_cleanup(self):
        state = dict(active=False, prepared=False, phase='running')
        lock = Mock()
        lock.__enter__ = Mock(return_value=None)
        lock.__exit__ = Mock(return_value=False)
        with patch.object(usb, 'locked', return_value=lock), patch.object(usb, 'load', return_value=state), \
                patch.object(usb, 'prepare', side_effect=RuntimeError('setup failure')), \
                patch.object(usb, 'cleanup', return_value=True) as cleanup:
            with self.assertRaisesRegex(RuntimeError, 'setup failure'):
                usb.monitor()
        cleanup.assert_called_once_with(state)

    def test_policy_blocks_before_unloading_and_never_loads_ff_memless(self):
        with tempfile.TemporaryDirectory() as temp:
            conf = Path(temp) / 'modprobe.d' / 'guard.conf'
            calls = []

            def run(*args, **_kwargs):
                calls.append(args)
                if args[:3] == ('modprobe', '-n', '-v'):
                    return 'install /immutable/false'
                if args == ('modprobe', '-c'):
                    return 'blacklist xpad\ninstall xpad /immutable/false'
                if args == ('rmmod', 'xpad'):
                    self.assertEqual(conf.read_text(), 'blacklist xpad\ninstall xpad /immutable/false\n')
                    module.exists.return_value = False
                return ''

            with patch.object(usb, 'CONF', conf), patch.object(usb, 'MODULE') as module, \
                    patch.object(usb, 'scope'), patch.object(usb, 'save'), \
                    patch.object(usb.shutil, 'which', return_value='/immutable/false'), \
                    patch.object(usb, 'run', side_effect=run):
                module.exists.return_value = True
                usb.prepare({})
            self.assertLess(calls.index(('udevadm', 'settle', '--timeout=10')), calls.index(('rmmod', 'xpad')))
            self.assertFalse(any('ff_memless' in call for call in calls))


class SupervisorTests(unittest.TestCase):
    def test_disappearing_node_retries_under_same_inhibitor_owner(self):
        state = dict(active=True, prepared=True, phase='running', stop=False,
                     ready=True, acls={}, granted=[], uid=1000, generation=0)
        identity = ['/sys/devices/pci/example/7-4', '045e', '1234', 'exact', 'ff', 7, 5]
        now = (identity, Path('/dev/bus/usb/007/005'))
        lock = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        workers = []
        delays = []

        def sleep(seconds):
            if seconds == 0.05:
                # End the successful second worker without touching USB or policy.
                state['phase'] = 'stopped'
            else:
                self.assertEqual(seconds, 1)
                self.assertTrue(state['active'])
                self.assertEqual(state['generation'], 0)
                delays.append(seconds)

        def worker(command, **kwargs):
            # The existing systemd-inhibit child stays in daemon(), spawning only
            # disposable monitor workers, never another inhibitor/systemd unit.
            self.assertEqual(command, [usb.sys.executable, '-I',
                                      str(Path(usb.__file__).resolve()), 'monitor'])
            workers.append(command)
            try:
                usb.monitor()
            except RuntimeError:
                return Mock(returncode=1)
            return Mock(returncode=0)

        with patch.object(usb, 'STOPPING', False), \
                patch.object(usb, 'locked', return_value=lock), \
                patch.object(usb, 'load', return_value=state), patch.object(usb, 'save'), \
                patch.object(usb, 'current', return_value=now), \
                patch.object(usb, 'MODULE') as mod, patch.object(usb, 'CONF') as conf, \
                patch.object(usb, 'policy', return_value='policy'), \
                patch.object(usb, 'run', side_effect=['original ACL',
                    RuntimeError('setfacl: No such file or directory'), '']) as run, \
                patch.object(usb, 'cleanup') as cleanup, \
                patch.object(usb.subprocess, 'run', side_effect=worker), \
                patch.object(usb.time, 'sleep', side_effect=sleep):
            mod.exists.return_value = False
            conf.read_text.return_value = 'policy'
            usb.daemon()
        self.assertEqual(len(workers), 2)
        self.assertEqual(delays, [1])
        self.assertTrue(state['active'])
        self.assertEqual(state['generation'], 1)
        self.assertEqual(list(state['acls'].values()), ['original ACL\n'])
        self.assertEqual(run.call_count, 3)
        cleanup.assert_not_called()

    def test_unexpected_worker_exit_and_unreadable_state_retain_supervisor(self):
        state = dict(active=True, prepared=True, phase='running', stop=False)
        lock = Mock(__enter__=Mock(), __exit__=Mock(return_value=False))
        delays = []

        def sleep(seconds):
            self.assertEqual(seconds, 1)
            self.assertTrue(state['active'])
            delays.append(seconds)
            if len(delays) == 2:
                state['phase'] = 'stopped'

        with patch.object(usb, 'STOPPING', False), \
                patch.object(usb, 'locked', return_value=lock), \
                patch.object(usb, 'load', side_effect=[state, OSError('state unreadable'),
                                                     state, state, state]), \
                patch.object(usb, 'save'), patch.object(usb, 'cleanup') as cleanup, \
                patch.object(usb.subprocess, 'run', return_value=Mock(returncode=-9)) as worker, \
                patch.object(usb.time, 'sleep', side_effect=sleep):
            usb.daemon()
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(delays, [1, 1])
        cleanup.assert_not_called()


class VMTests(unittest.TestCase):
    def test_cpu_topology_keeps_overrides_in_one_windows_socket(self):
        with patch.dict(vm.os.environ, {'XBOX_OVMF': '/immutable/firmware',
                                        'XBOX_QEMU': '/immutable/qemu'}):
            for cpus in (2, 4, 8, 64):
                with self.subTest(cpus=cpus):
                    root = vm.ET.fromstring(vm.domain_xml(Path('/unused'),
                        dict(name='owned', uuid='session'), Path('/unused/win.iso'), cpus, 8192))
                    self.assertEqual(root.findtext('vcpu'), str(cpus))
                    self.assertEqual(root.find('cpu/topology').attrib,
                                     dict(sockets='1', cores=str(cpus), threads='1'))

    def test_only_official_iso_hosts_and_https(self):
        vm.official_url('https://software.download.prss.microsoft.com/example.iso?token=x')
        for url in ['http://software.download.prss.microsoft.com/a',
                    'https://software.download.prss.microsoft.com.evil.test/a',
                    'https://example.com/windows.iso',
                    'https://user@software.download.prss.microsoft.com/a',
                    'https://software-download.microsoft.com:8443/a']:
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                vm.official_url(url)

    def test_checksum_failure_creates_no_vm_or_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            iso = base / 'input.iso'
            iso.write_bytes(b'not an official ISO')
            args = argparse.Namespace(name='owned', cpus=4, memory=8192, disk=80,
                                      iso=str(iso), sha256='0' * 64)
            with patch.object(vm.os, 'access', return_value=True), \
                    patch.object(vm.platform, 'machine', return_value='x86_64'), \
                    patch.object(vm, 'virsh', return_value=''), patch.object(vm, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
                    vm.provision(base, args)
            self.assertFalse((base / 'vm.json').exists())
            self.assertFalse((base / 'windows.qcow2').exists())
            run.assert_not_called()

    def test_download_checksum_failure_removes_partial(self):
        url = 'https://software.download.prss.microsoft.com/example.iso'
        response = io.BytesIO(b'corrupt fixture, not a real download')
        response.url = url
        opener = Mock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(vm.urllib.request, 'build_opener', return_value=opener):
            base = Path(temp)
            with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
                vm.obtain_iso(base, url, '0' * 64)
            self.assertFalse((base / 'windows.iso.partial').exists())
            self.assertFalse((base / 'windows.iso').exists())

    def test_invalid_checksum_prevents_network_access(self):
        with patch.object(vm.urllib.request, 'build_opener') as opener, self.assertRaises(RuntimeError):
            vm.obtain_iso(Path('/unused'), 'https://software.download.prss.microsoft.com/example.iso', '')
        opener.assert_not_called()

    def test_refuse_existing_unowned_name_before_iso_download(self):
        with tempfile.TemporaryDirectory() as temp:
            args = argparse.Namespace(name='existing', cpus=4, memory=8192, disk=80)
            with patch.object(vm.os, 'access', return_value=True), \
                    patch.object(vm.platform, 'machine', return_value='x86_64'), \
                    patch.object(vm, 'virsh', return_value='existing'), \
                    patch.object(vm, 'obtain_iso') as download, self.assertRaises(RuntimeError):
                vm.provision(Path(temp), args)
            download.assert_not_called()

    def test_idempotent_owned_provision_and_safe_xml(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            args = argparse.Namespace(name='owned', cpus=4, memory=8192, disk=80, iso='unused', sha256='unused')
            names = []
            definitions = []

            def virsh(*command):
                if command[0] == 'list':
                    return '\n'.join(names)
                if command[0] == 'define':
                    names.append('owned')
                    definitions.append(Path(command[1]).read_text())
                    return ''
                if command[0] == 'dumpxml':
                    return definitions[-1]
                raise AssertionError(command)

            env = {'XBOX_OVMF': '/immutable/firmware', 'XBOX_QEMU': '/immutable/qemu'}
            with patch.dict(vm.os.environ, env), patch.object(vm.os, 'access', return_value=True), \
                    patch.object(vm.platform, 'machine', return_value='x86_64'), \
                    patch.object(vm, 'virsh', side_effect=virsh), patch.object(vm, 'run') as run, \
                    patch.object(vm, 'obtain_iso', return_value=base / 'win<&.iso') as download:
                vm.provision(base, args)
                vm.provision(base, args)
            self.assertEqual(len(definitions), 1)
            download.assert_called_once()
            run.assert_called_once()
            root = vm.ET.fromstring(definitions[0])
            self.assertEqual(root.findtext('devices/emulator'), '/immutable/qemu')
            self.assertEqual(root.find('devices/disk/source').attrib['file'], str(base / 'windows.qcow2'))
            self.assertEqual(root.find('devices/tpm/backend').attrib['version'], '2.0')
            self.assertEqual(root.findtext('vcpu'), '4')
            self.assertEqual(root.find('cpu/topology').attrib,
                             dict(sockets='1', cores='4', threads='1'))
            self.assertTrue(root.findtext('os/loader').endswith('OVMF_CODE.ms.fd'))
            self.assertIsNone(root.find('devices/hostdev'))

    def test_uuid_alone_does_not_allow_adoption(self):
        self.assertFalse(vm.owned_xml('<domain><uuid>same</uuid></domain>', {'uuid': 'same'}))

    def test_cold_attach_requires_absence_and_never_restores_xpad(self):
        state = dict(name='owned', uuid='session', qmp=dict(phase='guard-started', physical='exact'))
        root = dict(ready=True, active=False, disarming=False, phase='running',
                    physical='exact', session='session', port='7-4')
        with tempfile.TemporaryDirectory() as temp, patch.object(vm, 'check_owned'), \
                patch.object(vm, 'guard', return_value=root) as guard, patch.object(vm, 'qmp') as qmp, \
                patch.object(vm.Path, 'exists', return_value=False):
            vm.usb_attach(Path(temp), state)
        qmp.assert_called_once_with(state, 'device_add', dict(driver='usb-host', id=vm.QMP_ID,
                                    hostbus=7, hostport='4', bus='usb.0', port='4'))
        guard.assert_called_once_with('status')  # No policy restore after device_add!
        self.assertEqual(state['qmp']['phase'], 'attached')

    def test_cold_attach_refuses_loaded_xpad(self):
        state = dict(uuid='session', qmp=dict(phase='guard-started', physical='exact'))
        root = dict(ready=True, active=False, disarming=False, phase='running',
                    physical='exact', session='session')
        with patch.object(vm, 'check_owned'), patch.object(vm, 'guard', return_value=root), \
                patch.object(vm.Path, 'exists', return_value=True), patch.object(vm, 'qmp') as qmp, \
                self.assertRaisesRegex(RuntimeError, 'xpad'):
            vm.usb_attach(Path('/unused'), state)
        qmp.assert_not_called()

    def test_active_flash_blocks_even_qmp_cleanup(self):
        with patch.object(vm, 'guard', return_value={'active': True, 'session': 'mine'}) as guard, \
                patch.object(vm, 'qmp') as qmp, self.assertRaisesRegex(RuntimeError, 'ACTIVE FLASH'):
            vm.usb_stop(Path('/unused'), {})
        qmp.assert_not_called()
        guard.assert_called_once_with('status')

    def test_cleanup_excludes_arming_before_any_qmp_operation(self):
        calls = []
        state = dict(name='owned', uuid='session', qmp={'phase': 'attach-intent'})

        def guard(action):
            calls.append(action)
            return dict(active=False, session='session')

        def qmp(*_args):
            self.assertIn('disarm', calls)
            calls.append('qmp')
            return ''  # Ambiguous attach-intent with no live device is safe to clear.

        with tempfile.TemporaryDirectory() as temp, patch.object(vm, 'guard', side_effect=guard), \
                patch.object(vm, 'check_owned'), patch.object(vm, 'qmp', side_effect=qmp), \
                patch.object(vm, 'virsh', return_value='running'), \
                patch.object(vm, 'run', return_value='inactive'):
            vm.usb_stop(Path(temp), state)
        self.assertLess(calls.index('disarm'), calls.index('qmp'))
        self.assertLess(calls.index('qmp'), calls.index('stop'))
        self.assertIsNone(state['qmp'])

    def test_confirmed_safe_shutoff_cleanup_does_not_query_dead_qmp(self):
        state = dict(name='owned', uuid='session', qmp={'phase': 'attached'})
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(vm, 'guard', return_value=dict(active=False, session='session')), \
                patch.object(vm, 'check_owned'), patch.object(vm, 'virsh', return_value='shut off'), \
                patch.object(vm, 'qmp') as qmp, patch.object(vm, 'run', return_value='inactive'):
            vm.usb_stop(Path(temp), state)
        qmp.assert_not_called()
        self.assertIsNone(state['qmp'])

    def test_wrong_session_never_detaches_or_stops_guard(self):
        with patch.object(vm, 'guard', return_value=dict(active=False, session='other')) as guard, \
                patch.object(vm, 'qmp') as qmp, self.assertRaises(RuntimeError):
            vm.usb_stop(Path('/unused'), {'uuid': 'mine'})
        qmp.assert_not_called()
        guard.assert_called_once_with('status')

    def test_refused_root_start_clears_only_local_intent(self):
        state = dict(uuid='mine', qmp=dict(phase='start-intent'))
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(vm, 'guard', return_value=dict(active=True, session='other')) as guard, \
                patch.object(vm, 'check_owned'), patch.object(vm, 'qmp') as qmp:
            vm.usb_stop(Path(temp), state)
        guard.assert_called_once_with('status')
        qmp.assert_not_called()
        self.assertIsNone(state['qmp'])

    def test_wizard_library_is_unchanged(self):
        template = Path.home() / '.config/opencode/skills/wizard/template.sh'
        if not template.exists():
            self.skipTest('Shared authoring template not installed')
        wizard = Path(__file__).with_name('wizard.sh').read_text()
        self.assertEqual(wizard.split('run_wizard() {')[0], template.read_text().split('run_wizard() {')[0])


if __name__ == '__main__':
    unittest.main()
