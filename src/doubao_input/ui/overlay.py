"""Bottom-centred, Voxtype-style recording overlay for Wayland.

The public methods are safe to call from worker threads. GTK work is
marshalled to the main loop while audio samples remain plain Python state
until the next animation frame.
"""
from __future__ import annotations

import array
import logging
import math
import threading
import time
import tomllib
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
from doubao_input.i18n import tr
from doubao_input.ui.voice_motion import VoiceMotion
from doubao_input.ui.waveform import draw_waveform
from doubao_input.product import VERSION

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # type: ignore

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell  # type: ignore
except (ImportError, ValueError):
    Gtk4LayerShell = None

if TYPE_CHECKING:
    from doubao_input.doubao.app_state import AppState

logger = logging.getLogger(__name__)

# Voxtype's 400x48 OSD gains one compact line for the live transcript.
OVERLAY_WIDTH = 400
OVERLAY_HEIGHT = 86
BOTTOM_MARGIN = 24
CORNER_PX = 12

CANVAS_WIDTH = 368
CANVAS_HEIGHT = 31
TICK_MS = 16
PEAK_DECAY_DB_PER_SECOND = 6.0
RMS_FLOOR_DB = -48.0

DEFAULT_THEME = {
    "accent": "#7aa2f7",
    "background": "#1a1b26",
    "muted": "#414868",
    "red": "#f7768e",
    "yellow": "#e0af68",
    "green": "#9ece6a",
    "bright_foreground": "#c0caf5",
}

STATE_BORDER_KEYS = {
    "idle": "muted",
    "starting": "red",
    "recording": "accent",
    "stopping": "yellow",
}


class Overlay:
    """Non-focusable layer-shell overlay with waveform, meter and live text."""

    def __init__(self, app_state: AppState | None = None) -> None:
        self._main_thread_id = threading.get_ident()
        self.reduced_motion = False
        self.waveform_style = "bars"
        self._app_state = app_state
        self._window: Gtk.Window | None = None
        self._label: Gtk.Label | None = None
        self._status_label: Gtk.Label | None = None
        self._canvas: Gtk.Picture | None = None
        self._panel: Gtk.Box | None = None
        self._css_provider: Gtk.CssProvider | None = None
        self._canvas_texture: Gdk.Texture | None = None
        self._update_info = None
        self._update_button = None

        self._audio_lock = threading.Lock()
        self._latest_rms = 0.0
        self._latest_rms_at = time.monotonic()
        self._peak_db = RMS_FLOOR_DB
        self._meter_db = RMS_FLOOR_DB
        self._last_peak_tick = time.monotonic()
        self._motion = VoiceMotion()

        self._ticker_src: int | None = None
        self._status_text = ""
        self._status_priority = False
        self._text = ""
        self._state = "idle"
        self._visible = False
        self._theme = _load_omarchy_theme()

        if app_state is not None:
            self._state = app_state.recording_state.value
            app_state.connect(
                "recording-state-changed", self._on_recording_state_changed
            )

    # ---- public API ----

    def show(self, status: str | None = None) -> None:
        self._run_on_main(self._show, status or tr("Listening…", "聆听中…"))

    def hide(self) -> None:
        self._run_on_main(self._hide)

    def set_text(self, text: str) -> None:
        self._run_on_main(self._set_text, text)

    def set_status(self, status: str) -> None:
        self._run_on_main(self._set_status, status)

    def set_update(self, info) -> None:
        self._run_on_main(self._set_update, info)

    def _set_update(self, info):
        self._update_info = info
        if self._update_button is not None:
            message = tr(
                f"Doubao Say {info.version} is available (current: {VERSION}). Finish dictation, then open the control center to update.",
                f"豆包说 {info.version} 已发布（当前：{VERSION}）。结束听写后，可在控制中心打开更新页面。")
            self._update_button.set_tooltip_text(message)
            self._update_message.set_text(message)
            self._update_button.set_visible(True)

    def push_rms(self, rms: float) -> None:
        """Accept a linear [0, 1] RMS value from the audio callback thread."""
        level = max(0.0, min(1.0, float(rms)))
        with self._audio_lock:
            self._latest_rms = level
            self._latest_rms_at = time.monotonic()
            db = _linear_to_db(level)
            self._meter_db = db
            if db > self._peak_db:
                self._peak_db = db

    def on_keystroke(self) -> None:
        """Keep the legacy hook; fresh text is already visible immediately."""
        self._run_on_main(self._arm_ticker)

    # ---- main-thread operations ----

    def _run_on_main(self, callback, *args) -> None:
        if threading.get_ident() == self._main_thread_id:
            callback(*args)
            return

        def invoke() -> bool:
            callback(*args)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(invoke)

    def _show(self, status: str) -> None:
        self._ensure_window()
        self._text = ""
        self._status_text = status
        self._status_priority = True
        self._refresh_label()
        if self._window is not None and not self._visible:
            self._window.set_visible(True)
            self._visible = True
        self._arm_ticker()

    def _hide(self) -> None:
        self._motion = VoiceMotion()
        if self._update_button:
            self._update_button.popdown()
        if self._window is not None and self._visible:
            self._window.set_visible(False)
            self._visible = False
        if self._ticker_src is not None:
            GLib.source_remove(self._ticker_src)
            self._ticker_src = None
        with self._audio_lock:
            self._latest_rms = 0.0
            self._latest_rms_at = time.monotonic()
            self._peak_db = RMS_FLOOR_DB
            self._meter_db = RMS_FLOOR_DB

    def _set_text(self, text: str) -> None:
        grew = len(text) > len(self._text)
        self._text = text
        self._status_priority = False
        if self._window is not None:
            self._refresh_label()
            if grew:
                self._arm_ticker()

    def _set_status(self, status: str) -> None:
        self._status_text = status
        self._status_priority = True
        if self._window is not None:
            self._refresh_label()

    def _on_recording_state_changed(self, _state, value: str) -> None:
        self._run_on_main(self._apply_state, value)

    def _apply_state(self, value: str) -> None:
        self._state = value
        if self._css_provider is not None:
            self._load_css()
        if not self._text:
            state_status = {
                "starting": tr("Starting voice recognition…", "正在启动语音识别…"),
                "recording": tr("Listening…", "正在聆听…"),
                "stopping": tr("Transcribing…", "正在转写…"),
            }.get(value)
            if state_status:
                self._status_text = state_status
                self._status_priority = True
                self._refresh_label()

    def _ensure_window(self) -> None:
        if self._window is not None:
            return

        win = Gtk.Window()
        win.set_title("Doubao Say overlay")
        win.set_decorated(False)
        win.set_resizable(False)
        win.set_default_size(OVERLAY_WIDTH, OVERLAY_HEIGHT)
        win.set_size_request(OVERLAY_WIDTH, OVERLAY_HEIGHT)
        win.set_focus_on_click(False)
        win.set_can_focus(False)
        win.add_css_class("doubao-overlay")

        # Layer-shell must be initialized before the window is realized.
        if Gtk4LayerShell is not None:
            try:
                Gtk4LayerShell.init_for_window(win)
                Gtk4LayerShell.set_namespace(win, "doubao-say-overlay")
                Gtk4LayerShell.set_layer(win, Gtk4LayerShell.Layer.OVERLAY)
                Gtk4LayerShell.set_anchor(
                    win, Gtk4LayerShell.Edge.BOTTOM, True
                )
                Gtk4LayerShell.set_anchor(win, Gtk4LayerShell.Edge.TOP, False)
                Gtk4LayerShell.set_anchor(win, Gtk4LayerShell.Edge.LEFT, False)
                Gtk4LayerShell.set_anchor(win, Gtk4LayerShell.Edge.RIGHT, False)
                Gtk4LayerShell.set_margin(
                    win, Gtk4LayerShell.Edge.BOTTOM, BOTTOM_MARGIN
                )
                Gtk4LayerShell.set_keyboard_mode(
                    win, Gtk4LayerShell.KeyboardMode.NONE
                )
            except Exception:
                logger.exception("Could not initialize gtk4-layer-shell")
        else:
            logger.warning(
                "Gtk4LayerShell unavailable; compositor will choose overlay position"
            )

        panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        panel.set_hexpand(True)
        panel.set_vexpand(True)
        panel.set_halign(Gtk.Align.FILL)
        panel.set_valign(Gtk.Align.FILL)
        panel.add_css_class("doubao-overlay-panel")

        canvas = Gtk.Picture()
        canvas.set_size_request(CANVAS_WIDTH, CANVAS_HEIGHT)
        canvas.set_can_shrink(False)
        canvas.set_halign(Gtk.Align.CENTER)
        waveform = Gtk.Overlay()
        waveform.set_child(canvas)
        self._update_button = Gtk.MenuButton(label="", visible=False)
        self._update_button.set_direction(Gtk.ArrowType.NONE)
        self._update_button.set_halign(Gtk.Align.END)
        self._update_button.set_valign(Gtk.Align.START)
        self._update_button.set_focus_on_click(False)
        self._update_button.set_has_frame(False)
        self._update_button.add_css_class("doubao-update")
        self._update_button.set_tooltip_text(tr("Update available", "有新版本"))
        update_dot = Gtk.Box()
        update_dot.set_size_request(8, 8)
        self._update_button.set_child(update_dot)
        button_css = Gtk.CssProvider()
        button_css.load_from_data(
            b"button { background: transparent; padding: 4px; min-height: 0; "
            b"min-width: 0; border: 0; box-shadow: none; }")
        self._update_button.get_first_child().get_style_context().add_provider(
            button_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        dot_css = Gtk.CssProvider()
        dot_css.load_from_data(
            b"box { background: #c53b53; min-height: 8px; min-width: 8px; "
            b"border-radius: 999px; }")
        update_dot.get_style_context().add_provider(
            dot_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        popover = Gtk.Popover()
        self._update_message = Gtk.Label(wrap=True, max_width_chars=32)
        for side in ("start", "end", "top", "bottom"):
            getattr(self._update_message, "set_margin_" + side)(10)
        popover.set_child(self._update_message)
        self._update_button.set_popover(popover)
        waveform.add_overlay(self._update_button)
        panel.append(waveform)
        if self._update_info:
            self._set_update(self._update_info)

        self._status_label = Gtk.Label()
        self._status_label.add_css_class("doubao-overlay-label")
        panel.append(self._status_label)

        label = Gtk.Label()
        label.set_xalign(0.5)
        label.set_yalign(0.5)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_single_line_mode(True)
        label.set_ellipsize(Pango.EllipsizeMode.START)
        label.set_hexpand(True)
        label.add_css_class("doubao-overlay-label")
        panel.append(label)

        self._window = win
        self._panel = panel
        self._canvas = canvas
        self._label = label
        self._css_provider = Gtk.CssProvider()
        self._load_css()
        panel.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        win.get_style_context().add_provider(
            self._css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        win.set_child(panel)
        self._render_canvas()

    def _load_css(self) -> None:
        if self._css_provider is None:
            return
        border_key = STATE_BORDER_KEYS.get(self._state, "muted")
        border = self._theme[border_key]
        background = _hex_to_rgb(self._theme["background"])
        css = f"""
            window.doubao-overlay {{
                background: transparent;
            }}
            .doubao-overlay-panel {{
                background-color: rgba(
                    {background[0]}, {background[1]}, {background[2]}, 0.85
                );
                border: 1px solid {border};
                border-radius: {CORNER_PX}px;
                padding: 5px 15px 4px 15px;
            }}
            .doubao-overlay-label {{
                color: {self._theme['bright_foreground']};
                font-size: 12px;
                font-weight: 500;
                min-height: 17px;
            }}
        """
        try:
            self._css_provider.load_from_data(css.encode("utf-8"))
        except TypeError:
            self._css_provider.load_from_data(css)

    def _refresh_label(self) -> None:
        if self._label is None:
            return
        self._status_label.set_text(self._status_text)
        display = self._text[-600:]
        self._label.set_markup(escape(display))
        self._label.set_tooltip_text(display or None)

    def _arm_ticker(self) -> None:
        if self._ticker_src is None and self._visible:
            self._last_peak_tick = time.monotonic()
            self._ticker_src = GLib.timeout_add(250 if self.reduced_motion else TICK_MS, self._tick)

    def _tick(self) -> bool:
        if not self._visible or self._window is None or self._canvas is None:
            self._ticker_src = None
            return GLib.SOURCE_REMOVE

        now = time.monotonic()
        elapsed = max(0.0, now - self._last_peak_tick)
        self._last_peak_tick = now
        with self._audio_lock:
            since_sample = max(0.0, now - self._latest_rms_at)
            current_db = max(
                RMS_FLOOR_DB,
                _linear_to_db(self._latest_rms)
                - PEAK_DECAY_DB_PER_SECOND * since_sample,
            )
            self._meter_db = current_db
            self._peak_db = max(
                current_db,
                self._peak_db - PEAK_DECAY_DB_PER_SECOND * elapsed,
            )
            rms = self._latest_rms
        self._motion.advance(rms, since_sample, elapsed)
        self._render_canvas()
        return GLib.SOURCE_CONTINUE

    def _render_canvas(self) -> None:
        if self._canvas is None:
            return
        try:
            surface = cairo.ImageSurface(
                cairo.FORMAT_ARGB32, CANVAS_WIDTH, CANVAS_HEIGHT
            )
            cr = cairo.Context(surface)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)

            accent = _hex_to_unit_rgb(self._theme["accent"])
            foreground = _hex_to_unit_rgb(self._theme["bright_foreground"])
            draw_waveform(cr, self.waveform_style, self._motion,
                          CANVAS_WIDTH, CANVAS_HEIGHT, accent, foreground,
                          reduced_motion=self.reduced_motion)

            texture = _image_surface_to_texture(surface)
            self._canvas.set_paintable(texture)
            self._canvas_texture = texture
        except Exception:
            logger.exception("Could not render overlay waveform")


def _load_omarchy_theme() -> dict[str, str]:
    theme = dict(DEFAULT_THEME)
    colors_path = (
        Path.home() / ".local/state/omarchy/current/theme/colors.toml"
    )
    try:
        values = tomllib.loads(colors_path.read_text(encoding="utf-8"))
        for key in theme:
            value = values.get(key)
            if isinstance(value, str) and _valid_hex_color(value):
                theme[key] = value
    except (OSError, tomllib.TOMLDecodeError):
        logger.debug("Using built-in Tokyo Night overlay colors", exc_info=True)
    return theme


def _valid_hex_color(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    channels = tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))
    return channels  # type: ignore[return-value]


def _hex_to_unit_rgb(value: str) -> tuple[float, float, float]:
    return tuple(channel / 255 for channel in _hex_to_rgb(value))


def _linear_to_db(value: float) -> float:
    if value <= 0:
        return RMS_FLOOR_DB
    return max(RMS_FLOOR_DB, 20.0 * math.log10(value))


def _db_to_normalized(value: float) -> float:
    return max(0.0, min(1.0, (value - RMS_FLOOR_DB) / -RMS_FLOOR_DB))


def _image_surface_to_texture(surface: cairo.ImageSurface) -> Gdk.Texture:
    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    data = array.array("B", surface.get_data())
    # Cairo ARGB32 is native-endian BGRA on this machine; Gdk expects RGBA.
    for index in range(0, len(data), 4):
        data[index], data[index + 2] = data[index + 2], data[index]
    return Gdk.MemoryTexture.new(
        width,
        height,
        Gdk.MemoryFormat.R8G8B8A8_PREMULTIPLIED,
        GLib.Bytes.new(bytes(data)),
        stride,
    )
