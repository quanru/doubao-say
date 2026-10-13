"""Provider switches must not change the owner of a pending credential draft."""
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from doubao_input.ui.settings_window import ASR_PROVIDERS, SettingsWindow
from doubao_input.ui.control_window import ControlWindow


class ASRKeyPersistenceTest(TestCase):
    def view(self):
        self.saved = {"deepgram": "synthetic-deepgram"}
        self.provider = "volcengine"
        self.draft = "synthetic-volcengine"
        entry = Mock()
        entry.get_text.side_effect = lambda: self.draft
        entry.set_text.side_effect = lambda text: setattr(self, "draft", text)
        view = SimpleNamespace(
            _updating=False, _asr_save_source=0, _asr_has_key=False, _asr_testing=False,
            asr_key=entry, asr_status=Mock(), asr_provider=Mock(), status=Mock(),
            _sync_provider_details=Mock(), _restore_controls=Mock(),
            _save_asr=lambda key: self.saved.__setitem__(self.provider, key),
            _asr_has_key_func=lambda: self.provider in self.saved,
        )
        view.asr_provider.get_selected.return_value = ASR_PROVIDERS.index("deepgram")
        def apply():
            self.provider = "deepgram"
            return True
        view._save_current = Mock(side_effect=apply)
        for name in ("_asr_provider_changed", "_save_asr_key_now", "flush_edits", "_flush_asr_key"):
            setattr(view, name, MethodType(getattr(SettingsWindow, name), view))
        return view

    def test_successful_key_clear_replaces_footer_error(self):
        view = self.view()
        view._clear_asr = Mock()
        view.status.set_text("API key could not be saved. Try again.")
        SettingsWindow._clear_asr_clicked(view)
        self.assertFalse(view._asr_has_key)
        view.status.set_text.assert_called_with("API key cleared.")

    def test_saved_and_pending_drafts_never_overwrite_other_provider(self):
        for already_saved in (False, True):
            with self.subTest(already_saved=already_saved):
                view = self.view()
                if already_saved:
                    self.assertTrue(view._save_asr_key_now())
                else:
                    view._asr_save_source = 42
                with patch("doubao_input.ui.settings_window.GLib.source_remove") as remove:
                    view._asr_provider_changed()
                    view._flush_asr_key()
                self.assertEqual(remove.call_count, 0 if already_saved else 1)
                self.assertEqual(self.saved, {"volcengine": "synthetic-volcengine",
                                              "deepgram": "synthetic-deepgram"})
                self.assertEqual(self.draft, "")
                self.assertEqual(view._asr_save_source, 0)

    def test_failed_draft_save_blocks_switch_and_keeps_draft_for_retry(self):
        view = self.view()
        view._save_asr = Mock(side_effect=OSError("synthetic write failure"))
        view._asr_provider_changed()
        view._save_current.assert_not_called()
        view._restore_controls.assert_called_once()
        self.assertEqual(self.draft, "synthetic-volcengine")
        self.assertEqual(self.saved, {"deepgram": "synthetic-deepgram"})
        view.status.set_text.assert_called_with("API key could not be saved. Try again.")

    def test_key_test_preserves_save_error_and_does_not_start_probe(self):
        view = self.view()
        view._save_asr = Mock(side_effect=OSError("synthetic write failure"))
        view._test_asr = Mock()
        SettingsWindow._test_asr_clicked(view)
        view._test_asr.assert_not_called()
        view.asr_status.set_text.assert_called_with("synthetic write failure")
        self.assertFalse(view._asr_testing)

    def test_failed_key_save_keeps_settings_open(self):
        view = self.view()
        view._save_asr = Mock(side_effect=OSError("synthetic write failure"))
        view.trigger_picker = Mock()
        view.vibekey_pickers = []
        self.assertTrue(SettingsWindow._close(view))
        view._save_current.assert_not_called()
        self.assertEqual(self.draft, "synthetic-volcengine")

    def test_provider_cannot_change_during_key_test(self):
        view = self.view()
        view._asr_testing = True
        view._asr_provider_changed()
        view._restore_controls.assert_called_once()
        view._save_current.assert_not_called()
        self.assertEqual(self.provider, "volcengine")

    def test_provider_switch_refreshes_placeholder_and_clears_old_result(self):
        for saved in (False, True):
            with self.subTest(saved=saved):
                view = self.view()
                if not saved:
                    self.saved.pop("deepgram")
                view._asr_provider_changed()
                view.asr_key.set_placeholder_text.assert_called_with(
                    "Saved — leave blank to keep" if saved else "Enter speech API key")
                if saved:
                    view.asr_status.set_text.assert_called_with("")


class OnboardingKeyPersistenceTest(TestCase):
    def view(self):
        self.saved = {"deepgram": "synthetic-deepgram"}
        self.provider = "volcengine"
        self.draft = "synthetic-volcengine"
        entry = Mock()
        entry.get_text.side_effect = lambda: self.draft
        entry.set_text.side_effect = lambda text: setattr(self, "draft", text)
        actions = Mock()
        actions.asr_has_key.side_effect = lambda: self.provider in self.saved
        actions.save_asr.side_effect = lambda key: self.saved.__setitem__(self.provider, key)
        actions.apply_asr_provider.side_effect = lambda provider: setattr(self, "provider", provider)
        actions.is_preview_testing.return_value = False
        view = SimpleNamespace(
            _changing_asr_provider=False, _asr_testing=False,
            _asr_key_save_source=0, _asr_key=entry, _asr_status=Mock(),
            _asr_provider=Mock(), _asr_test_button=Mock(), _actions=actions,
            _refresh=Mock(), set_feedback=Mock(), _window=Mock(),
        )
        view._asr_provider.get_selected.return_value = ASR_PROVIDERS.index("deepgram")
        for name in ("_asr_provider_changed", "_save_asr_key_now", "_flush_asr_key",
                     "_test_asr_clicked", "_asr_tested", "_sync_asr_controls", "hide"):
            setattr(view, name, MethodType(getattr(ControlWindow, name), view))
        return view

    def test_saved_and_pending_drafts_keep_their_provider(self):
        for already_saved in (False, True):
            with self.subTest(already_saved=already_saved):
                view = self.view()
                if already_saved:
                    self.assertTrue(view._save_asr_key_now())
                else:
                    view._asr_key_save_source = 42
                with patch("doubao_input.ui.control_window.GLib.source_remove"):
                    view._asr_provider_changed()
                    view._flush_asr_key()
                self.assertEqual(self.saved, {"volcengine": "synthetic-volcengine",
                                              "deepgram": "synthetic-deepgram"})
                self.assertEqual(self.draft, "")
                self.assertEqual(view._asr_key_save_source, 0)

    def test_empty_draft_does_not_require_credentials_to_switch(self):
        view = self.view()
        self.draft = ""
        view._asr_provider_changed()
        self.assertEqual(self.provider, "deepgram")
        view._actions.save_asr.assert_not_called()

    def test_saved_key_replaces_stale_provider_feedback(self):
        view = self.view()
        self.assertTrue(view._save_asr_key_now())
        view.set_feedback.assert_called_with("API key saved automatically.")

    def test_key_test_result_replaces_stale_feedback(self):
        for result, error, expected in (
            ("accepted", "", "accepted"),
            (None, "synthetic rejection", "Test failed: synthetic rejection"),
        ):
            with self.subTest(error=error):
                view = self.view()
                view._asr_tested(result, error)
                view.set_feedback.assert_called_with(expected)

    def test_empty_entry_reflects_saved_key_for_current_provider(self):
        view = self.view()
        self.draft = ""
        view._sync_asr_controls()
        view._asr_test_button.set_sensitive.assert_called_with(False)
        view._asr_key.set_placeholder_text.assert_called_with("Enter speech API key")
        self.provider = "deepgram"
        view._sync_asr_controls()
        view._asr_test_button.set_sensitive.assert_called_with(True)
        view._asr_key.set_placeholder_text.assert_called_with("Saved — leave blank to keep")

    def test_failed_save_preserves_provider_draft_and_visible_window(self):
        view = self.view()
        view._actions.save_asr.side_effect = OSError("synthetic write failure")
        view._asr_provider_changed()
        view.hide()
        self.assertEqual(self.provider, "volcengine")
        self.assertEqual(self.draft, "synthetic-volcengine")
        view.set_feedback.assert_called_with("synthetic write failure")
        view._window.set_visible.assert_not_called()

    def test_key_test_blocks_switch_and_restores_controls_on_completion(self):
        view = self.view()
        view._test_asr_clicked()
        self.assertEqual(self.draft, "")
        view._asr_provider.set_sensitive.assert_called_with(False)
        view._asr_provider_changed()
        self.assertEqual(self.provider, "volcengine")
        completed = view._actions.test_asr.call_args.args[1]
        completed("accepted", "")
        self.assertFalse(view._asr_testing)
        view._asr_provider.set_sensitive.assert_called_with(True)
