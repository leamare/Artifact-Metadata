"""Minimal Chrome DevTools Protocol client (stdlib only) for headless screenshots.

    with Browser() as b:
        png = b.screenshot('http://127.0.0.1:8000/ui/render/render.html?id=10001', 526, 890)
"""
from __future__ import annotations

import base64
import json
import os
import random
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

CHROME = next((c for c in ('google-chrome-stable', 'google-chrome', 'chromium', 'chromium-browser')
               if shutil.which(c)), None)


FONTS_CONF = '''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <match target="font">
    <edit name="hinting" mode="assign"><bool>false</bool></edit>
    <edit name="hintstyle" mode="assign"><const>hintnone</const></edit>
    <edit name="antialias" mode="assign"><bool>true</bool></edit>
    <edit name="rgba" mode="assign"><const>none</const></edit>
  </match>
</fontconfig>
'''


class WebSocket:
    def __init__(self, url):
        assert url.startswith('ws://')
        hostport, path = url[5:].split('/', 1)
        host, port = hostport.split(':')
        self.sock = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n'
                           f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n'
                           'Sec-WebSocket-Version: 13\r\n\r\n').encode())
        resp = b''
        while b'\r\n\r\n' not in resp:
            resp += self.sock.recv(4096)
        if b' 101 ' not in resp.split(b'\r\n', 1)[0]:
            raise ConnectionError(resp[:200])
        self.buf = resp.split(b'\r\n\r\n', 1)[1]

    def send(self, text):
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack('>H', n)
        else:
            header += bytes([0x80 | 127]) + struct.pack('>Q', n)
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(1 << 20)
            if not chunk:
                raise ConnectionError('websocket closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        message = b''
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            payload = self._read(n)
            message += payload
            if b0 & 0x80:
                return message.decode()


class Browser:
    def __init__(self, width=526, height=890):
        self.profile = tempfile.mkdtemp(prefix='cdp-')
        port = random.randint(20000, 40000)
        self.proc = subprocess.Popen(
            [CHROME, '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
             f'--remote-debugging-port={port}', f'--user-data-dir={self.profile}',
             f'--window-size={width},{height}', '--force-device-scale-factor=1',
             'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self._env())
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json'))
                page = next(t for t in tabs if t['type'] == 'page')
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError('chrome did not start')
        self.ws = WebSocket(page['webSocketDebuggerUrl'])
        self.next_id = 0
        self.call('Page.enable')
        self.call('Runtime.enable')
        self.call('Emulation.setDefaultBackgroundColorOverride', color={'r': 0, 'g': 0, 'b': 0, 'a': 0})

    def _env(self):
        """Valve's renders have unhinted, greyscale-antialiased text; Chrome on Linux takes its
        font rendering from fontconfig, so give it a configuration that says so."""
        conf = os.path.join(self.profile, 'fonts.conf')
        with open(conf, 'w') as f:
            f.write(FONTS_CONF)
        return {**os.environ, 'FONTCONFIG_FILE': conf}

    def call(self, method, **params):
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise RuntimeError(f'{method}: {msg["error"]}')
                return msg.get('result', {})

    def evaluate(self, expr):
        return self.call('Runtime.evaluate', expression=expr, returnByValue=True).get('result', {}).get('value')

    def screenshot(self, url, width=526, height=890, timeout=20, scale=1.0):
        """PNG of the page's width x height CSS pixels, rendered at scale (2 = twice the pixels)."""
        self.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=scale, mobile=False)
        self.call('Page.navigate', url=url)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.evaluate('window.renderDone === true'):
                break
            time.sleep(0.05)
        else:
            raise TimeoutError(url)
        shot = self.call('Page.captureScreenshot', format='png',
                         clip={'x': 0, 'y': 0, 'width': width, 'height': height, 'scale': 1})
        return base64.b64decode(shot['data'])

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(5)
        finally:
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
