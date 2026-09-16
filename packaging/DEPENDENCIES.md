# Bundled Python dependency inventory

Read from the METADATA and embedded license files of the locally built wheel set
on 2026-09-13. These are package-declared identifiers, not legal verification of
all source files or transitive system-library obligations.

| Package | Version | Declared license | Embedded notice files |
| --- | --- | --- | --- |
| cffi | 2.1.1 | MIT-0 | 2 |
| evdev | 2.0.0 | BSD-3-Clause | 1 |
| pycparser | 3.0 | BSD-3-Clause | 1 |
| sounddevice | 0.5.6 | MIT | 1 |
| websockets | 17.1 | BSD-3-Clause | 2 |

Wheels are distributed intact, including these notices. GTK, WebKit, PipeWire,
PortAudio, Cairo and system PyGObject are installed by the OS and not bundled.
The optional X11 helpers `xdotool` and `xclip` are also not bundled; they are
probed at runtime and are not required for installation or Wayland. Ruff is
development-only, not part of end-user archives. Rebuild this inventory when
dependency pins change.

Before public release: verify exact upstream code revisions and author notices,
review full license texts and bundled-wheel contents, and record any additional
attribution requirements. Correcting a repository URL is not provenance proof.
