from pathlib import Path
p=Path('work/iso/bin/omarchy-iso-test');s=p.read_text()
start=s.index('\nacceptance_phase() {\n');end=s.index('\n# ---------------------------------------------------------------------- main',start)
s=s[:start]+'''
acceptance_phase() {
  qemu-img create -f qcow2 -b "$BASE_DISK" -F qcow2 "$RUN_DIR/run.qcow2" >/dev/null
  start_vm "$RUN_DIR/run.qcow2" "$RUN_DIR/serial.log"
  establish_session
  # Optional configtool is documented by Omarchy; install through its helper.
  # Authenticate only in this disposable guest's PTY, using the harness test account.
  ssh -tt -i "$SSH_KEY" -p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "$GUEST_USER@127.0.0.1" "echo $GUEST_PASSWORD | sudo -S -v && export PATH=/usr/share/omarchy/bin:\\$PATH; /usr/share/omarchy/bin/omarchy-pkg-add fcitx5-configtool" </dev/null
  # Permit read-only input observation only inside this disposable test guest.
  ssh_guest "echo $GUEST_PASSWORD | sudo -S chmod a+r /dev/input/event*" >/dev/null
  capture_console "success-candidate-session"
  (umask 077; printf '%s\\n' "$SSH_KEY" "$QMP_SOCK" "$(cat "$PIDFILE")" "$RUN_DIR" > "$ACCEPTANCE_STATE")
}
'''+s[end:]
Path('work/iso/bin/acceptance-session').write_text(s)
