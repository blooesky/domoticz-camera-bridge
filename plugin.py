"""
<plugin key="CameraBridge" name="Camera Bridge - RTSP to JPEG" author="4D" version="1.0.0" wikilink="https://github.com/blooesky/domoticz-camera-bridge">
    <description><h2>Camera Bridge</h2><p>On-demand RTSP snapshots. One hardware entry per camera. Run install.sh first.</p><p>In Setup / More Options / Cameras use HTTP, address 127.0.0.1, the local port below, and Image URL snapshot.jpg. Leave camera credentials empty there.</p></description>
    <params>
        <param field="Address" label="Full RTSP URL (without credentials)" width="500px" required="true" default="rtsp://192.168.1.100:554/Streaming/Channels/102"/>
        <param field="Port" label="Local HTTP port (unique per camera)" width="100px" required="true" default="9081"/>
        <param field="Username" label="Camera username" width="200px" required="false" default="admin"/>
        <param field="Password" label="Camera password" width="200px" required="false" default=""/>
        <param field="Mode1" label="RTSP transport" width="100px">
            <options><option label="TCP (recommended)" value="tcp" default="true"/><option label="UDP" value="udp"/></options>
        </param>
        <param field="Mode2" label="Snapshot interval while viewing" width="120px">
            <options><option label="1 second" value="1" default="true"/><option label="2 seconds" value="2"/></options>
        </param>
        <param field="Mode3" label="HTTP wait for first image (seconds, 1-9)" width="100px" default="8"/>
        <param field="Mode4" label="Stop after no requests (seconds, 10-60)" width="100px" default="10"/>
    </params>
</plugin>
"""
import importlib.util
import os
import Domoticz


class BasePlugin:
    def __init__(self):
        self.capture = None
        self.server = None
        self.last_log = None

    def onStart(self):
        try:
            # Load by absolute path; multiple plugin instances retain independent state.
            home = Parameters['HomeFolder']
            spec = importlib.util.spec_from_file_location('camera_bridge_runtime', os.path.join(home, 'camera_bridge.py'))
            runtime = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runtime)
            ffmpeg = os.path.join(home, 'bin', 'ffmpeg')
            if not os.path.isfile(ffmpeg) or not os.access(ffmpeg, os.X_OK):
                raise ValueError('Local bin/ffmpeg missing or not executable. Run bash install.sh in the plugin folder.')
            port = int(Parameters.get('Port', '9081'))
            wait = int(Parameters.get('Mode3') or '8')
            idle = int(Parameters.get('Mode4') or '10')
            interval = int(Parameters.get('Mode2') or '1')
            transport = Parameters.get('Mode1') or 'tcp'
            if not (1024 <= port <= 65535 and 1 <= wait <= 9 and 10 <= idle <= 60):
                raise ValueError('Use port 1024-65535, HTTP wait 1-9, idle timeout 10-60')
            if interval not in (1, 2) or transport not in ('tcp', 'udp'):
                raise ValueError('Invalid interval or transport')
            url = runtime.camera_url(Parameters['Address'], Parameters.get('Username', ''), Parameters.get('Password', ''))
            for unit, name, kind in ((1, 'Status', 'Alert'), (2, 'Last snapshot', 'Text'),
                                     (3, 'Capture enabled', 'Switch'), (4, 'Refresh', 'Switch')):
                if unit not in Devices:
                    args = dict(Name=name, Unit=unit, TypeName=kind, Used=1)
                    if unit == 4:
                        args['Switchtype'] = 9
                    Domoticz.Device(**args).Create()
                    if unit == 3:
                        Devices[unit].Update(nValue=1, sValue='On')
            enabled = Devices[3].nValue != 0
            self.capture = runtime.Capture(ffmpeg, url, transport, interval, idle, enabled)
            self.server = runtime.SnapshotServer(port, self.capture, wait)
            self.capture.start()
            self.server.start()
            Domoticz.Heartbeat(5)
            Domoticz.Log('Ready: http://127.0.0.1:{}/snapshot.jpg (on demand only)'.format(port))
            self.onHeartbeat()
        except Exception as exc:
            self.onStop()
            # Only our validation messages are safe to print. Never dump Parameters or URL.
            message = str(exc) if isinstance(exc, ValueError) else 'Startup failed ({}); check port availability and plugin files'.format(type(exc).__name__)
            Domoticz.Error(message)
            if 1 in Devices:
                Devices[1].Update(nValue=4, sValue=message)

    def onStop(self):
        if self.capture is not None:
            self.capture.close()
        if self.server is not None:
            self.server.close()
        self.server = None
        self.capture = None

    @staticmethod
    def update(unit, value, text):
        if unit in Devices and (Devices[unit].nValue != value or Devices[unit].sValue != text):
            Devices[unit].Update(nValue=value, sValue=text)

    def onHeartbeat(self):
        if self.capture is None:
            return
        status = self.capture.status()
        state = status['state']
        message = state + (': ' + status['detail'] if status['detail'] else '')
        self.update(1, {'Idle': 0, 'Disabled': 0, 'Connecting': 2, 'Streaming': 1, 'Error': 4}[state], message)
        self.update(2, 0, status['last_snapshot'])
        if state == 'Error' and message != self.last_log:
            Domoticz.Error(message)
        self.last_log = message

    def onCommand(self, Unit, Command, Level, Hue):
        if self.capture is None:
            return
        if Unit == 3 and Command in ('On', 'Off'):
            enabled = Command == 'On'
            self.capture.set_enabled(enabled)
            self.update(3, int(enabled), Command)
        elif Unit == 4 and Command == 'On':
            self.capture.trigger()
            self.update(4, 0, 'Off')


_plugin = BasePlugin()

def onStart():
    _plugin.onStart()

def onStop():
    _plugin.onStop()

def onHeartbeat():
    _plugin.onHeartbeat()

def onCommand(Unit, Command, Level, Hue):
    _plugin.onCommand(Unit, Command, Level, Hue)
