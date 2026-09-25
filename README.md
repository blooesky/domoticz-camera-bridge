# Camera Bridge for Domoticz

On-demand JPEG snapshots from RTSP cameras. One hardware entry per camera.
View RTSP cameras in the standard Domoticz **Cameras** interface, even when the
camera has no usable HTTP snapshot endpoint. All plugin fields and device names
are in English.

**Version:** 1.0.0 · **License:** MIT (plugin source only)

Reported working by the initial user with a real camera and Domoticz. Compatibility
with every camera model, OS architecture and Domoticz build is not implied.

## Behaviour

- No background captures and no camera connection while idle.
- A GET request to `/snapshot.jpg` starts local FFmpeg.
- FFmpeg stays connected while requests arrive, generating one JPEG per second
  (optionally one every two seconds). Requests share the same process.
- After 10 seconds without image requests, FFmpeg stops. This delay is configurable.
- Images stay in RAM; snapshots are not repeatedly written to the SD card.
- A new viewing session waits for a new image, rather than displaying an old session.
- A failed capture returns HTTP 503. Subsequent requests allow automatic retries.
- A stalled connection is restarted after 15 seconds without frames, while demand remains.
- The first image can take several seconds, depending on connection, keyframe interval
  and camera codec. The one-second interval applies after capture starts; it is not
  a guarantee of one-second startup or end-to-end latency.
- Any consumer of the snapshot URL keeps capture active, including dashboards,
  notifications or camera previews. Closing one viewer cannot stop other viewers.

## Requirements

An existing working Domoticz installation with Python plugin support, on Linux.
The installer supports Raspberry Pi OS / Debian ARM64 and ARMHF (ARMv7 or newer).
Use camera IP addresses and start with its H.264 substream to reduce CPU load.
H.265 depends on the installed FFmpeg decoder and available CPU.

The plugin uses only Python's standard library. No pip installation or venv is needed.
FFmpeg is a separate executable installed in `CameraBridge/bin/ffmpeg`.
The installer does not install Domoticz itself or enable Python support in a build
that lacks it. Docker users: install and run inside the Domoticz container environment;
127.0.0.1 always refers to that environment.

## Installation

### Clone with Git

Replace `YOUR_GITHUB_USERNAME` with the owner of this repository. Run as the owner
of the Domoticz installation, not as root. Adjust the path and service name for
your installation. Git must already be installed for this method.

```bash
cd ~/domoticz/plugins
git clone https://github.com/blooesky/domoticz-camera-bridge.git CameraBridge
cd CameraBridge
bash install.sh
sudo systemctl restart domoticz
```

### Install from a ZIP

Download and extract the repository ZIP, rename the extracted folder to
`CameraBridge`, and place it inside the actual Domoticz `plugins` directory.
`plugin.py` must be directly inside `plugins/CameraBridge`, not another nested
folder. Then run:

```bash
cd ~/domoticz/plugins/CameraBridge
bash install.sh
sudo systemctl restart domoticz
```

The installer downloads a third-party static FFmpeg build matching the OS
architecture, checks the upstream transfer checksum, and generates a test JPEG.
Missing system utilities may be installed with `sudo apt-get`. No global Python
packages or global FFmpeg are installed. Run `bash install.sh` **without sudo**;
it rejects root execution to prevent ownership problems.

The Raspberry Pi needs Internet access to [johnvansickle.com](https://johnvansickle.com/ffmpeg/)
for the download. FFmpeg is not bundled in this repository. The installer uses the
upstream release URL and prints the installed version; it does not guarantee the
newest FFmpeg release. The upstream MD5 check detects download corruption and is
not a digital signature. Use `bash install.sh --force` to redownload.

If FFmpeg installation fails, resolve that error before adding the hardware.
The installer does not restart Domoticz automatically.

## Updating

For a Git installation with no local source modifications:

```bash
cd ~/domoticz/plugins/CameraBridge
git pull --ff-only
bash install.sh
sudo systemctl restart domoticz
```

The installer keeps an existing working local FFmpeg. Hardware settings are stored
in Domoticz, not in repository files. For ZIP installations, disable the Camera
Bridge hardware entries, replace the source files while keeping `bin/`, run the
installer, restart Domoticz and enable those entries again.

## Add hardware

In **Setup → Hardware**, choose **Camera Bridge - RTSP to JPEG**.

| Field | Example |
|---|---|
| Name | Front camera |
| Full RTSP URL | `rtsp://192.168.1.100:554/Streaming/Channels/102` |
| Local HTTP port | `9081` |
| Camera username | `admin` |
| Camera password | Your camera password |
| RTSP transport | TCP |
| Snapshot interval while viewing | 1 second |
| HTTP wait for first image | 8 seconds |
| Stop after no requests | 10 seconds |

Use separate username/password fields; special characters are URL-encoded for you.
Use the camera credentials, not the account used to sign in to a cloud app.
For Hikvision/HiLook, `/Streaming/Channels/102` is the usual secondary stream path;
verify the actual path with your model. `/Streaming/Channels/101` is the usual main stream.
| Stream | Typical Hikvision / HiLook path | Trade-off |
|---|---|---|
| Main stream | `/Streaming/Channels/101` | Higher image resolution and potentially higher CPU/network use |
| Substream | `/Streaming/Channels/102` | Lower resource use; default example |

Changing the RTSP URL in Hardware does not require changing the Domoticz Cameras
entry. JPEG generation stays at the selected one- or two-second interval. Camera
firmware and stream settings determine the actual resolution.

Other brands may work if they provide an FFmpeg-compatible RTSP video stream;
enter the appropriate URL for the model. They have not all been tested.

For more cameras add this hardware again, with a different port: 9082, 9083, etc.
Each entry has its own capture process and independent state.

## Add the image to Domoticz Cameras

Open **Setup → More Options → Cameras** (menu wording can vary by Domoticz version)
and add a camera:

| Setting | Value |
|---|---|
| Name | Front camera |
| Enabled | Yes |
| Protocol | HTTP |
| Address | `127.0.0.1` |
| Port | `9081` |
| Username / Password | Leave both empty |
| Image URL | `snapshot.jpg` |

Domoticz fetches the JPEG from the plugin and presents it through its camera interface.
Its periodic image requests keep capture active. No live RTSP player or Custom Menu is
required. Do not enter the camera RTSP address into the Domoticz Image URL field.

The HTTP endpoint deliberately binds only to 127.0.0.1. Do not open/forward its port
on the router. Use your existing authenticated access to Domoticz to view the image.
Direct `http://PI_IP:9081/` access from another PC does not work by design.
A page or app that expects to contact the plugin port directly is not supported.

## Devices

| Device | Meaning |
|---|---|
| Status | Idle, Connecting, Streaming, Error or Disabled |
| Last snapshot | Time of the most recent successful JPEG |
| Capture enabled | Allows or blocks requested captures; persisted across restarts |
| Refresh | Requests a capture session without opening the camera viewer |

Idle means no requested capture; it does **not** prove that the camera is online.
Device state is updated on the five-second plugin heartbeat, not on every frame.
The Last snapshot device therefore does not generate one database update per second.
Refresh does not override Capture enabled = Off.

## Diagnostics (run on the Raspberry Pi)

Status inspection does not start FFmpeg:

```bash
curl --fail http://127.0.0.1:9081/status.json
```

Request and save one image:

```bash
curl --fail --max-time 12 http://127.0.0.1:9081/snapshot.jpg -o /tmp/camera-test.jpg
```

After the last request, wait more than 10 seconds and inspect status again:
`state` should be `Idle` and `ffmpeg_running` should be `false`.
A first request may time out while the camera connects; retry shortly afterwards.

If no image appears:

- Check that `install.sh` finished with `JPEG generation test: OK`.
- Check the plugin Status device and Domoticz log.
- Check the RTSP URL and credentials in VLC from a machine that can reach the camera.
- Try TCP and the H.264 substream; ensure the camera is not at its connection limit.
- Verify that no other hardware/service uses the chosen local port.
- Make sure Capture enabled is On and Domoticz is allowed to create new devices.
- With a missing plugin type, check directory nesting, restart Domoticz and check
  whether its build supports Python plugins.

Credentials are not printed by the plugin. FFmpeg receives the authenticated RTSP URL
as a process argument; local accounts with permission to inspect processes can see it.
Raw FFmpeg stderr is suppressed because it may contain credentials. Status errors are
therefore intentionally generic. Do not share camera passwords in screenshots/logs.

## Validation and limits

Runtime tested with real FFmpeg and a synthetic video source: JPEG output, concurrent
requests, idle shutdown, restart, disabled capture, and failure responses. Plugin XML
and callbacks tested with a Domoticz API stub. The initial user has also reported
successful use in their real Domoticz/camera installation. The exact OS version,
Domoticz build, codec and architecture of that field test were not recorded.
ARM64/ARMHF are installer targets, not a claim that both have been field-tested.

To run the included developer tests on Linux with FFmpeg available on PATH:

```bash
python3 -m unittest discover -s tests -v
```

This version does not provide video live playback, audio, recording, ONVIF discovery,
PTZ controls, background snapshots or automatic camera entries in Domoticz.

## Repository contents

| File | Purpose |
|---|---|
| `plugin.py` | Domoticz hardware settings, devices and lifecycle callbacks |
| `camera_bridge.py` | On-demand FFmpeg capture and loopback JPEG server |
| `install.sh` | Architecture detection, local FFmpeg setup and validation |
| `tests/test_runtime.py` | Runtime and plugin callback tests |
| `CHANGELOG.md` | Release history |
| `CONTRIBUTING.md` | Reproduction details for issues and contribution checks |
| `THIRD_PARTY_NOTICES.md` | FFmpeg source and licensing information |

`bin/`, Python caches, local environments, snapshots and temporary files are ignored
by Git. No camera credentials or FFmpeg binaries are included.

## License

The plugin source is released under the [MIT License](LICENSE).
FFmpeg is a separate third-party program with its own license; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
