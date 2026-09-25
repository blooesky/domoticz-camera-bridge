# Third-party notices

## FFmpeg

FFmpeg is not included in this repository or source ZIP. `install.sh` downloads
an executable separately to the local `bin/` directory.

- FFmpeg project: https://ffmpeg.org/
- Static binary provider: https://johnvansickle.com/ffmpeg/
- Build and source links are available on the binary provider's page.

The provider identifies its static builds as GNU GPL version 3. This does not
change the MIT license assigned to this repository's plugin source. The installer
preserves `GPLv3.txt` and `readme.txt` from the archive when present, under
`bin/ffmpeg-docs/`. Refer to those files and the provider's source information for
the downloaded build. Do not describe the FFmpeg binary as MIT-licensed.

## Python

No third-party Python packages are bundled or installed. The plugin uses Python's
standard library and the Domoticz-provided Python API.
