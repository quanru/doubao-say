"""Interactive first-run acceptance with isolated credentials; no key listener.

Launch with the installed module on PYTHONPATH and the layer-shell preload.
The private temporary profile is retained for login persistence verification.
Never commit its contents or print authentication data.
"""
import os
from pathlib import Path
import tempfile

os.umask(0o077)
profile = Path(tempfile.mkdtemp(prefix="doubao-login-acceptance-"))
for variable, folder in (("XDG_CONFIG_HOME", "config"),
                         ("XDG_DATA_HOME", "data"),
                         ("XDG_CACHE_HOME", "cache")):
    directory = profile / folder
    directory.mkdir(mode=0o700)
    os.environ[variable] = str(directory)

from doubao_input.app import DoubaoInputApp

app = DoubaoInputApp()
# Share the production bus name: isolated credentials must not mean a second
# microphone/overlay owner. Quit the normal application before this rehearsal.
app.register(None)
if app.get_is_remote():
    raise SystemExit("Doubao is already running. Stop it before fresh-login acceptance.")
app.settings.doubao_key = 0
print(f"Isolated login acceptance profile: {profile}", flush=True)
raise SystemExit(app.run([]))
