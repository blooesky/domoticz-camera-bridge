"""Camera Bridge runtime. Standard library only; no Domoticz calls from threads."""
import datetime
import http.server
import json
import os
import select
import subprocess
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit


def camera_url(url, username='', password=''):
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in ('rtsp', 'rtsps') or not parsed.hostname:
        raise ValueError('Enter a complete rtsp:// or rtsps:// camera URL')
    if parsed.fragment:
        raise ValueError('Use separate Username/Password fields for special characters')
    # Validate port without ever echoing credentials in errors.
    try:
        parsed.port
    except ValueError:
        raise ValueError('Invalid RTSP port') from None
    if username:
        host = parsed.netloc.rsplit('@', 1)[-1]
        auth = quote(username, safe='') + ':' + quote(password, safe='')
        parsed = parsed._replace(netloc=auth + '@' + host)
    return urlunsplit(parsed)


class Capture:
    def __init__(self, ffmpeg, url, transport='tcp', interval=1,
                 idle_timeout=10, enabled=True):
        self.command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin',
                        '-rtsp_transport', transport, '-threads', '2', '-i', url,
                        '-map', '0:v:0', '-an', '-sn', '-dn',
                        '-vf', 'fps=1/{}'.format(interval), '-c:v', 'mjpeg',
                        '-q:v', '4', '-threads', '1', '-f', 'image2pipe',
                        '-flush_packets', '1', 'pipe:1']
        self.interval = interval
        self.idle_timeout = idle_timeout
        self.cv = threading.Condition()
        self.stop_event = threading.Event()
        self.enabled = enabled
        self.last_request = float('-inf')
        self.frame = None
        self.frame_time = 0.0
        self.last_snapshot = 'Never'
        self.state = 'Idle' if enabled else 'Disabled'
        self.detail = ''
        self.pid = None
        self.thread = threading.Thread(target=self._run, name='CameraBridge capture', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop_event.set()
        with self.cv:
            self.cv.notify_all()
        if self.thread.is_alive():
            self.thread.join(5)

    def set_enabled(self, value):
        with self.cv:
            self.enabled = value
            self.frame = None
            self.last_request = float('-inf')
            self.cv.notify_all()

    def trigger(self):
        with self.cv:
            if self.enabled and not self.stop_event.is_set():
                self.last_request = time.monotonic()
                self.cv.notify_all()

    def snapshot(self, timeout):
        with self.cv:
            if not self.enabled or self.stop_event.is_set():
                return None
            now = time.monotonic()
            # A new viewing session must never return an image from an old session.
            if now - self.last_request >= self.idle_timeout:
                self.frame = None
            self.last_request = now
            self.cv.notify_all()
            deadline = now + timeout
            while self.enabled and not self.stop_event.is_set():
                now = time.monotonic()
                if self.frame is not None and now - self.frame_time <= self.interval + 1:
                    return self.frame
                remaining = deadline - now
                if remaining <= 0:
                    break
                self.cv.wait(min(remaining, 0.25))
            return None

    def status(self):
        with self.cv:
            return dict(state=self.state, detail=self.detail, enabled=self.enabled,
                        last_snapshot=self.last_snapshot, ffmpeg_running=self.pid is not None)

    def _state(self, state, detail=''):
        with self.cv:
            self.state, self.detail = state, detail
            self.cv.notify_all()

    @staticmethod
    def _terminate(proc):
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)
        finally:
            if proc.stdout:
                proc.stdout.close()

    def _run(self):
        proc = None
        buffer = bytearray()
        retry_at = 0.0
        last_data = 0.0
        try:
            while not self.stop_event.is_set():
                now = time.monotonic()
                with self.cv:
                    active = self.enabled and now - self.last_request < self.idle_timeout
                    enabled = self.enabled
                if not active:
                    if proc is not None:
                        self._terminate(proc)
                        proc = None
                    with self.cv:
                        self.pid = None
                        self.frame = None
                    buffer.clear()
                    retry_at = 0.0
                    self._state('Idle' if enabled else 'Disabled')
                    self.stop_event.wait(0.1)
                    continue
                if proc is None:
                    if now < retry_at:
                        self.stop_event.wait(0.1)
                        continue
                    self._state('Connecting')
                    try:
                        # No shell and no preexec_fn (Domoticz uses embedded Python).
                        # Raw stderr may contain passwords, so never forward it to logs.
                        proc = subprocess.Popen(self.command, stdin=subprocess.DEVNULL,
                                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                bufsize=0, close_fds=True)
                    except OSError:
                        self._state('Error', 'Cannot start local FFmpeg; check install.sh and permissions')
                        retry_at = now + 3
                        continue
                    with self.cv:
                        self.pid = proc.pid
                        self.frame = None
                    buffer.clear()
                    last_data = now
                ready, _, _ = select.select([proc.stdout], [], [], 0.15)
                if ready:
                    chunk = os.read(proc.stdout.fileno(), 65536)
                    if chunk:
                        buffer.extend(chunk)
                        while True:
                            start = buffer.find(b'\xff\xd8')
                            if start < 0:
                                if len(buffer) > 1:
                                    del buffer[:-1]
                                break
                            if start:
                                del buffer[:start]
                            end = buffer.find(b'\xff\xd9', 2)
                            if end < 0:
                                break
                            jpeg = bytes(buffer[:end + 2])
                            del buffer[:end + 2]
                            last_data = time.monotonic()
                            with self.cv:
                                self.frame, self.frame_time = jpeg, last_data
                                self.last_snapshot = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
                                self.state, self.detail = 'Streaming', ''
                                self.cv.notify_all()
                        if len(buffer) > 16 * 1024 * 1024:
                            raise RuntimeError('Frame buffer limit exceeded')
                if proc.poll() is not None or time.monotonic() - last_data > 15:
                    self._terminate(proc)
                    proc = None
                    with self.cv:
                        self.pid = None
                        self.frame = None
                    self._state('Error', 'No video frame; check RTSP URL, credentials, codec and camera access')
                    retry_at = time.monotonic() + 3
        except Exception:
            self._state('Error', 'Capture worker stopped unexpectedly; disable and re-enable hardware')
        finally:
            self._terminate(proc)
            with self.cv:
                self.pid = None
                self.frame = None
                self.cv.notify_all()


class SnapshotServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port, capture, wait_timeout=8):
        self.capture = capture
        self.wait_timeout = wait_timeout
        self.slots = threading.BoundedSemaphore(12)
        # Intentionally loopback only: Domoticz proxies the image for local/remote viewers.
        super().__init__(('127.0.0.1', port), SnapshotHandler)
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': 0.1},
                                       name='CameraBridge HTTP', daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        if self.thread.is_alive():
            self.shutdown()
            self.thread.join(2)
        self.server_close()

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        pass


class SnapshotHandler(http.server.BaseHTTPRequestHandler):
    server_version = 'CameraBridge/1.0.0'
    sys_version = ''

    def setup(self):
        self.request.settimeout(12)
        super().setup()

    def log_message(self, format, *args):
        pass

    def _reply(self, code, data, mime, head=False):
        try:
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.send_header('Connection', 'close')
            if code == 503:
                self.send_header('Retry-After', '1')
            self.end_headers()
            if not head:
                self.wfile.write(data)
        except (OSError, TimeoutError):
            pass

    def do_HEAD(self):
        # Health checks must not accidentally start a capture.
        if urlsplit(self.path).path in ('/snapshot.jpg', '/status.json'):
            self._reply(200, b'', 'text/plain', True)
        else:
            self._reply(404, b'', 'text/plain', True)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/snapshot.jpg':
            jpeg = self.server.capture.snapshot(self.server.wait_timeout)
            if jpeg is None:
                self._reply(503, b'Camera image unavailable; retry shortly.\n', 'text/plain')
            else:
                self._reply(200, jpeg, 'image/jpeg')
        elif path == '/status.json':
            data = json.dumps(self.server.capture.status()).encode('utf-8')
            self._reply(200, data, 'application/json')
        else:
            self._reply(404, b'Not found\n', 'text/plain')
