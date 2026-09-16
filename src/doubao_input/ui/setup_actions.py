"""Narrow setup commands/queries, independent of GTK and application internals."""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class SetupActions:
    test_voice: Callable[[], None]
    cancel_preview: Callable[[], None]
    open_settings: Callable[[], None]
    is_preview_testing: Callable[[], bool]
    summary: Callable[[], dict] = lambda: {}
    complete_setup: Callable[[], None] = lambda: None
    apply_key: Callable[[int, tuple[int, ...]], None] = lambda key, modifiers=(): None
    capture_key: Callable | None = None
    cancel_key_capture: Callable[[], None] = lambda: None
    polish_settings: Callable[[], object] = lambda: None
    polish_has_key: Callable[[], bool] = lambda: False
    save_polish: Callable = lambda settings, key: None
    test_polish: Callable = lambda settings, key, done: None
    apply_microphone: Callable[[str], None] = lambda device: None
    apply_asr_provider: Callable[[str], None] = lambda provider: None
