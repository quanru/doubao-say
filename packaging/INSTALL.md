# Doubao Say 1.1.0

English interface by default. Select System, English or 简体中文 in Settings;
the choice saves and applies automatically. System follows the session locale (Chinese → Simplified Chinese;
unsupported languages → English). Manual choices override the system locale.
This is a standalone cloud voice-input application. Doubao web-account recognition
is the default; an optional user-supplied Volcengine Seed ASR API key can be selected
in Settings.

## Requirements

This bundle includes Python dependency wheels for the Python/CPU version in its
filename (for example cpython-314 and x86_64). System libraries are not bundled.
The recommended `./install.sh` detects missing Arch/Omarchy packages, shows the
exact list and asks before installing them. Use `./install.sh --yes` only after
reviewing that list. Run it in the intended desktop session: Wayland selects
`gtk4-layer-shell` and `wl-clipboard`; native X11 uses GTK's built-in backend.
The source installer, archive installer and runtime checks use the same required
desktop dependencies. XWayland's `DISPLAY` does not select native X11.

The equivalent manual command for Hyprland/Omarchy is:

```sh
omarchy pkg add python python-gobject python-cairo gtk4 gtk4-layer-shell webkitgtk-6.0 pipewire wl-clipboard portaudio
```

For a native X11 session on Arch:

```sh
sudo pacman -S --needed python python-gobject python-cairo gtk4 webkitgtk-6.0 pipewire portaudio
```

X11 requires GTK's GdkX11 backend, but neither layer-shell nor wl-clipboard.
PipeWire is used on X11 and Wayland so microphone node selection matches capture.
Automatic paste on native X11 additionally uses the optional `xdotool` and
`xclip` helpers. They are probed at runtime and can be installed on Arch with
`sudo pacman -S --needed xdotool xclip`. If either is unavailable, installation
and startup still succeed and recognized text is retained for manual copying.
CopyQ is not required. Ordinary clipboard paste replaces clipboard contents and
may be stored by a clipboard manager. Direct typing through optional `wtype`
remains a Hyprland/Wayland feature; choose Clipboard paste on native X11.
Other Wayland compositors do not gain automatic input from this X11 support.

Your user needs read access to keyboard events and write access to `/dev/uinput`.
On this Omarchy setup, membership in `input` provides these permissions. If absent,
run `sudo usermod -aG input "$USER"` and log out/in. Never run the application as root.
Review this broad keyboard access before enabling it. Other Linux distributions
may need their own udev rules and corresponding system packages.

The optional Vibekey receiver also needs access to its vendor HID interface. Its
support is off by default and can be enabled in Settings. If you use that receiver,
install the bundled narrowly scoped rule, reload udev, then unplug and reconnect it:

```sh
sudo install -Dm644 packaging/70-doubao-say-au05.rules /etc/udev/rules.d/70-doubao-say-au05.rules
sudo udevadm control --reload-rules
```

The rule matches only USB VID/PID `fff1:00dd`. When Vibekey support is enabled,
Doubao Say discovers the receiver at runtime; the receiver and this rule are not
required for ordinary keyboards.

## Git / marketplace installation (manual setup required)

This route installs the same app from source, not the offline archive below.
Omarchy only clones the repository; it does not run setup hooks or install dependencies.
Review the source first, add it **without enabling**, then explicitly install dependencies:

```sh
omarchy plugin add https://github.com/quanru/doubao-say.git
cd ~/.config/omarchy/plugins/md.lifeos.doubao-say
./install.sh
```

Decline enablement if prompted by `plugin add`. The installer uses Omarchy's package manager
and may ask for an administrator password. It does not change group membership,
udev rules, compositor shortcuts, or autostart. The read-only `--check` command
checks runtime dependencies and reports device access without logging in, recording,
uploading audio, or sending input. Device access is not a physical-key acceptance test.
Complete any required logout/login and the application's four-step onboarding before
enabling the plugin. Do not create a virtual environment inside an installed plugin:
Omarchy rejects symlinks and watches its tree for changes. Git installs use OS packages;
offline bundles provide their own wheels/runtime. Their dependency versions can differ.

For updates, stop recording and disable the plugin first. Review the changes offered by
`omarchy plugin update md.lifeos.doubao-say`, rerun setup if requirements
changed, then enable it again. Marketplace review applies to a specific commit; a
Git installation/update may retrieve a newer, unreviewed branch head.

For a Git-installed copy, disable the plugin and use
`omarchy plugin remove md.lifeos.doubao-say` (not the archive uninstaller).
If you registered the optional desktop launcher, remove only `~/.local/share/applications/doubao-say.desktop`
after verifying that its Exec points to the removed plugin. Credentials and settings
remain under `~/.config/doubao-say`; package dependencies are not automatically removed.
Do not install the Git and archive variants side by side: they have the same plugin ID.

## Install (per-user application; system packages may require authorization)

Verify the archive against the supplied SHA256SUMS, extract it, enter its folder,
then use the same installer entry point:

```sh
./install.sh --check
./install.sh
```

`--check` changes nothing. The installer asks before adding missing system packages,
verifies the bundle, and installs its bundled Python wheels into a per-user runtime.
The lower-level `python3 install.py` remains available when system prerequisites are already managed.

The **app** archive installs to `~/.local/share/doubao-say/app`.
The **plugin** archive installs to
`~/.config/omarchy/plugins/md.lifeos.doubao-say`.
Both register a **Doubao Say** desktop launcher and share a Python runtime
outside the plugin folder. XDG_CONFIG_HOME and XDG_DATA_HOME are respected.
Existing installations are backed up, not erased. Do not delete the installed
directory. Keep the original extracted installer for uninstall, or extract the
matching archive again; do not run install.py from the managed installation tree.

Open the launcher and either sign in to Doubao or select the Volcengine official
API backend in Settings and add/test your speech API key. Then focus a text field
and press Fn.
Tap to start/stop; hold to talk/release to finish; double-tap sends Enter.
Choose another key in Settings if your keyboard does not expose Fn.
Double-tap can submit a message or execute a terminal command.

The control center checks the latest stable GitHub Release at most daily. A newer
version produces a small red dot on the recording overlay and an Update button in
the control center; downloading and
installation remain manual. Plugin users update with `omarchy plugin update
md.lifeos.doubao-say` and rerun setup if dependencies changed.
Archive users install the new matching archive over the existing installation.

## Plugin enable / disable

Finish recording and quit the standalone app before enabling the plugin:

```sh
omarchy plugin enable md.lifeos.doubao-say
omarchy plugin disable md.lifeos.doubao-say
```

Alternatively `./install.sh --enable` installs and enables a plugin archive.
Enabling starts the client silently; disabling stops the process owned by the
plugin. A separately running standalone instance is not owned or stopped by the
plugin. Do not enable XDG autostart and plugin startup simultaneously.
The plugin restarts a crashed client. To keep it stopped, disable the plugin.

## Upgrade / uninstall

Disable the plugin or quit the standalone app before upgrading. Extract the new
bundle and run its installer. Settings and sign-in data are kept separately.

```sh
./install.sh --uninstall
```

Uninstall moves the managed application/plugin into a backup under
`~/.local/share/doubao-say/backups`. It restores the previous desktop
launcher when available. Credentials, user settings and shared runtime are kept.
Turn off desktop autostart in Settings before uninstalling the standalone app.

## Privacy

Microphone audio is sent to the selected recognition provider during recording.
The default backend depends on Doubao's unofficial web protocol; the optional
official backend uses the user's Volcengine API account and is billed under its
terms. No authentication data, microphone recordings,
personal transcripts or development virtual environment are included in this bundle.
If optional polishing is enabled, recognized and provisional text is sent to the
user-configured OpenAI-compatible endpoint and is subject to that provider's terms.
The daily update check contacts GitHub and caches only its time and public release tag.
Keep credential files and debug logs out of bug reports.
