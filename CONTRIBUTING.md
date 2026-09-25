# Contributing

## Report a problem

Include the plugin version, Domoticz version, Raspberry Pi model, OS version,
`dpkg --print-architecture`, camera model, video codec, main/substream selection,
and the output of the local `status.json` endpoint. Explain the expected and
actual behaviour, and whether VLC can open the stream.

Remove usernames, passwords, authenticated URLs and identifying network details
before sharing logs or screenshots. Do not paste the complete FFmpeg process
command because it may include the camera password.

## Development checks

On Linux with Python 3 and FFmpeg installed and available on PATH:

```bash
bash -n install.sh
python3 -m unittest discover -s tests -v
```

The tests use a synthetic FFmpeg source and a stub Domoticz API. They do not
replace a test on actual Domoticz with an RTSP camera.

Keep all Domoticz API calls on Domoticz callbacks, not background threads.
Preserve loopback-only HTTP binding and avoid logging credentials. Do not commit
FFmpeg binaries, generated images, local credentials or Python caches.
