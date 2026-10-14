Name:           doubao-say
Version:        @VERSION@
Release:        1%{?dist}
Summary:        Voice input for Linux desktops
License:        MIT
URL:            https://doubao-say.lifeos.md/
Source0:        doubao-say-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel
Requires:       python(abi) = %{python3_version}
Requires:       python3 >= 3.11
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       python3-websockets
Requires:       python3-evdev
Requires:       python3-jwt
Requires:       python3-cryptography
Requires:       gtk4
Requires:       webkitgtk6.0
Requires:       pipewire-utils
Requires:       wl-clipboard
Recommends:     python3-sounddevice
Recommends:     xdotool
Recommends:     xclip
Recommends:     wmctrl
Recommends:     gtk4-layer-shell

%description
GTK4 desktop voice input with configurable shortcuts and online recognition.
Uses Doubao web sign-in or the user's Volcengine/Deepgram API credentials.
No services are started and no input-group memberships are modified on install.

%prep
%setup -q

%build

%install
mkdir -p %{buildroot}%{python3_sitelib} %{buildroot}%{_bindir}
cp -a src/doubao_input %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib}/doubao_input -name __pycache__ -type d -exec rm -rf {} +
cat > %{buildroot}%{_bindir}/doubao-say <<'LAUNCHER'
#!/bin/sh
exec /usr/bin/python3 -m doubao_input "$@"
LAUNCHER
chmod 755 %{buildroot}%{_bindir}/doubao-say
install -Dm644 packaging/store/md.lifeos.DoubaoSay.desktop %{buildroot}%{_datadir}/applications/md.lifeos.DoubaoSay.desktop
install -Dm644 packaging/store/md.lifeos.DoubaoSay.metainfo.xml %{buildroot}%{_datadir}/metainfo/md.lifeos.DoubaoSay.metainfo.xml
install -Dm644 src/doubao_input/resources/logo-128.png %{buildroot}%{_datadir}/icons/hicolor/128x128/apps/md.lifeos.DoubaoSay.png

%files
%license LICENSE NOTICE
%doc README.md
%{_bindir}/doubao-say
%{python3_sitelib}/doubao_input/
%{_datadir}/applications/md.lifeos.DoubaoSay.desktop
%{_datadir}/metainfo/md.lifeos.DoubaoSay.metainfo.xml
%{_datadir}/icons/hicolor/128x128/apps/md.lifeos.DoubaoSay.png
