#!/bin/bash
set -euo pipefail

readonly ROOT_DIR="$PWD"
readonly MIDSCENE_PROJECT="${1:?Usage: run-omarchy-midscene.sh PROJECT}"
# Validate the bounded profile before defaults, VM setup, or model handling.
# PR48_RUNNER_GUARD_BEGIN
if [[ "$MIDSCENE_PROJECT" == omarchy-pr48-regression || -n "${PR48_REGRESSION_PROFILE:-}" ]]; then
  if [[ "$MIDSCENE_PROJECT" != omarchy-pr48-regression ||
        "${PR48_REGRESSION_PROFILE:-}" != matched-pr48 ||
        "${GITHUB_EVENT_NAME:-}" != workflow_dispatch ||
        "${GITHUB_REF:-}" != refs/heads/research/omarchy-plugin-visual-review ||
        "${PR48_BEFORE_SHA:-}" != c866b8fe03c18f0169b9327778ec9f620ac18095 ||
        "${PR48_AFTER_SHA:-}" != ed1dae4ecd097736ea92b76b09a31ca4df4f1aa2 ||
        -n "${REVIEW_PLUGIN_REPOSITORY:-}" || -n "${REVIEW_PLUGIN_SHA:-}" ||
        -n "${PR48_REQUEST_PLUGIN_ID:-}" || -n "${REVIEW_PLUGIN_ID:-}" ||
        -n "${REVIEW_PLUGIN_PROFILE:-}" || -n "${REVIEW_PLUGIN_OPEN_METHOD:-}" ||
        -n "${PR48_REQUEST_REVIEW_RUN_ID:-}" || -n "${REVIEW_BASE_REPOSITORY:-}" ||
        -n "${REVIEW_PR_NUMBER:-}" || -n "${PR48_REQUEST_VISIBLE_ASSERTION:-}" ||
        ( "${PR48_REQUEST_PLUGIN_OPEN_METHOD:-}" != '' && "${PR48_REQUEST_PLUGIN_OPEN_METHOD:-}" != auto ) ||
        ( "${PR48_REQUEST_BOOTSTRAP:-}" != '' && "${PR48_REQUEST_BOOTSTRAP:-}" != false ) ]]; then
    echo 'PR48 requires the trusted bounded profile, exact manual branch and commits, and no review/plugin/bootstrap payload.' >&2
    exit 1
  fi
  export MIDSCENE_MODEL_RETRY_COUNT=0
  export MIDSCENE_REPLANNING_CYCLE_LIMIT=4
  export MIDSCENE_RATE_GATE_MAX_REQUESTS=32
fi
# PR48_RUNNER_GUARD_END
readonly WORK_DIR="$ROOT_DIR/.midscene-omarchy"
readonly HARNESS_DIR="$WORK_DIR/omarchy-iso"
# shellcheck source=omarchy-vm.env
source "$ROOT_DIR/tests/e2e/omarchy-vm.env"
readonly ISO_PATH="$WORK_DIR/omarchy-${OMARCHY_ISO_VERSION}.iso"
readonly BASE_DIR="$HARNESS_DIR/test-runs/omarchy-${OMARCHY_ISO_VERSION}"
readonly SSH_KEY="$BASE_DIR/id_ed25519"
readonly SSH_PORT=2222
readonly PLUGIN_DIR="/home/omarchy/.config/omarchy/plugins/md.lifeos.doubao-say"
if [[ "$MIDSCENE_PROJECT" == omarchy-pr48-regression ]]; then
  readonly REVIEW_PLUGIN_REPOSITORY="" REVIEW_PLUGIN_ID="" REVIEW_PLUGIN_SHA=""
else
  readonly REVIEW_PLUGIN_REPOSITORY="${REVIEW_PLUGIN_REPOSITORY:-tathagat11/omarchy-checklist-todo}"
  readonly REVIEW_PLUGIN_ID="${REVIEW_PLUGIN_ID:-tathagat11.checklist-todo}"
  readonly REVIEW_PLUGIN_SHA="${REVIEW_PLUGIN_SHA:-0b8dfdbdc5dc1deaff178ad727fa22f6e289423a}"
fi
readonly REVIEW_PLUGIN_DIR="/home/omarchy/.config/omarchy/plugins/$REVIEW_PLUGIN_ID"
# Reject an attempted LookOut profile before booting a VM or handling secrets.
# LOOKOUT_RUNNER_GUARD_BEGIN
if [[ "${REVIEW_PLUGIN_PROFILE:-}" == lookout || "$REVIEW_PLUGIN_REPOSITORY" == dpaluy/omarchy-lookout || "$REVIEW_PLUGIN_ID" == dpaluy.lookout ]]; then
  if [[ "$MIDSCENE_PROJECT" != omarchy-plugin-smoke || "${REVIEW_PLUGIN_PROFILE:-}" != lookout ||
        "$REVIEW_PLUGIN_REPOSITORY" != dpaluy/omarchy-lookout ||
        "$REVIEW_PLUGIN_SHA" != 9dfdfc49178c7e4521ca6b41910920bf17c54d80 ||
        "$REVIEW_PLUGIN_ID" != dpaluy.lookout || "${REVIEW_PLUGIN_OPEN_METHOD:-}" != open ]]; then
    echo 'LookOut requires the trusted profile, exact pinned source, smoke project, and explicit open method.' >&2
    exit 1
  fi
  export MIDSCENE_MODEL_RETRY_COUNT=0
  export MIDSCENE_REPLANNING_CYCLE_LIMIT=4
  export MIDSCENE_RATE_GATE_MAX_REQUESTS=32
elif [[ -n "${REVIEW_PLUGIN_PROFILE:-}" ]]; then
  echo 'Unrecognized plugin review profile.' >&2
  exit 1
fi
# LOOKOUT_RUNNER_GUARD_END
readonly SHIM_DIR="$(mktemp -d)"
readonly PLUGIN_ARCHIVE="$(mktemp /tmp/doubao-say-omarchy-plugin-XXXXXX.tar)"
readonly REVIEW_PLUGIN_ARCHIVE="$(mktemp /tmp/omarchy-review-plugin-XXXXXX.tar.gz)"
readonly PR48_ARCHIVE_DIR="$(mktemp -d /tmp/omarchy-pr48-XXXXXX)"
export NODE_OPTIONS="${NODE_OPTIONS:-} --require=$ROOT_DIR/tests/e2e/node_modules/@computer-use/libnut/dist/import_libnut.js"
export OMARCHY_SSH_KEY="$SSH_KEY"

VM_PID=""
XVFB_PID=""
MODEL_GATE_PID=""

cleanup() {
  local result=$?
  if [[ "$MIDSCENE_PROJECT" == omarchy-pr48-regression && -n "$VM_PID" ]]; then
    if ! collect_pr48_evidence; then
      echo 'Could not collect complete bounded PR48 evidence before stopping the guest.' >&2
      result=1
    fi
  fi
  if ((result != 0)) && [[ -n $VM_PID ]] &&
      [[ $MIDSCENE_PROJECT == omarchy-plugin-smoke || $MIDSCENE_PROJECT == omarchy-plugin-review ]]; then
    echo 'Guest plugin service diagnostics (last 60 lines):' >&2
    ssh_session 'journalctl --user -u omarchy-shell -n 60 --no-pager' >&2 || true
  fi
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
  rm -rf "$PR48_ARCHIVE_DIR"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

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

collect_pr48_evidence() {
  # The guest contains only synthetic test data. Copy a small explicit allowlist,
  # never home/config files, process environments, unrestricted logs, or controls.
  local archive="$PR48_ARCHIVE_DIR/evidence.tar"
  local output="$ROOT_DIR/tests/e2e/midscene_run/pr48"
  mkdir -p "$output"
  if ! timeout --signal=TERM --kill-after=5s 30s ssh -i "$SSH_KEY" -p "$SSH_PORT" \
      -o BatchMode=yes -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=5 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 \
      -o LogLevel=ERROR omarchy@127.0.0.1 'python3 -' >"$archive" <<'PY'
# PR48_EVIDENCE_PACK_BEGIN
import pathlib
import re
import sys
import tarfile

root = pathlib.Path('/tmp/pr48-evidence')
allowed = re.compile(r'(?:environment|monitors|hyprland|packages|sources)\.json|(?:before|after)/(?:events\.jsonl|status\.json|provenance\.json|(?:ready|start|finish|exit)\.json|(?:ready|start_failed|listening|finished)-(?:status|layers)\.json|exception\.txt|[a-z0-9_-]+\.png)')
files = []
total = 0
for entry in sorted(root.glob('**/*')):
    relative = entry.relative_to(root).as_posix()
    if not allowed.fullmatch(relative):
        continue
    if entry.is_symlink() or any(parent.is_symlink() for parent in entry.parents) or not entry.is_file():
        raise SystemExit('Refusing non-regular PR48 evidence')
    size = entry.stat().st_size
    total += size
    if size > 8 * 1024 * 1024 or total > 48 * 1024 * 1024 or len(files) >= 40:
        raise SystemExit('PR48 evidence exceeds bounded collection limits')
    files.append((entry, relative))
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    for entry, relative in files:
        archive.add(entry, arcname=relative, recursive=False)
# PR48_EVIDENCE_PACK_END
PY
  then
    printf '%s\n' '{"collected":false,"reason":"bounded_guest_collection_failed"}' >"$output/collection.json"
    return 1
  fi
  # Independently reject paths, links, duplicates, and oversized data on the host.
  python3 - "$archive" "$output" <<'PY'
# PR48_EVIDENCE_UNPACK_BEGIN
import json
import pathlib
import re
import sys
import tarfile

destination = pathlib.Path(sys.argv[2])
allowed = re.compile(r'(?:environment|monitors|hyprland|packages|sources)\.json|(?:before|after)/(?:events\.jsonl|status\.json|provenance\.json|(?:ready|start|finish|exit)\.json|(?:ready|start_failed|listening|finished)-(?:status|layers)\.json|exception\.txt|[a-z0-9_-]+\.png)')
seen = set()
total = 0
with tarfile.open(sys.argv[1], mode='r:') as archive:
    for member in archive:
        total += member.size
        if (not member.isfile() or not allowed.fullmatch(member.name) or member.name in seen
                or member.size > 8 * 1024 * 1024 or total > 48 * 1024 * 1024 or len(seen) >= 40):
            raise SystemExit('Refusing unsafe or oversized PR48 evidence archive')
        seen.add(member.name)
        output = destination / member.name
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(archive.extractfile(member).read())
(destination / 'collection.json').write_text(json.dumps({'collected': True, 'files': sorted(seen), 'bytes': total}) + '\n')
# PR48_EVIDENCE_UNPACK_END
PY
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
  log "Booting Omarchy session for Midscene E2E"\
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
if [[ $MIDSCENE_PROJECT == omarchy-pr48-regression ]]; then
  # PR48_SOURCE_SETUP_BEGIN
  # Keep both product revisions separate from the trusted external harness and
  # the checkout. Download data on the host; execute product code only in guest.
  ssh_session "omarchy plugin disable md.lifeos.doubao-say || true"
  ssh_session "pkill -f '[d]oubao_input' || true"
  ssh_session "! pgrep -f '[d]oubao_input' >/dev/null"
  ssh_guest 'umask 077; mkdir -p /tmp/pr48-source/before /tmp/pr48-source/after /tmp/pr48-evidence'
  for variant in before after; do
    if [[ "$variant" == before ]]; then
      sha="$PR48_BEFORE_SHA"
      archive_sha256=dd3dce434ad5162c3cf4d807d774f087f7606a6c953ab1d9033abe48530577f1
    else
      sha="$PR48_AFTER_SHA"
      archive_sha256=36442aedc31ea2c4a99b6a3bde380252cf13c256253bebddf7e0d2c09512fc27
    fi
    archive="$PR48_ARCHIVE_DIR/$variant.tar.gz"
    curl --fail --location --silent --show-error --retry 0 \
      --connect-timeout 15 --max-time 90 --max-filesize 50000000 \
      "https://github.com/quanru/doubao-say/archive/$sha.tar.gz" --output "$archive"
    printf '%s  %s\n' "$archive_sha256" "$archive" | sha256sum --check --status
    timeout --signal=TERM --kill-after=5s 45s scp -i "$SSH_KEY" -P "$SSH_PORT" \
      -o BatchMode=yes -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ConnectTimeout=10 -o LogLevel=ERROR \
      "$archive" "omarchy@127.0.0.1:/tmp/pr48-$variant.tar.gz"
    ssh_guest "printf '%s  %s\\n' '$archive_sha256' '/tmp/pr48-$variant.tar.gz' | sha256sum --check --status && \
      tar -C '/tmp/pr48-source/$variant' --strip-components=1 --no-same-owner --no-same-permissions \
      -xzf '/tmp/pr48-$variant.tar.gz' 'doubao-say-$sha/src' && \
      test -f '/tmp/pr48-source/$variant/src/doubao_input/app.py' && \
      chmod -R a-w '/tmp/pr48-source/$variant'"
  done
  timeout --signal=TERM --kill-after=5s 30s scp -i "$SSH_KEY" -P "$SSH_PORT" \
    -o BatchMode=yes -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 -o LogLevel=ERROR \
    "$ROOT_DIR/tests/e2e/pr48_runtime_fixture.py" omarchy@127.0.0.1:/tmp/pr48-harness.py
  # Match the pinned source's install.sh dependencies, without running either
  # product installer or registering/launching the current branch's app.
  readonly PR48_PACKAGES='python python-gobject python-cairo gtk4 webkitgtk-6.0 pipewire portaudio gtk4-layer-shell wl-clipboard python-sounddevice python-websockets python-evdev'
  ssh_session_tty "printf '%s\\n' omarchy | sudo -S -v && \
    timeout --signal=TERM --kill-after=10s 360s sudo pacman -Sy --needed --noconfirm $PR48_PACKAGES"
  ssh_session "python3 -c \"import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Gdk', '4.0'); gi.require_version('GdkX11', '4.0'); from gi.repository import Gtk, Gdk, GdkX11; import cairo, sounddevice, websockets, evdev\" && \
    ! pgrep -f '[d]oubao_input' >/dev/null"
  ssh_session "hyprctl -j monitors | jq '{monitor_count:length,monitors:map({width,height,scale,transform})}' >/tmp/pr48-evidence/monitors.json && \
    hyprctl -j version | jq '{tag,commit,branch,dirty}' >/tmp/pr48-evidence/hyprland.json && \
    pacman -Q $PR48_PACKAGES | jq -Rn '[inputs | split(\" \") | {package:.[0],version:.[1]}]' >/tmp/pr48-evidence/packages.json && \
    jq -n --arg iso_version '$OMARCHY_ISO_VERSION' --arg iso_sha256 '$OMARCHY_ISO_SHA256' \
      --arg harness_sha '$OMARCHY_ISO_HARNESS_SHA' \
      '{iso_version:\$iso_version,iso_sha256:\$iso_sha256,harness_sha:\$harness_sha,source_setup:\"separate-pinned-source-no-product-install\",session:\"single-disposable-Omarchy-VM\"}' >/tmp/pr48-evidence/environment.json && \
    jq -n --arg before '$PR48_BEFORE_SHA' --arg after '$PR48_AFTER_SHA' \
      '{repository:\"quanru/doubao-say\",before:\$before,after:\$after,archive_sha256:{before:\"dd3dce434ad5162c3cf4d807d774f087f7606a6c953ab1d9033abe48530577f1\",after:\"36442aedc31ea2c4a99b6a3bde380252cf13c256253bebddf7e0d2c09512fc27\"}}' >/tmp/pr48-evidence/sources.json"
  # PR48_SOURCE_SETUP_END
elif [[ $MIDSCENE_PROJECT == omarchy-plugin-review || $MIDSCENE_PROJECT == omarchy-plugin-smoke ]]; then
  [[ $REVIEW_PLUGIN_REPOSITORY =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
  [[ $REVIEW_PLUGIN_SHA =~ ^[a-fA-F0-9]{40}$ ]]
  [[ $REVIEW_PLUGIN_ID =~ ^[a-z0-9][a-z0-9._-]{2,127}$ ]]
  if [[ ${REVIEW_PLUGIN_OPEN_METHOD:-} == launch && $REVIEW_PLUGIN_ID == md.lifeos.doubao-say ]]; then
    # The reusable base VM has a keepLoaded Service.qml that respawns Doubao
    # Say after a kill. Disable that service before stopping the old GTK
    # single-instance app; enable it again after installing the PR checkout.
    ssh_session "omarchy plugin disable '$REVIEW_PLUGIN_ID' || true"
    ssh_session "pgrep -af '[d]oubao_input' || true"
    ssh_session "pkill -f '[d]oubao_input' || true"
    ssh_session "! pgrep -f '[d]oubao_input' >/dev/null"
  fi
  curl --fail --location --silent --show-error --retry 3 \
    --max-time 90 --max-filesize 50000000 \
    "https://github.com/$REVIEW_PLUGIN_REPOSITORY/archive/$REVIEW_PLUGIN_SHA.tar.gz" \
    --output "$REVIEW_PLUGIN_ARCHIVE"
  ssh_guest "rm -rf '$REVIEW_PLUGIN_DIR' && mkdir -p '$REVIEW_PLUGIN_DIR'"
  scp -i "$SSH_KEY" -P "$SSH_PORT" \
    -o BatchMode=yes -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -o ConnectTimeout=10 -o LogLevel=ERROR \
    "$REVIEW_PLUGIN_ARCHIVE" omarchy@127.0.0.1:/tmp/omarchy-review-plugin.tar.gz
  ssh_session "tar -C '$REVIEW_PLUGIN_DIR' --strip-components=1 -xzf /tmp/omarchy-review-plugin.tar.gz && \
    test \"\$(jq -r .id '$REVIEW_PLUGIN_DIR/manifest.json')\" = '$REVIEW_PLUGIN_ID' && \
    omarchy plugin validate '$REVIEW_PLUGIN_DIR' && \
    omarchy-shell shell rescanPlugins"
  if [[ ${REVIEW_PLUGIN_OPEN_METHOD:-open} == launch ]]; then
    # Service plugins may need system libraries before their background process
    # can start. Install only inside the disposable guest at the pinned SHA.
    ssh_session "test -x '$REVIEW_PLUGIN_DIR/start.sh' && test -x '$REVIEW_PLUGIN_DIR/install.sh'"
    ssh_session_tty "printf '%s\\n' omarchy | sudo -S -v && \
      sudo pacman -Sy --noconfirm && '$REVIEW_PLUGIN_DIR/install.sh' --yes"
  fi
  if [[ ${REVIEW_PLUGIN_OPEN_METHOD:-} == launch && $REVIEW_PLUGIN_ID == md.lifeos.doubao-say ]]; then
    # Catch an old service that restarted while dependencies were installed.
    ssh_session "! pgrep -f '[d]oubao_input' >/dev/null"
  fi
  review_enable_output=""
  review_enabled=false
  for _review_attempt in {1..30}; do
    if review_enable_output="$(ssh_session "omarchy plugin enable '$REVIEW_PLUGIN_ID' --section '${REVIEW_PLUGIN_SECTION:-right}'" 2>&1)"; then
      echo "$review_enable_output"
      review_enabled=true
      break
    fi
    if [[ $review_enable_output != *"is not known"* ]]; then
      echo "Review plugin enable failed: $review_enable_output" >&2
      exit 1
    fi
    ssh_session "omarchy-shell shell rescanPlugins" || true
    sleep 1
  done
  if [[ $review_enabled != true ]]; then
    echo "Review plugin was not recognized after rescan: $review_enable_output" >&2
    exit 1
  fi
  if [[ ${REVIEW_PLUGIN_OPEN_METHOD:-} == launch && $REVIEW_PLUGIN_ID == md.lifeos.doubao-say ]]; then
    ssh_session "pgrep -af '[d]oubao_input' || true"
    ssh_session "for pid in \$(pgrep -f '^/usr/bin/python3 -m doubao_input --background$'); do \
      tr '\\0' '\\n' </proc/\$pid/environ | grep '^PYTHONPATH='; \
      tr '\\0' '\\n' </proc/\$pid/environ | grep -F 'PYTHONPATH=$REVIEW_PLUGIN_DIR/src' >/dev/null || exit 1; \
    done"
  fi
  if [[ $MIDSCENE_PROJECT == omarchy-plugin-review ]]; then
    # The pinned Checklist Todo widget registers its IPC target after mounting.
    review_status=""
    for _review_attempt in {1..30}; do
      if review_status="$(ssh_session "omarchy-shell '$REVIEW_PLUGIN_ID' status" 2>/dev/null)" &&
          [[ $review_status == '0 todos' ]]; then
        break
      fi
      sleep 1
    done
    if [[ $review_status != '0 todos' ]]; then
      echo "Checklist Todo IPC did not become ready: $review_status" >&2
      ssh_session "journalctl --user -u omarchy-shell -n 80 --no-pager" || true
      exit 1
    fi
  fi
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

fi

# First-run Omarchy notifications can obscure a PR's UI and lead the visual
# agent to open the system updater. Dismiss them for every desktop project.
ssh_session "omarchy-shell notifications dismissAll"

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

if [[ "${REVIEW_PLUGIN_PROFILE:-}" == lookout || "${PR48_REGRESSION_PROFILE:-}" == matched-pr48 ]]; then
  mkdir -p "$ROOT_DIR/tests/e2e/midscene_run"
  export MIDSCENE_RATE_GATE_STATE_FILE="$ROOT_DIR/tests/e2e/midscene_run/model-request-count.json"
fi
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
  omarchy-pr48-regression)
    # Leave time for bounded evidence collection before the 25-minute job cap.
    timeout --signal=TERM --kill-after=10s 12m npm --prefix tests/e2e test -- --project "$MIDSCENE_PROJECT"
    ;;
  omarchy-shard-[1-4])
    npm --prefix tests/e2e test -- --project "$MIDSCENE_PROJECT"
    ;;
  omarchy-plugin-smoke)
    if [[ "${REVIEW_PLUGIN_PROFILE:-}" == lookout ]]; then
      cp tests/e2e/cases/omarchy-lookout-review.yaml tests/e2e/cases/omarchy-plugin-smoke.yaml
    else
      node tests/e2e/render-omarchy-plugin-smoke.mjs
    fi
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
