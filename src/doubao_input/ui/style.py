"""Shared, theme-aware styling for Doubao Say's ordinary GTK windows."""
from gi.repository import Gtk


_CSS = """
.doubao-window {
  font-size: 15px;
}

.doubao-window .app-header {
  margin-bottom: 2px;
}

.doubao-window .app-title {
  font-size: 24px;
  font-weight: 700;
}

.doubao-window .step-navigation {
  background-color: alpha(@theme_fg_color, 0.055);
  border: 1px solid alpha(@theme_fg_color, 0.10);
  border-radius: 16px;
  padding: 6px;
}

.doubao-window .step-navigation button {
  min-height: 38px;
  border-radius: 11px;
  padding-left: 6px;
  padding-right: 6px;
  font-size: 22px;
  font-weight: 600;
}

.doubao-window .step-current {
  font-size: 16px;
  font-weight: 700;
}

.doubao-window .setup-card,
.doubao-window .polish-card {
  background-color: alpha(@theme_fg_color, 0.04);
  border: 1px solid alpha(@theme_fg_color, 0.09);
  border-radius: 18px;
  padding: 20px;
}

.doubao-window .polish-card {
  margin-top: 8px;
  padding: 16px;
}

.doubao-window .step-title {
  font-size: 26px;
  font-weight: 750;
}

.doubao-window .supporting-copy {
  opacity: 0.82;
}

.doubao-window button {
  min-height: 40px;
  border-radius: 12px;
  padding-left: 14px;
  padding-right: 14px;
}

.doubao-window entry,
.doubao-window dropdown,
.doubao-window spinbutton,
.doubao-window textview {
  border-radius: 10px;
}

.doubao-window .inline-feedback,
.doubao-window .window-feedback {
  background-color: alpha(@accent_bg_color, 0.13);
  border-radius: 10px;
  padding: 10px 12px;
}

.doubao-window .settings-section-title {
  margin-top: 14px;
  font-size: 17px;
  font-weight: 700;
}

.doubao-window .settings-row {
  background-color: alpha(@theme_fg_color, 0.035);
  border-radius: 12px;
  padding: 10px 12px;
}

.doubao-window expander {
  background-color: alpha(@theme_fg_color, 0.035);
  border-radius: 12px;
  padding: 10px 12px;
}
"""

_provider = None
_display = None


def apply_window_style(window):
    """Apply the shared style once per display and scope it to this window."""
    global _provider, _display
    window.add_css_class("doubao-window")
    display = window.get_display()
    if _provider is not None and _display == display:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _provider, _display = provider, display
