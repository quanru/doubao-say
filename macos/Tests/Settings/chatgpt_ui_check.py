"""Capture actual SwiftUI controls with synthetic accounts in an isolated bundle."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import threading
import uuid

binary = Path(sys.argv[1]).resolve()
output = Path(sys.argv[2]).resolve()
output.mkdir(parents=True, exist_ok=True)
bundle = output / "Doubao SIWC UI Verify.app"
executable = bundle / "Contents/MacOS/ChatGPTUICheck"
executable.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["ditto", str(binary), str(executable)], check=True)
(bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({
    "CFBundleIdentifier": "md.lifeos.doubao-say.siwc-ui." + uuid.uuid4().hex,
    "CFBundleName": "Doubao SIWC UI Verify", "CFBundleExecutable": "ChatGPTUICheck",
    "CFBundlePackageType": "APPL", "LSMinimumSystemVersion": "13.0", "LSUIElement": True,
}))
subprocess.run(["codesign", "--force", "--sign", "-", str(bundle)], check=True)
modes = os.environ.get("SIWC_UI_MODES", "disconnected,connected,quota,model-menu,model-select,model-keyboard,model-cancel,account-menu,empty-models,models-loading").split(",")
for language in ["en", "zh"]:
    for mode in modes:
        for theme in ["light", "dark"]:
            name = mode + "-" + language + "-" + theme
            image = output / (name + ".png")
            environment = dict(os.environ, SIWC_UI_CASE=mode, SIWC_UI_DARK="1" if theme == "dark" else "0")
            process = subprocess.Popen([str(executable), "-language", language], env=environment,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            timer = threading.Timer(15, process.kill)
            timer.start()
            lines = []
            captured = False
            try:
                for line in process.stdout:
                    lines.append(line)
                    if line.startswith("CAPTURE_WINDOW:"):
                        window = line.strip().split(":", 1)[1]
                        capture = subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-l", window, str(image)],
                            timeout=5, capture_output=True)
                        captured = capture.returncode == 0 and image.is_file()
                    elif line.startswith("CAPTURE_MENU:"):
                        window = line.strip().split(":", 1)[1]
                        menu_image = output / (name + ".menu.png")
                        capture = subprocess.run(["/usr/sbin/screencapture", "-x", "-o", "-l", window, str(menu_image)],
                            timeout=5, capture_output=True)
                        if capture.returncode or not menu_image.is_file():
                            raise RuntimeError("Dropdown screenshot failed")
                code = process.wait(timeout=2)
            finally:
                timer.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=2)
            (output / (name + ".log")).write_text("".join(lines))
            if code or not captured:
                raise SystemExit(code or 1)
            print(name + ": native window captured, isolated process exited")
