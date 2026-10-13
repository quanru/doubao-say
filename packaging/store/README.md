# Linux store packages

RPM and Flatpak builders complement the existing archive installer. Packages use
`md.lifeos.DoubaoSay` for desktop integration and do not enable a background
service, change input-group membership, or install udev rules.

## RPM (Fedora 44)

```sh
python3 packaging/build-store.py rpm --output /tmp/doubao-rpm
rpmbuild --define '_topdir /tmp/doubao-rpm' -bb /tmp/doubao-rpm/SPECS/doubao-say.spec
sudo dnf install /tmp/doubao-rpm/RPMS/noarch/doubao-say-*.rpm
```

Use DNF so system dependencies are resolved. This package is tested on Fedora
44; an RPM filename alone does not establish compatibility with other RPM-based
distributions. GNOME uses the GlobalShortcuts permission dialog. Other desktops
may need the input permissions described in `packaging/INSTALL.md`.

## Flatpak (GNOME 49 runtime)

```sh
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.gnome.Sdk//49 org.gnome.Platform//49
python3 packaging/build-store.py flatpak --output /tmp/doubao-flatpak
cd /tmp/doubao-flatpak
flatpak-builder --user --repo=repo build md.lifeos.DoubaoSay.json
flatpak build-bundle repo doubao-say.flatpak md.lifeos.DoubaoSay --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo
flatpak install --user ./doubao-say.flatpak
flatpak run md.lifeos.DoubaoSay
```

**This is a desktop-integration Flatpak, not an isolated offline application.**
It requests device access and `org.freedesktop.Flatpak` host-command access:
`flatpak-spawn --host` runs the host's PipeWire, clipboard and input helpers.
Install `pw-record`/`pw-dump` (PipeWire utilities) on the host. Wayland clipboard
integration needs `wl-copy`/`wl-paste`; native X11 automatic paste needs
`xdotool` and `xclip`. Hyprland integration additionally uses `hyprctl`.
Host input permissions still apply; granting Flatpak permissions does not grant
access to protected input devices. Credentials and application state use the
Flatpak's private XDG directories. Recognition requires an online provider.

The bundle is intended for direct installation and evaluation. It is not listed
on Flathub, and its host-command permission has not been approved by Flathub or
any third-party app store.

## Verification and provenance

`Linux store packages` CI builds both formats, installs each in Linux, verifies
GTK/WebKit and Python imports plus desktop resources, then uninstalls it.
`SOURCE.json` identifies the application version and build commit. These gates
verify packaging and runtime dependencies; they do not claim a real microphone,
login, global shortcut or cross-application paste test. Those require a desktop
acceptance run before describing a store listing as supported.
