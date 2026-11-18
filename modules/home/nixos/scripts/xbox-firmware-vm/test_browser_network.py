"""Opt-in packaged Chromium tests; all upstream traffic stays on loopback."""
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_iso_metadata import metadata


@unittest.skipUnless(os.environ.get('XBOX_BROWSER_TEST') == '1', 'Opt-in local Chromium test')
class BrowserNetworkTests(unittest.TestCase):
    def setUp(self):
        from selenium import webdriver
        self.calls = []
        calls = self.calls

        class Handler(BaseHTTPRequestHandler):
            def handle(self):
                try:
                    super().handle()
                except OSError:
                    pass  # Revocation deliberately closes active TLS sockets.

            def do_GET(self):
                calls.append(self.path)
                self.send_response(302 if self.path == '/redirect' else 200)
                if self.path == '/redirect':
                    self.send_header('Location', forbidden)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *_args):
                pass

        plain = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        forbidden = f'http://127.0.0.1:{plain.server_port}/disallowed'
        self.forbidden = forbidden
        temp = self.enterContext(tempfile.TemporaryDirectory())
        cert, key = (str(Path(temp) / name) for name in ('cert.pem', 'key.pem'))
        subprocess.run([os.environ.get('XBOX_OPENSSL', 'openssl'), 'req', '-x509', '-newkey',
                        'rsa:2048', '-nodes', '-keyout', key, '-out', cert, '-days', '1',
                        '-subj', '/CN=www.microsoft.com'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tls = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        tls.socket = context.wrap_socket(tls.socket, server_side=True)
        for server in (plain, tls):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

        # Only the proxy's outbound CONNECT is mapped to the TLS fixture.
        # All other outbound connections fail: these tests cannot reach Microsoft.
        connect = socket.create_connection

        def local_connect(address, *args, **kwargs):
            if address == ('www.microsoft.com', 443):
                address = ('127.0.0.1', tls.server_port)
            elif address[0] not in ('localhost', '127.0.0.1'):
                raise OSError('Nonlocal test connection refused')
            return connect(address, *args, **kwargs)

        self.enterContext(patch.object(metadata.socket, 'create_connection', side_effect=local_connect))
        self.options = webdriver.ChromeOptions()
        self.options.binary_location = os.environ['XBOX_CHROMIUM']
        self.options.add_argument('--headless=new')
        # Fixture certificate only; production verification remains enabled.
        self.options.add_argument('--ignore-certificate-errors')

    @contextlib.contextmanager
    def browser(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        with metadata.browser_network(self.options) as network, \
                webdriver.Chrome(service=Service(os.environ['XBOX_CHROMEDRIVER'],
                                  log_output=os.devnull), options=self.options) as browser:
            browser.set_page_load_timeout(10)
            yield browser, network

    def navigate(self, browser, url):
        from selenium.common.exceptions import WebDriverException
        try:
            browser.get(url)
        except WebDriverException:
            pass  # Either a network error or Chromium's internal error page.

    def test_proxy_alone_blocks_initial_and_redirect_without_cdp(self):
        with self.browser() as (browser, _network):
            self.navigate(browser, self.forbidden)
            self.assertEqual(self.calls, [])
            self.navigate(browser, 'https://www.microsoft.com/redirect')
            self.assertIn('/redirect', self.calls)
            self.assertNotIn('/disallowed', self.calls)
            self.navigate(browser, self.forbidden.replace('http:', 'https:'))
            self.assertNotIn('/disallowed', self.calls)

    def test_disconnect_during_active_interception_cannot_contact_forbidden(self):
        paused, resume = threading.Event(), threading.Event()
        original = metadata.metadata_url_allowed

        def policy(url):
            if url == 'https://www.microsoft.com/paused':
                paused.set()
                if not resume.wait(15):
                    raise RuntimeError('Test reader release timed out')
            return original(url)

        with self.browser() as (browser, network):
            # Delay the CDP reader deliberately: neither its failure signal nor
            # quit can protect the following navigation. The proxy must do so.
            with self.assertRaisesRegex(RuntimeError, 'interception failed'), \
                    patch.object(metadata, 'metadata_url_allowed', side_effect=policy), \
                    metadata.browser_requests(browser, network) as connection:
                try:
                    browser.execute_script("setTimeout(() => { location.href = 'https://www.microsoft.com/paused' }, 250)")
                    self.assertTrue(paused.wait(5), 'Fetch never paused the active navigation')
                    connection.close()
                    self.navigate(browser, self.forbidden)
                    self.assertNotIn('/disallowed', self.calls)
                    # Leave the context open: abort must occur on the reader,
                    # not only when the context manager eventually exits.
                    resume.set()
                    for _ in range(100):
                        if network.revoked:
                            break
                        threading.Event().wait(.05)
                    self.assertTrue(network.revoked, 'Disconnect did not revoke network')
                    for _ in range(100):
                        if browser.service.process.poll() is not None:
                            break
                        threading.Event().wait(.05)
                    self.assertIsNotNone(browser.service.process.poll(),
                                         'Disconnect did not abort the browser before context exit')
                finally:
                    resume.set()


if __name__ == '__main__':
    unittest.main()
