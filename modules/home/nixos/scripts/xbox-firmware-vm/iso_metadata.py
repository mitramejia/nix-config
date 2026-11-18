"""Resolve consumer Windows media through Microsoft's ordinary download page.

No ISO download, browser fingerprint overrides, challenge emulation or mirrors.
The temporary browser profile is discarded; its signed link is never logged.
"""

import argparse
import contextlib
from html.parser import HTMLParser
import json
import os
import re
import select
import socket
import socketserver
import sys
import threading
import time
import urllib.parse
import urllib.request

PAGE = 'https://www.microsoft.com/en-us/software-download/windows11'


class MetadataProxy(socketserver.ThreadingTCPServer):
    """Browser-lifetime destination guard, independent of the CDP connection.

    Only HTTPS CONNECT to metadata hosts is supported. No HTTP forwarding,
    upstream proxy, direct fallback or TLS interception. Fetch remains the
    finer per-request guard; this layer survives its detachment.
    """
    daemon_threads = True

    def __init__(self):
        self.lock = threading.Lock()
        self.revoked = False
        self.tunnels = set()
        super().__init__(('127.0.0.1', 0), MetadataTunnel)

    def revoke(self):
        with self.lock:
            self.revoked = True
            for tunnel in self.tunnels:
                try:
                    tunnel.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


class MetadataTunnel(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        upstream = None
        try:
            line = self.rfile.readline(8193).decode('ascii').strip().split()
            if len(line) != 3:
                return
            method, authority, protocol = line
            # Parse a bare authority, not a URL containing userinfo/path etc.
            if (method != 'CONNECT' or protocol != 'HTTP/1.1'
                    or not re.fullmatch(r'[a-zA-Z0-9.-]+:443', authority)
                    or not metadata_url_allowed('https://' + authority)):
                self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                return
            size = 0
            while True:
                header = self.rfile.readline(8193)
                size += len(header)
                if size > 32768 or not header:
                    return
                if header == b'\r\n':
                    break
            with self.server.lock:
                if self.server.revoked:
                    return
            upstream = socket.create_connection((authority[:-4], 443), timeout=5)
            with self.server.lock:
                if self.server.revoked:
                    return
                self.server.tunnels.update((self.connection, upstream))
            self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            while True:
                readable, _, _ = select.select((self.connection, upstream), (), (), 1)
                with self.server.lock:
                    if self.server.revoked:
                        return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except (OSError, UnicodeError, ValueError):
            pass  # Closed/invalid tunnels never fall back to another route.
        finally:
            with self.server.lock:
                self.server.tunnels.difference_update((self.connection, upstream))
            if upstream is not None:
                upstream.close()


@contextlib.contextmanager
def browser_network(options):
    with MetadataProxy() as proxy:
        worker = threading.Thread(target=proxy.serve_forever, daemon=True)
        worker.start()
        # Fixed proxy has no DIRECT fallback. Chromium otherwise implicitly
        # bypasses loopback; remove that exemption, and disable UDP/QUIC routes.
        options.add_argument(f'--proxy-server=http://127.0.0.1:{proxy.server_address[1]}')
        options.add_argument('--proxy-bypass-list=<-loopback>')
        options.add_argument('--disable-quic')
        # Do not coalesce different HTTPS authorities onto one allowed tunnel.
        options.add_argument('--disable-http2')
        options.add_argument('--force-webrtc-ip-handling-policy=disable_non_proxied_udp')
        try:
            yield proxy
        finally:
            proxy.revoke()
            proxy.shutdown()
            worker.join()


def metadata_url_allowed(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname or ''
        allowed = (parsed.scheme == 'https' and
                   (host == 'microsoft.com' or host.endswith('.microsoft.com')
                    or host == 'ajax.aspnetcdn.com') and parsed.port in (None, 443)
                   and parsed.username is None and parsed.password is None)
    except (ValueError, TypeError):
        return False
    return allowed


@contextlib.contextmanager
def browser_requests(browser, network):
    """CDP Fetch intercepts every request BEFORE sending, including redirects.

    setBlockedURLs skips main-frame navigation; packaged Selenium's BiDi
    interception is incompatible with this Chromium. Use the stable Fetch
    protocol on the driver's existing loopback debugger. The independent
    destination proxy MUST already be configured before starting Chromium.
    On detachment it still blocks forbidden destinations, then revocation
    closes allowed tunnels and quit interrupts the browser's active flow.
    """
    import websocket

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    address = browser.capabilities['goog:chromeOptions']['debuggerAddress']
    require(re.fullmatch(r'(?:localhost|127\.0\.0\.1):[0-9]+', address), 'Nonlocal browser debugger refused')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open('http://' + address + '/json/list', timeout=5) as response:
        require(response.url == 'http://' + address + '/json/list', 'Debugger redirect refused')
        targets = json.loads(response.read(65536))
    matches = [t['webSocketDebuggerUrl'] for t in targets if t['id'] == browser.current_window_handle]
    require(len(matches) == 1 and matches[0].startswith('ws://' + address + '/devtools/page/'),
            'Unexpected browser debug target')
    failed, stopped = threading.Event(), threading.Event()
    try:
        with contextlib.closing(websocket.create_connection(matches[0], timeout=5, suppress_origin=True,
                http_no_proxy=['localhost', '127.0.0.1'], redirect_limit=0)) as connection:
            connection.send(json.dumps(dict(id=1, method='Fetch.enable', params={
                'patterns': [dict(urlPattern='*', requestStage='Request')]})))
            ack = json.loads(connection.recv())
            require(ack.get('id') == 1 and 'result' in ack and 'error' not in ack,
                    'Browser request interception unavailable; stopped')
            connection.settimeout(1)

            def receive():
                next_id = 1
                try:
                    while not stopped.is_set():
                        try:
                            message = json.loads(connection.recv())
                        except websocket.WebSocketTimeoutException:
                            continue
                        if 'error' in message:
                            raise RuntimeError('CDP command failed')
                        if message.get('method') != 'Fetch.requestPaused':
                            continue
                        params = message['params']
                        allowed = metadata_url_allowed(params['request']['url'])
                        next_id += 1
                        arguments = dict(requestId=params['requestId'])
                        if not allowed:
                            arguments['errorReason'] = 'BlockedByClient'
                        connection.send(json.dumps(dict(id=next_id, params=arguments,
                            method='Fetch.continueRequest' if allowed else 'Fetch.failRequest')))
                except Exception:
                    if not stopped.is_set():
                        failed.set()
                        network.revoke()
                        try:
                            browser.quit()
                        except Exception:
                            pass  # Network is already revoked, even if quit fails.

            worker = threading.Thread(target=receive, daemon=True)
            worker.start()
            try:
                yield connection
                require(not failed.is_set(), 'Browser request interception failed; stopped')
            finally:
                stopped.set()
                connection.abort()
                worker.join(timeout=2)
    except websocket.WebSocketException:
        raise RuntimeError('Browser request interception unavailable; stopped') from None


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Page(HTMLParser):
    """Only the edition selector and publisher's language/hash rows matter."""

    def __init__(self, html):
        super().__init__()
        self.editions = []
        self.rows = []
        self.selector = False
        self.option = None
        self.row = None
        self.cell = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select':
            self.selector = attrs.get('id') == 'product-edition'
        if tag == 'option' and self.selector:
            self.option = [attrs.get('value', ''), '']
        if tag == 'tr':
            self.row = []
        if tag == 'td' and self.row is not None:
            self.cell = ''

    def handle_data(self, data):
        if self.option is not None:
            self.option[1] += data
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag):
        if tag == 'select':
            self.selector = False
        if tag == 'option' and self.option is not None:
            self.editions.append(self.option)
            self.option = None
        if tag == 'td' and self.cell is not None:
            self.row.append(' '.join(self.cell.split()))
            self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def edition(self):
        choices = [(key, text.strip()) for key, text in self.editions
                   if key.isdigit() and text.strip() ==
                   'Windows 11 (multi-edition ISO for x64 devices)']
        require(len(choices) == 1, 'Microsoft edition selector changed; refusing ambiguous/non-consumer media')
        return choices[0]

    def digest(self, label):
        hashes = [row[1].lower() for row in self.rows if len(row) == 2
                  and row[0] == label + ' 64-bit' and re.fullmatch('[0-9A-Fa-f]{64}', row[1])]
        require(len(hashes) == 1, 'No unique matching publisher SHA256 on Microsoft page; strict verification retained')
        return hashes[0]


def language_option(options, language):
    choices = []
    for value, label in options:
        if value in ('null', ''):
            continue
        try:
            sku = json.loads(value)
        except (ValueError, TypeError):
            raise RuntimeError('Microsoft language selector schema changed') from None
        if sku.get('language') == language:
            require(str(sku.get('id', '')).isdigit(), 'Invalid Microsoft SKU')
            choices.append((value, label.strip(), str(sku['id'])))
    require(len(choices) == 1, 'Language not uniquely offered by Microsoft; use --language with its exact language name')
    return choices[0]


def validate_link(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname in
            ('software.download.prss.microsoft.com', 'software-download.microsoft.com')
            and parsed.username is None and parsed.password is None
            and parsed.port in (None, 443) and not parsed.fragment
            and re.search(r'/(?:Win11_.*_x64|Windows11_Client_x64_[a-z]{2}-[a-z]{2}_[0-9_]+)\.iso$',
                          urllib.parse.unquote(parsed.path), re.I),
            'Microsoft did not offer an allowed HTTPS x64 ISO link')
    return url


def link_expiry(url):
    # Current official signed links use P1 as a Unix expiry. Fail closed if
    # that protocol changes; never reuse a link just because it still exists.
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get('P1', [])
    require(len(values) == 1 and values[0].isdigit(), 'Unknown Microsoft link expiry schema')
    expires = int(values[0])
    require(time.time() + 300 < expires <= time.time() + 25 * 3600,
            'Microsoft link is expired, nearly expired or has an unexpected lifetime; retry discovery')
    return expires


def check_reply(data):
    if data is None:
        return
    require(isinstance(data, dict), 'Microsoft response schema changed')
    if data.get('Errors'):
        errors = data['Errors']
        restricted = isinstance(errors, list) and any(
            isinstance(e, dict) and (e.get('Type') in (8, 9) or 'Sentinel' in str(e.get('Key', '')))
            for e in errors)
        raise RuntimeError(('Microsoft rejected this session (SentinelReject/access restriction). ' if restricted
                            else 'Microsoft returned a download service error. ') +
                           'No download or VM creation. Try later on your normal connection or use '
                           '--iso /path/to/official.iso --sha256 PUBLISHER_SHA256. No bypass attempted.')


def page_options(browser):
    check_reply(browser.execute_script('return window.__xboxReply || null'))
    return browser.execute_script('return [...document.querySelectorAll("#product-languages option")].map(o => [o.value, o.textContent])')


def page_links(browser):
    check_reply(browser.execute_script('return window.__xboxReply || null'))
    return browser.execute_script('return [...document.querySelectorAll("#download-links a[href]")].filter(a => a.textContent.includes("64-bit")).map(a => a.href)')


def resolve(language):
    # Lazy imports keep the parser tests hardware/browser-free.
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select, WebDriverWait

    options = webdriver.ChromeOptions()
    options.binary_location = os.environ['XBOX_CHROMIUM']
    options.add_argument('--headless=new')
    # Do not disable the sandbox, spoof the UA, reuse personal profiles or
    # defeat automation detection. Let Microsoft's own page initialize session.
    try:
        with browser_network(options) as network, \
                webdriver.Chrome(service=Service(os.environ['XBOX_CHROMEDRIVER'],
                log_output=os.devnull), options=options) as browser, browser_requests(browser, network):
            browser.set_page_load_timeout(45)
            browser.get(PAGE)
            require(browser.current_url == PAGE, 'Unexpected Microsoft page redirect; stopped')
            wait = WebDriverWait(browser, 25)
            wait.until(lambda b: b.find_elements(By.CSS_SELECTOR, '#product-edition option[value]'))
            page = Page(browser.page_source)
            edition, title = page.edition()
            wait.until(lambda b: b.execute_script('return typeof window.jQuery === "function"'))
            # Observe the page's ordinary responses, without altering requests,
            # so HTTP-200 Errors/SentinelReject fail early rather than hanging.
            browser.execute_script('''
                window.__xboxReply = null;
                jQuery(document).ajaxSuccess(function(event, xhr, settings, data) {
                    if (settings.url.startsWith('https://www.microsoft.com/software-download-connector/api/'))
                        window.__xboxReply = data;
                });
            ''')
            Select(browser.find_element(By.ID, 'product-edition')).select_by_value(edition)
            browser.find_element(By.ID, 'submit-product-edition').click()
            wait.until(lambda b: len(page_options(b)) > 1)
            selector = Select(browser.find_element(By.ID, 'product-languages'))
            value, label, sku = language_option(
                [(o.get_attribute('value'), o.text) for o in selector.options], language)
            # The US label differs between selector and hash table; other
            # languages use their official display label (e.g. English International).
            hash_label = 'English' if language == 'English' else label
            expected = page.digest(hash_label)
            selector.select_by_value(value)
            browser.execute_script('window.__xboxReply = null')
            browser.find_element(By.ID, 'submit-sku').click()
            # Never click the download: discovery must not transfer multi-GB media.
            links = wait.until(page_links)
            require(browser.current_url == PAGE and len(set(links)) == 1,
                    'Ambiguous Microsoft download response')
            url = validate_link(links[0])
            require(Page(browser.page_source).digest(hash_label) == expected,
                    'Publisher hash changed during selection; retry later')
            return dict(url=url, sha256=expected, language=language, edition=title, expires_at=link_expiry(url),
                        product_id=edition, sku=sku, architecture='x64', publisher_page=PAGE)
    except WebDriverException:
        raise RuntimeError('Microsoft automatic link discovery failed or was restricted (including SentinelReject). '
                           'No download or VM creation. Try later on your normal connection, or use '
                           '--iso /path/to/official.iso --sha256 PUBLISHER_SHA256. '
                           'No CAPTCHA/access restriction bypass is attempted.') from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', default='English', help='Exact Microsoft language name; English is US')
    args = parser.parse_args()
    try:
        print(json.dumps(resolve(args.language)))
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
