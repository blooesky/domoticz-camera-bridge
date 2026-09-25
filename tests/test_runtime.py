import concurrent.futures
import importlib.util
import pathlib
import shutil
import sys
import tempfile
import time
import types
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from camera_bridge import Capture, SnapshotServer, camera_url


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.capture = Capture('/usr/bin/ffmpeg', 'rtsp://invalid', idle_timeout=1.5)
        # Real FFmpeg generates changing JPEGs from a synthetic source; no camera required.
        self.capture.command = [shutil.which('ffmpeg'), '-hide_banner', '-loglevel', 'error',
                                '-nostdin', '-re', '-f', 'lavfi', '-i', 'testsrc=size=160x120:rate=4',
                                '-c:v', 'mjpeg', '-threads', '1', '-f', 'image2pipe',
                                '-flush_packets', '1', 'pipe:1']
        self.server = SnapshotServer(0, self.capture, wait_timeout=1)
        self.url = 'http://127.0.0.1:{}'.format(self.server.server_port)
        self.capture.start()
        self.server.start()

    def tearDown(self):
        self.capture.close()
        self.server.close()
        self.assertFalse(self.capture.thread.is_alive())
        self.assertFalse(self.server.thread.is_alive())
        self.assertIsNone(self.capture.pid)

    def get(self, path='/snapshot.jpg'):
        with urllib.request.urlopen(self.url + path, timeout=3) as response:
            return response.read(), response.headers

    def test_on_demand_reuse_idle_and_restart(self):
        self.get('/status.json')
        self.assertIsNone(self.capture.pid)
        first, headers = self.get()
        self.assertTrue(first.startswith(b'\xff\xd8') and first.endswith(b'\xff\xd9'))
        self.assertEqual(headers['Content-Type'], 'image/jpeg')
        self.assertIn('no-store', headers['Cache-Control'])
        pid = self.capture.pid
        time.sleep(0.4)
        second, _ = self.get('/snapshot.jpg?cache=123')
        self.assertNotEqual(first, second)
        self.assertEqual(pid, self.capture.pid)
        deadline = time.monotonic() + 4
        while self.capture.pid is not None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertIsNone(self.capture.pid)
        self.assertEqual(self.capture.status()['state'], 'Idle')
        self.assertIsNone(self.capture.frame)
        self.get()
        self.assertNotEqual(pid, self.capture.pid)

    def test_parallel_requests_share_one_process(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.get()[0], range(6)))
        self.assertTrue(all(item.startswith(b'\xff\xd8') for item in results))
        pid = self.capture.pid
        self.get()
        self.assertEqual(pid, self.capture.pid)

    def test_disabled_and_unknown_paths(self):
        self.capture.set_enabled(False)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get()
        self.assertEqual(error.exception.code, 503)
        self.assertIsNone(self.capture.pid)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get('/missing')
        self.assertEqual(error.exception.code, 404)

    def test_failed_capture_is_503(self):
        self.capture.command = ['/no/such/ffmpeg']
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get()
        self.assertEqual(error.exception.code, 503)
        self.assertEqual(self.capture.status()['state'], 'Error')
        self.assertIsNone(self.capture.pid)

    def test_head_does_not_start_camera(self):
        request = urllib.request.Request(self.url + '/snapshot.jpg', method='HEAD')
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
        self.assertIsNone(self.capture.pid)


class ConfigurationTests(unittest.TestCase):
    def test_credentials_and_validation(self):
        self.assertEqual(camera_url('rtsp://192.0.2.1:554/stream', 'a@b', 'p:#? /'),
                         'rtsp://a%40b:p%3A%23%3F%20%2F@192.0.2.1:554/stream')
        self.assertRaises(ValueError, camera_url, 'http://example.com')
        self.assertRaises(ValueError, camera_url, 'rtsp://example.com:no/stream')

    def test_plugin_xml_and_domoticz_lifecycle(self):
        source = (ROOT / 'plugin.py').read_text()
        xml = source[source.index('<plugin '):source.index('</plugin>') + 9]
        self.assertEqual(ET.fromstring(xml).attrib['key'], 'CameraBridge')
        devices = {}
        errors = []
        class Device:
            def __init__(self, **kwargs):
                self.unit = kwargs['Unit']
                self.nValue = 0
                self.sValue = ''
            def Create(self):
                devices[self.unit] = self
            def Update(self, nValue, sValue):
                self.nValue, self.sValue = nValue, sValue
        stub = types.SimpleNamespace(Device=Device, Log=lambda s: None,
                                     Error=errors.append, Heartbeat=lambda n: None)
        sys.modules['Domoticz'] = stub
        spec = importlib.util.spec_from_file_location('test_plugin', ROOT / 'plugin.py')
        plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin)
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            folder = pathlib.Path(directory)
            (folder / 'bin').mkdir()
            (folder / 'bin' / 'ffmpeg').symlink_to(shutil.which('ffmpeg'))
            shutil.copy(ROOT / 'camera_bridge.py', folder)
            plugin.Parameters = dict(HomeFolder=str(folder), Address='rtsp://192.0.2.1/stream',
                                     Port=str(port), Username='', Password='')
            plugin.Devices = devices
            try:
                plugin.onStart()
                self.assertFalse(errors, errors)
                self.assertEqual(set(devices), {1, 2, 3, 4})
                self.assertEqual(devices[3].nValue, 1)
                self.assertIsNone(plugin._plugin.capture.pid)
                plugin.onCommand(3, 'Off', 0, '')
                self.assertFalse(plugin._plugin.capture.enabled)
                plugin.onHeartbeat()
            finally:
                plugin.onStop()
            # Persist the disabled setting across restart.
            try:
                plugin.onStart()
                self.assertFalse(plugin._plugin.capture.enabled)
            finally:
                plugin.onStop()
        del sys.modules['Domoticz']

if __name__ == '__main__':
    unittest.main()
