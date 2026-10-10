from unittest import TestCase

from doubao_input.doubao.asr_client import ASRClient
from doubao_input.doubao.params_store import ParamsStore
from doubao_input.doubao.volcengine_asr_client import VolcengineASRClient
from doubao_input.doubao.volcengine_credentials import VolcengineCredentialsStore
from doubao_input.deepgram.asr_client import DeepgramASRClient
from doubao_input.deepgram.credentials import DeepgramCredentialsStore
from doubao_input.voxtype.asr_client import VoxtypeASRClient
from doubao_input.voxtype.runtime import VoxtypeRuntimeStore
from doubao_input.recognition_providers import (
    RECOGNITION_PROVIDER_IDS,
    recognition_provider,
    recognition_providers,
)


class RecognitionProviderRegistryTest(TestCase):
    def test_registry_order_drives_persisted_ids_and_ui_names(self):
        providers = recognition_providers()
        self.assertEqual(
            RECOGNITION_PROVIDER_IDS,
            tuple(provider.id for provider in providers),
        )
        self.assertEqual(
            [provider.name for provider in providers],
            [
                "Doubao account",
                "Volcengine official API",
                "Deepgram Nova-3 (English)",
                "Voxtype (local)",
            ],
        )

    def test_registry_owns_runtime_backend_configuration(self):
        doubao = recognition_provider("doubao")
        self.assertIsInstance(doubao.new_client(), ASRClient)
        self.assertIs(doubao.credential_store, ParamsStore)
        self.assertTrue(doubao.interactive_auth)
        official = recognition_provider("volcengine")
        self.assertIsInstance(official.new_client(), VolcengineASRClient)
        self.assertIs(official.credential_store, VolcengineCredentialsStore)
        self.assertFalse(official.interactive_auth)
        deepgram = recognition_provider("deepgram")
        self.assertIsInstance(deepgram.new_client(), DeepgramASRClient)
        self.assertIs(deepgram.credential_store, DeepgramCredentialsStore)
        self.assertTrue(deepgram.uses_api_key)
        self.assertIn("Nova-3", deepgram.credential_help)
        voxtype = recognition_provider("voxtype")
        self.assertIsInstance(voxtype.new_client(), VoxtypeASRClient)
        self.assertIs(voxtype.credential_store, VoxtypeRuntimeStore)
        self.assertTrue(voxtype.is_local)

    def test_unknown_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported recognition service"):
            recognition_provider("missing")
