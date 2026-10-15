from pathlib import Path
p=Path('work/iso/bin/omarchy-iso-test');s=p.read_text()
start=s.index('\nacceptance_phase() {\n');end=s.index('\n# ---------------------------------------------------------------------- main',start)
s=s[:start]+'''
acceptance_phase() {
  qemu-img create -f qcow2 -b "$BASE_DISK" -F qcow2 "$RUN_DIR/run.qcow2" >/dev/null
  start_vm "$RUN_DIR/run.qcow2" "$RUN_DIR/serial.log"
  establish_session
  capture_console "success-candidate-session"
  (umask 077; printf '%s\\n' "$SSH_KEY" "$QMP_SOCK" "$(cat "$PIDFILE")" "$RUN_DIR" > "$ACCEPTANCE_STATE")
}
'''+s[end:]
Path('work/iso/bin/acceptance-session').write_text(s)
