FROM fedora:43
RUN dnf -y install gnome-shell gnome-control-center xdg-desktop-portal \
      xdg-desktop-portal-gnome xdg-desktop-portal-gtk dbus-daemon \
      python3-gobject python3-cairo python3-evdev mesa-dri-drivers \
      mesa-libEGL mesa-libGL glib2 glibc-langpack-en procps-ng \
      adwaita-icon-theme util-linux && dnf clean all
RUN useradd --create-home --uid 1000 gnome-ci && \
    mkdir -p /dev/input && touch /dev/input/event0 && chmod 600 /dev/input/event0
COPY src /workspace/src
COPY tests/gnome /workspace/tests/gnome
RUN mkdir -p /tmp/gnome-runtime && chown gnome-ci /tmp/gnome-runtime && chmod 700 /tmp/gnome-runtime
ENV HOME=/home/gnome-ci XDG_RUNTIME_DIR=/tmp/gnome-runtime \
    XDG_SESSION_TYPE=wayland XDG_CURRENT_DESKTOP=GNOME \
    XDG_SESSION_DESKTOP=gnome LIBGL_ALWAYS_SOFTWARE=1 \
    GSK_RENDERER=cairo LANG=en_US.UTF-8 PYTHONPATH=/workspace/src
WORKDIR /workspace
CMD ["bash", "tests/gnome/launch-container.sh"]
