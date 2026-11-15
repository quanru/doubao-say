"""Constants and configuration for Doubao Murmur Linux port.

Mirrors the fixed parameters from the macOS DoubaoASRClient.swift.
"""

import os
from pathlib import Path

# --- Doubao ASR WebSocket ---

WSS_BASE_URL = "wss://ws-samantha.doubao.com/samantha/audio/asr"

FIXED_QUERY_PARAMS = {
    "version_code": "20800",
    "language": "zh",
    "device_platform": "web",
    "aid": "497858",
    "real_aid": "497858",
    "pkg_type": "release_version",
    "pc_version": "3.12.3",
    "region": "",
    "sys_region": "",
    "samantha_web": "1",
    "use-olympus-account": "1",
    "format": "pcm",
}

ORIGIN = "https://www.doubao.com"
LOGIN_URL = "https://www.doubao.com/chat"

# --- Audio capture ---

AUDIO_SAMPLE_RATE = 16000
AUDIO_CHANNELS = 1
AUDIO_DTYPE = "int16"
AUDIO_BLOCKSIZE = 4096  # samples per callback (~256ms at 16kHz)

# --- Auth error detection ---

AUTH_ERROR_CODE = 709599054
AUTH_ERROR_KEYWORDS = [
    "cookie", "auth", "login", "session", "unauthorized", "expired",
]

# --- Paths ---

CONFIG_DIR_NAME = "doubao-say"
PARAMS_FILE = "asr_params.json"
KEYBOARD_FILE = "keyboard.json"


def get_config_dir() -> Path:
    """Get the XDG config directory for the app."""
    config_home = os.environ.get(
        "XDG_CONFIG_HOME", str(Path.home() / ".config")
    )
    app_dir = Path(config_home) / CONFIG_DIR_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_params_path() -> Path:
    """Get the path to the ASR params JSON file."""
    return get_config_dir() / PARAMS_FILE


def get_keyboard_config_path() -> Path:
    """Get the path to the on-screen keyboard geometry JSON file."""
    return get_config_dir() / KEYBOARD_FILE


# --- Timeouts ---

# Final packets may follow live text by several seconds. This is only a
# watchdog; explicit final results and the quiet-result timer finish sooner.
STOP_SAFETY_TIMEOUT = 5.0  # seconds
DEBOUNCE_INTERVAL = 0.3  # seconds
PASTE_DELAY = 0.05  # seconds between copy and paste simulation
AUTH_EXPIRY_DELAY = 2.0  # seconds before resetting after auth error

# --- Paste shortcut ---
# True  -> synthesize Ctrl+Shift+V for terminals such as kitty/Alacritty.
# False -> synthesize Ctrl+V. Works in GUI apps (VSCode, gedit, browser)
#          but NOT in terminals (terminals treat Ctrl+V as the tty "lnext"
#          literal-next-char escape, inherited from readline's history).
# Fallback when active-window detection is unavailable. On Hyprland the
# injector automatically chooses Ctrl+Shift+V for terminals and Ctrl+V otherwise.
INJECT_USE_SHIFT = False

# --- Overlay UI ---

OVERLAY_WIDTH = 760
OVERLAY_HEIGHT = 88
# Transcription text wraps within this many "characters" (Pango's average
# char-width unit ~= the old 760px text column) and the overlay grows in
# height up to OVERLAY_MAX_LINES before the oldest words scroll off.
OVERLAY_TEXT_CHARS = 88
OVERLAY_MAX_LINES = 5
PTT_BUTTON_SIZE = 60

# --- User-Agent for WebView ---

WEBVIEW_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
