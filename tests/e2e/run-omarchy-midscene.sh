#!/bin/bash
set -euo pipefail

readonly ROOT_DIR="$PWD"
readonly MIDSCENE_PROJECT="${1:?Usage: run-omarchy-midscene.sh PROJECT}"
readonly WORK_DIR="$ROOT_DIR/.midscene-omarchy"
readonly HARNESS_DIR="$WORK_DIR/omarchy-iso"
# shellcheck source=omarchy-vm.env
source "$ROOT_DIR/tests/e2e/omarchy-vm.env"
readonly ISO_PATH="$WORK_DIR/omarchy-${OMARCHY_ISO_VERSION}.iso"
readonly BASE_DIR="$HARNESS_DIR/test-runs/omarchy-${OMARCHY_ISO_VERSION}"
readonly SSH_KEY="$BASE_DIR/id_ed25519"
readonly SSH_PORT=2222
readonly PLUGIN_DIR="/home/omarchy/.config/omarchy/plugins/md.lifeos.doubao-say"
readonly REVIEW_PLUGIN_ID="tathagat11.checklist-todo"
readonly REVIEW_PLUGIN_SHA="0b8dfdbdc5dc1deaff178ad727fa22f6e289423a"
readonly REVIEW_PLUGIN_DIR="/home/omarchy/.config/omarchy/plugins/$REVIEW_PLUGIN_ID"
readonly SHIM_DIR="$(mktemp -d)"
readonly PLUGIN_ARCHIVE="$(mktemp /tmp/doubao-say-omarchy-plugin-XXXXXX.tar)"
readonly REVIEW_PLUGIN_ARCHIVE="$(mktemp /tmp/omarchy-review-plugin-XXXXXX.tar.gz)"
export NODE_OPTIONS="${NODE_OPTIONS:-} --require=$ROOT_DIR/tests/e2e/node_modules/@computer-use/libnut/dist/import_libnut.js"
export OMARCHY_SSH_KEY="$SSH_KEY"

VM_PID=""
XVFB_PID=""
MODEL_GATE_PID=""

cleanup() {
  if [[ -n $MODEL_GATE_PID ]]; then
    kill "$MODEL_GATE_PID" 2>/dev/null || true
  fi
  if [[ -n $XVFB_PID ]]; then
    kill "$XVFB_PID" 2>/dev/null || true
  fi
  if [[ -n $VM_PID ]]; then
    kill "$VM_PID" 2>/dev/null || true
  fi
  rm -rf "$SHIM_DIR"
  rm -f "$PLUGIN_ARCHIVE"
  rm -f "$REVIEW_PLUGIN_ARCHIVE"
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

# Put either the product checkout or one public, exact-commit review subject in
# the disposable Omarchy guest. Third-party code never runs on the host.
if [[ $MIDSCENE_PROJECT == omarchy-plugin-review ]]; then
  curl --fail --location --silent --show-error --retry 3 \
    --max-time 90 \
    "https://github.com/tathagat11/omarchy-checklist-todo/archive/$REVIEW_PLUGIN_SHA.tar.gz" \
    --output "$REVIEW_PLUGIN_ARCHIVE"
  ssh_guest "mkdir -p '$REVIEW_PLUGIN_DIR'"
  scp -i "$SSH_KEY" -P "$SSH_PORT" \
    -o BatchMode=yes -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 -o LogLevel=ERROR \
    "$REVIEW_PLUGIN_ARCHIVE" omarchy@127.0.0.1:/tmp/omarchy-review-plugin.tar.gz
  ssh_session "tar -C '$REVIEW_PLUGIN_DIR' --strip-components=1 -xzf /tmp/omarchy-review-plugin.tar.gz && \
    test \"\$(jq -r .id '$REVIEW_PLUGIN_DIR/manifest.json')\" = '$REVIEW_PLUGIN_ID' && \
    omarchy plugin validate '$REVIEW_PLUGIN_DIR' && \
    omarchy-shell shell rescanPlugins && \
    omarchy plugin enable '$REVIEW_PLUGIN_ID' --section right && \
    omarchy-shell '$REVIEW_PLUGIN_ID' status"
else
  # The Midscene project lifecycle starts its synthetic GTK fixture in the
  # guest's actual Hyprland session for every product case attempt.
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

  # First-run Omarchy notifications are unrelated to the plugin and visually
  # overlap the product's own recording overlay in VNC screenshots.
  ssh_session "omarchy-shell notifications dismissAll"
fi

# Start the host display ourselves and verify it before libnut connects. The
# ComputerAgent's built-in Xvfb launcher only waits a fixed 500 ms, which can
# race on busy Actions runners and crash before a report can be written.
export DISPLAY=
for _display_number in {99..198}; do
  if [[ ! -e /tmp/.X"$_display_number"-lock && ! -S /tmp/.X11-unix/X"$_display_number" ]]; then
    export DISPLAY=:"$_display_number"
    break
  fi
done
if [[ -z ${DISPLAY:-} ]]; then
  echo "No free host X11 display found." >&2
  exit 1
fi
echo "Starting host Xvfb on $DISPLAY."
Xvfb "$DISPLAY" -screen 0 1280x800x24 -ac -nolisten tcp \
  >"$WORK_DIR/xvfb.log" 2>&1 &
XVFB_PID=$!
for _xvfb_attempt in {1..200}; do
  if xset -display "$DISPLAY" q >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    cat "$WORK_DIR/xvfb.log" >&2
    echo "Host Xvfb exited before becoming ready." >&2
    exit 1
  fi
  if ((_xvfb_attempt == 200)); then
    cat "$WORK_DIR/xvfb.log" >&2
    echo "Host Xvfb did not become ready." >&2
    exit 1
  fi
  sleep 0.2
done

export MIDSCENE_RATE_GATE_UPSTREAM="$MIDSCENE_MODEL_BASE_URL"
export MIDSCENE_MODEL_BASE_URL="http://127.0.0.1:18783"
node "$ROOT_DIR/tests/e2e/model-rate-gate.mjs" >"$WORK_DIR/model-rate-gate.log" 2>&1 &
MODEL_GATE_PID=$!
for _gate_attempt in {1..100}; do
  if curl --silent --fail --max-time 1 "$MIDSCENE_MODEL_BASE_URL/healthz" >/dev/null; then
    break
  fi
  if ! kill -0 "$MODEL_GATE_PID" 2>/dev/null || ((_gate_attempt == 100)); then
    echo "Model rate gate did not become ready." >&2
    exit 1
  fi
  sleep 0.2
done

case "$MIDSCENE_PROJECT" in
  omarchy-shard-[1-4])
    npm --prefix tests/e2e test -- --project "$MIDSCENE_PROJECT"
    ;;
  omarchy-shell|omarchy-plugin-review)
    npm --prefix tests/e2e test -- --project "$MIDSCENE_PROJECT"
    ;;
  *)
    echo "Unsupported Omarchy Midscene project: $MIDSCENE_PROJECT" >&2
    exit 2
    ;;
esac
