# Changelog

## 1.0.0 — 2026-09-25

Initial release.

- RTSP-to-JPEG capture started only by image requests or the Refresh device.
- One- or two-second JPEG interval while viewing.
- Automatic shutdown after inactivity (10 seconds by default).
- One independent hardware entry and local port per camera.
- Loopback HTTP endpoint for the Domoticz Cameras interface.
- Status, Last snapshot, Capture enabled and Refresh devices.
- In-memory snapshots, retry handling and stalled-capture recovery.
- Local FFmpeg installer for ARM64 and ARMHF (ARMv7 or newer).
- English documentation and runtime tests.

GitHub packaging adds documentation, license and repository metadata without
changing the tested plugin runtime or its settings.
