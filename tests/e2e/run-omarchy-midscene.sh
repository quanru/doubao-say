#!/bin/bash
set -euo pipefail

readonly ROOT_DIR="$PWD"
readonly WORK_DIR="$ROOT_DIR/.midscene-omarchy"
readonly HARNESS_DIR="$WORK_DIR/omarchy-iso"
# shellcheck source=omarchy-vm.env
source "$ROOT_DIR/tests/e2e/omarchy-vm.env"
readonly ISO_PATH="$WORK_DIR/omarchy-${OMARCHY_ISO_VERSION}.iso"
readonly BASE_DIR="$HARNESS_DIR/test-runs/omarchy-${OMARCHY_ISO_VERSION}"
readonly SSH_KEY="$BASE_DIR/id_ed25519"
readonly SSH_PORT=2222
readonly PLUGIN_DIR="/home/omarchy/.config/omarchy/plugins/md.lifeos.doubao-say"
readonly SHIM_DIR="$(mktemp -d)"
readonly PLUGIN_ARCHIVE="$(mktemp /tmp/doubao-say-omarchy-plugin-XXXXXX.tar)"
export NODE_OPTIONS="${NODE_OPTIONS:-} --require=$ROOT_DIR/tests/e2e/node_modules/@computer-use/libnut/dist/import_libnut.js"
export OMARCHY_SSH_KEY="$SSH_KEY"

VM_PID=""

cleanup() {
  if [[ -n $VM_PID ]]; then
    kill "$VM_PID" 2>/dev/null || true
  fi
  rm -rf "$SHIM_DIR"
  rm -f "$PLUGIN_ARCHIVE"
}
trap cleanup EXIT

ssh_guest() {
  local status=255
  for _ssh_attempt in 1 2 3 4 5; do
    ssh -i "$SSH_KEY" -p "$SSH_PORT" \
      -o BatchMode=yes \
      -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=10 \
      -o LogLevel=ERROR \
      omarchy@127.0.0.1 "$@" && return 0
    status=$?
    if ((status != 255)); then
      return "$status"
    fi
    echo "Guest SSH connection attempt $_ssh_attempt failed; retrying." >&2
    sleep 3
  done
  return "$status"
}

ssh_session() {
  local command="$1"
  ssh_guest "export XDG_RUNTIME_DIR=/run/user/\$(id -u); \
    export DBUS_SESSION_BUS_ADDRESS=unix:path=\$XDG_RUNTIME_DIR/bus; \
    export HYPRLAND_INSTANCE_SIGNATURE=\$(ls -t \$XDG_RUNTIME_DIR/hypr | head -1); \
    export WAYLAND_DISPLAY=\$(find \$XDG_RUNTIME_DIR -maxdepth 1 -name 'wayland-*' ! -name '*.lock' -printf '%f\\n' | head -1); \
    export OMARCHY_PATH=/usr/share/omarchy; \
    export PATH=\$OMARCHY_PATH/bin:\$PATH; \
    $command" </dev/null
}

ssh_session_tty() {
  local command="$1"
  ssh -tt -i "$SSH_KEY" -p "$SSH_PORT" \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 \
    -o LogLevel=ERROR \
    omarchy@127.0.0.1 "export XDG_RUNTIME_DIR=/run/user/\$(id -u); \
      export DBUS_SESSION_BUS_ADDRESS=unix:path=\$XDG_RUNTIME_DIR/bus; \
      export OMARCHY_PATH=/usr/share/omarchy; \
      export PATH=\$OMARCHY_PATH/bin:\$PATH; \
      $command"
}

test -s "$ISO_PATH"
test -s "$BASE_DIR/base.qcow2"
test -s "$SSH_KEY"

# Reuse the pinned official harness's VM, login and session routines. Replace
# only its post-login acceptance body so this job can hand the live desktop to
# Midscene instead of running Omarchy's unrelated upstream acceptance suite.
readonly SESSION_HARNESS="$HARNESS_DIR/bin/omarchy-midscene-session"
cp "$HARNESS_DIR/bin/omarchy-iso-test" "$SESSION_HARNESS"
sed -i '/^acceptance_phase() {/,/^}/c\
acceptance_phase() {\
  log "Booting Omarchy session for Doubao Say Midscene E2E"\
  qemu-img create -f qcow2 -b "$BASE_DISK" -F qcow2 "$RUN_DIR/run.qcow2" >/dev/null\
  start_vm "$RUN_DIR/run.qcow2" "$RUN_DIR/serial.log"\
  establish_session\
  capture_console "success-session-ready-for-midscene"\
}' "$SESSION_HARNESS"

printf '#!/bin/sh\nexit 0\n' >"$SHIM_DIR/omarchy-pkg-add"
printf '#!/bin/sh\nexec convert "$@"\n' >"$SHIM_DIR/magick"
chmod 0755 "$SHIM_DIR/omarchy-pkg-add" "$SHIM_DIR/magick"

PATH="$SHIM_DIR:$PATH" "$SESSION_HARNESS" "$ISO_PATH" \
  --reuse-base \
  --keep-running \
  --memory 4096 \
  --no-preview

readonly RUN_DIR="$(find "$BASE_DIR/runs" -mindepth 1 -maxdepth 1 -type d | sort | tail -1)"
VM_PID="$(cat "$RUN_DIR/qemu.pid")"
kill -0 "$VM_PID"
ssh_guest true

# Put this exact checkout at its real Omarchy plugin location and validate the
# manifest. The Midscene project lifecycle starts its deterministic GTK fixture
# in the guest's actual Hyprland session for every case attempt.
echo "Creating the Omarchy plugin test payload."
tar -C "$ROOT_DIR" --exclude='__pycache__' -cf "$PLUGIN_ARCHIVE" \
  LICENSE README.md manifest.json install.sh setup-omarchy.sh start.sh \
  omarchy src tests/e2e/gtk_fixture.py tests/e2e/gtk_onboarding_fixture.py \
  tests/e2e/gtk_runtime_fixture.py

for _copy_attempt in 1 2 3 4 5; do
  if scp -i "$SSH_KEY" -P "$SSH_PORT" \
      -o BatchMode=yes \
      -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=no \
      -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=10 \
      -o LogLevel=ERROR \
      "$PLUGIN_ARCHIVE" omarchy@127.0.0.1:/tmp/doubao-say-plugin.tar; then
    break
  fi
  if ((_copy_attempt == 5)); then
    echo "Could not upload the plugin payload after five attempts." >&2
    exit 1
  fi
  echo "Guest SCP attempt $_copy_attempt failed; retrying." >&2
  sleep 3
done

ssh_guest "rm -rf '$PLUGIN_DIR' && mkdir -p '$PLUGIN_DIR' && \
  tar -C '$PLUGIN_DIR' -xf /tmp/doubao-say-plugin.tar"

echo "Validating md.lifeos.doubao-say with Omarchy."
ssh_session "omarchy plugin validate '$PLUGIN_DIR'"

echo "Installing the source checkout through its unified installer."
# The official ISO harness creates this disposable account with password
# "omarchy". Authorize sudo inside the same PTY that install.sh and
# omarchy-pkg-add use, matching a user who has just authenticated in a terminal.
# The compact prebuilt VM omits Pacman's sync databases, so refresh metadata in
# this disposable guest before asking the unchanged installer to resolve packages.
ssh_session_tty "printf '%s\\n' omarchy | sudo -S -v && \
  sudo pacman -Sy --noconfirm && '$PLUGIN_DIR/install.sh' --yes"
ssh_guest "test -f /home/omarchy/.local/share/applications/doubao-say.desktop && \
  grep -Fq '$PLUGIN_DIR/start.sh' /home/omarchy/.local/share/applications/doubao-say.desktop"

npm --prefix tests/e2e test -- --project omarchy-onboarding

# The Midscene project teardown has stopped its onboarding fixture. Dismiss
# first-run notifications before the shell project inspects Omarchy itself.
ssh_session "omarchy-shell notifications dismissAll"

# Reuse the same live Hyprland session for a visual comparison against
# Omarchy's OCR and hyprctl-based acceptance checks.
npm --prefix tests/e2e test -- --project omarchy-shell
