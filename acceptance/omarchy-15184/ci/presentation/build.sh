#!/bin/bash
set -euo pipefail
wayland-scanner client-header ci/presentation/presentation-time.xml work/native-capture/presentation-client.h
wayland-scanner private-code ci/presentation/presentation-time.xml work/native-capture/presentation-protocol.c
cc -std=c11 -shared -fPIC -O2 -Wall -Wextra -Werror -Iwork/native-capture ci/presentation/probe.c work/native-capture/presentation-protocol.c $(pkg-config --cflags --libs wayland-client libpng) -ldl -lpthread -o work/native-capture/presentation-probe.so
mapfile -t state < work/session-state
scp -q -i "${state[0]}" -P 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null work/native-capture/presentation-probe.so omarchy@127.0.0.1:/tmp/pr15184/
