"""Offline fixtures from the Microsoft consumer page/API, checked 2026-11-18.

No signed tokens, network, browser, guest execution or multi-GB downloads.
"""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_vm import module, vm

metadata = module('iso_metadata')
HASH = 'BD4307DF32BC8AF33B39CCECB1174AEB345386630F89A2B86C7A4E36B55EA650'
HTML = '''<select id="product-edition"><option value="null">Select Download</option>
<option value="3813">Windows 11 (multi-edition ISO for x64 devices)</option></select>
<table><tr><td>English International 64-bit</td>
<td>7E3F373BD3C2321B5D5125DFCF718DFBF1A0ABC50A267118669951890DF98A5D</td></tr>
<tr><td>English 64-bit</td><td>''' + HASH + '''</td></tr></table>'''
OPTIONS = [('null', 'Select one'), ('{"id":"27160","language":"English"}', 'English (United States)'),
           ('{"id":"27128","language":"English (United Kingdom)"}', 'English International')]
URL = 'https://software.download.prss.microsoft.com/dbazure/Windows11_Client_x64_en-us_26300_9457.iso?P1=87400'


class MetadataTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('XBOX_BROWSER_TEST') == '1', 'Opt-in local browser/network guard test')
    def test_real_browser_blocks_initial_and_redirect_before_contact(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import threading
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException
        from selenium.webdriver.chrome.service import Service

        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append(self.path)
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/evil')
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'http://127.0.0.1:{server.server_port}/redirect'
        original = metadata.metadata_url_allowed
        for permit_initial in (False, True):
            options = webdriver.ChromeOptions()
            options.binary_location = os.environ['XBOX_CHROMIUM']
            options.add_argument('--headless=new')
            # Test-only permission for the initial local endpoint. The real
            # production policy must still block its redirect before contact.
            with patch.object(metadata, 'metadata_url_allowed',
                              side_effect=lambda u: (permit_initial and u == url) or original(u)), \
                    webdriver.Chrome(service=Service(os.environ['XBOX_CHROMEDRIVER']), options=options) as browser, \
                    metadata.browser_requests(browser, Mock()):
                browser.set_page_load_timeout(15)
                try:
                    browser.get(url)
                except WebDriverException:
                    pass  # Chromium may instead return its blocked error page.
                if permit_initial:
                    self.assertTrue(calls)
                    self.assertEqual(set(calls), {'/redirect'})
                else:
                    self.assertEqual(calls, [])

    def test_browser_requests_and_redirect_hops_are_allowlisted(self):
        for url, allowed in [(metadata.PAGE, True), ('https://ov-df.microsoft.com/mdt.js', True),
                             ('https://ajax.aspnetcdn.com/ajax/jquery.js', True),
                             ('https://microsoft.com.evil.test/', False),
                             ('https://user@www.microsoft.com/', False),
                             ('http://www.microsoft.com/', False),
                             ('https://www.microsoft.com:8443/', False),
                             ('https://www.microsoft.com:invalid/', False),
                             ('http://127.0.0.1/', False)]:
            with self.subTest(url=url):
                self.assertEqual(metadata.metadata_url_allowed(url), allowed)

    def test_official_page_dynamic_edition_and_language_hash_binding(self):
        page = metadata.Page(HTML.replace('3813', '99999'))
        self.assertEqual(page.edition()[0], '99999')
        self.assertEqual(page.digest('English'), HASH.lower())
        self.assertNotEqual(page.digest('English International'), HASH.lower())
        self.assertEqual(metadata.language_option(OPTIONS, 'English')[2], '27160')
        self.assertEqual(metadata.language_option(OPTIONS, 'English (United Kingdom)')[2], '27128')

    def test_missing_duplicate_or_wrong_arch_hash_fails_closed(self):
        for html in (HTML.replace('English 64-bit', 'English 32-bit'), HTML + HTML,
                     HTML.replace(HASH, 'not-a-hash')):
            with self.subTest(html=html), self.assertRaises(RuntimeError):
                metadata.Page(html).digest('English')

    def test_edition_drift_and_evaluation_refused(self):
        for html in (HTML.replace('x64 devices', 'ARM64 devices'), HTML + HTML,
                     HTML.replace('multi-edition ISO for x64 devices', 'Enterprise Evaluation')):
            with self.subTest(html=html), self.assertRaises(RuntimeError):
                metadata.Page(html).edition()

    def test_language_schema_and_missing_ambiguous_sku(self):
        for options in (OPTIONS + [OPTIONS[1]], [('bad JSON', 'English')],
                        [('{"id":"evil","language":"English"}', 'English')], []):
            with self.subTest(options=options), self.assertRaises(RuntimeError):
                metadata.language_option(options, 'English')

    def test_actual_sentinel_error_is_recognized_without_logging_value(self):
        # Actual response to a plain UUID session request, HTTP 200.
        reply = {'Errors': [{'Key': 'ErrorSettings.SentinelReject',
                             'Value': 'Sentinel marked this request as rejected.', 'Type': 8}]}
        with self.assertRaisesRegex(RuntimeError, 'SentinelReject/access restriction'):
            metadata.check_reply(reply)
        metadata.check_reply({'Skus': []})
        metadata.check_reply(None)
        for data in ([], {'Errors': [{'Value': 'secret signed token'}]}):
            with self.assertRaises(RuntimeError) as error:
                metadata.check_reply(data)
            self.assertNotIn('secret signed token', str(error.exception))

    def test_actual_link_path_and_expiry_validation(self):
        self.assertEqual(metadata.validate_link(URL), URL)
        with patch.object(metadata.time, 'time', return_value=1000):
            self.assertEqual(metadata.link_expiry(URL), 87400)
            for url in (URL.replace('87400', '1000'), URL.replace('87400', '999999'),
                        URL.replace('P1=', 'unknown='), URL + '&P1=87400'):
                with self.subTest(url=url), self.assertRaises(RuntimeError):
                    metadata.link_expiry(url)

    def test_evil_links_and_non_x64_media_refused(self):
        for url in (URL.replace('https:', 'http:'), URL.replace('.com/', '.com.evil.test/'),
                    URL.replace('://', '://user@'), URL.replace('.com/', '.com:8443/'),
                    URL.replace('_x64_', '_arm64_'), URL + '#fragment'):
            with self.subTest(url=url), self.assertRaises(RuntimeError):
                metadata.validate_link(url)

    def test_download_redirect_validation_happens_before_following(self):
        with self.assertRaises(RuntimeError):
            vm.OfficialRedirect().redirect_request(Mock(), None, 302, '', {}, 'https://evil.test/x.iso')

    def test_discovery_timeout_has_no_retry_and_no_signed_url_in_error(self):
        process = Mock(pid=999999)
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.communicate.side_effect = [subprocess.TimeoutExpired('secret', 150), ('', '')]
        with patch.dict(vm.os.environ, XBOX_ISO_RESOLVER='/immutable/resolver'), \
                patch.object(vm.subprocess, 'Popen', return_value=process) as run, \
                patch.object(vm.os, 'killpg') as kill:
            with self.assertRaisesRegex(RuntimeError, 'discovery interrupted/timed out'):
                vm.discover_iso('English')
            self.assertEqual(run.call_count, 1)
            self.assertTrue(run.call_args.kwargs['start_new_session'])
            self.assertEqual(process.communicate.call_args_list[0].kwargs['timeout'], 150)
            kill.assert_called_once_with(999999, vm.signal.SIGKILL)

    def test_verified_local_cache_reuse_and_provenance_without_url(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            iso = base / 'windows.iso'
            iso.write_bytes(b'fixture media')
            expected = hashlib.sha256(iso.read_bytes()).hexdigest()
            reply = dict(url=URL, sha256=expected, language='English', architecture='x64',
                         publisher_page=metadata.PAGE)
            with patch.object(vm, 'discover_iso', return_value=reply) as discover, \
                    patch.object(vm, 'obtain_iso', return_value=iso):
                vm.automatic_iso(base, 'English')
                receipt = json.loads((base / 'iso-provenance.json').read_text())
                self.assertNotIn('url', receipt)
                self.assertEqual(receipt['sha256'], expected)
                vm.automatic_iso(base, 'English')
                self.assertEqual(discover.call_count, 1)
                iso.write_bytes(b'corrupted')
                with self.assertRaisesRegex(RuntimeError, 'SHA256 mismatch'):
                    vm.automatic_iso(base, 'English')

    def test_expired_resolver_metadata_never_reaches_download(self):
        reply = dict(url=URL, sha256=HASH.lower(), language='English', architecture='x64',
                     publisher_page=metadata.PAGE, expires_at=0)
        process = Mock(returncode=0)
        process.__enter__ = Mock(return_value=process)
        process.__exit__ = Mock(return_value=False)
        process.communicate.return_value = (json.dumps(reply), '')
        with patch.dict(vm.os.environ, XBOX_ISO_RESOLVER='/immutable/resolver'), \
                patch.object(vm.subprocess, 'Popen', return_value=process), \
                self.assertRaisesRegex(RuntimeError, 'Invalid publisher metadata'):
            vm.discover_iso('English')

    def test_provision_defaults_to_automatic_without_manual_iso(self):
        from argparse import Namespace
        args = Namespace(name='owned', cpus=4, memory=8192, disk=80,
                         iso=None, sha256=None, language='English')
        with tempfile.TemporaryDirectory() as temp, \
                patch.dict(vm.os.environ, XBOX_OVMF='/immutable/ovmf', XBOX_QEMU='/immutable/qemu'), \
                patch.object(vm.os, 'access', return_value=True), \
                patch.object(vm.platform, 'machine', return_value='x86_64'), \
                patch.object(vm, 'virsh', return_value=''), patch.object(vm, 'check_owned'), \
                patch.object(vm, 'run', return_value='{"format":"qcow2"}'), \
                patch.object(vm, 'automatic_iso', return_value=Path('/unused/windows.iso')) as auto, \
                patch.object(vm, 'obtain_iso') as manual:
            vm.provision(Path(temp), args)
            auto.assert_called_once_with(Path(temp), 'English')
            manual.assert_not_called()

    def test_failed_download_never_issues_a_verified_receipt(self):
        with tempfile.TemporaryDirectory() as temp, \
                patch.object(vm, 'discover_iso', return_value=dict(url=URL, sha256=HASH.lower())), \
                patch.object(vm, 'obtain_iso', side_effect=RuntimeError('mismatch')):
            with self.assertRaises(RuntimeError):
                vm.automatic_iso(Path(temp), 'English')
            self.assertFalse((Path(temp) / 'iso-provenance.json').exists())

    def test_wizard_default_has_no_url_or_hash_prompt(self):
        wizard = Path(__file__).with_name('wizard.sh').read_text().split('run_wizard() {')[1]
        self.assertNotIn('ask ISO_SOURCE', wizard)
        self.assertNotIn('ask ISO_SHA256', wizard)
        self.assertIn('provision --name "$VM_NAME"\n', wizard)

    def test_tools_media_is_readonly_sata_without_guest_exec_channel(self):
        with patch.dict(vm.os.environ, XBOX_OVMF='/immutable/ovmf', XBOX_QEMU='/immutable/qemu',
                        XBOX_GUEST_TOOLS='/immutable/tools.iso'):
            root = vm.ET.fromstring(vm.domain_xml(Path('/unused'), dict(name='owned', uuid='same'),
                                                Path('/unused/windows.iso'), 4, 8192))
        tools = next(
            disk for disk in root.findall('devices/disk')
            if disk.find('source').get('file') == '/immutable/tools.iso')
        self.assertEqual(tools.get('device'), 'cdrom')
        self.assertIsNotNone(tools.find('readonly'))
        self.assertEqual(tools.find('target').attrib, dict(dev='sdc', bus='sata'))
        self.assertIsNone(root.find('devices/channel'))
        helper = Path(__file__).with_name('guest-tools.cmd').read_text()
        self.assertIn('ms-windows-store://pdp/?ProductId=9NBLGGH30XJ3', helper)
        self.assertNotIn('ExecutionPolicy', helper)


if __name__ == '__main__':
    unittest.main()
