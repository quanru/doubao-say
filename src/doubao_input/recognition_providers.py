"""Recognition provider registry shared by settings, UI, and runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from doubao_input.i18n import tr


class CredentialStore(Protocol):
    @classmethod
    def load(cls): ...

    @classmethod
    def clear(cls) -> None: ...

    @classmethod
    def has_saved(cls) -> bool: ...


@dataclass(frozen=True)
class RecognitionProvider:
    id: str
    name_en: str
    name_zh: str
    client_factory: Callable[[], object]
    credential_store_factory: Callable[[], type[CredentialStore]]
    interactive_auth: bool
    clear_rejected_credentials: bool

    @property
    def name(self) -> str:
        return tr(self.name_en, self.name_zh)

    def new_client(self):
        return self.client_factory()

    @property
    def credential_store(self) -> type[CredentialStore]:
        return self.credential_store_factory()


def _doubao_client():
    from doubao_input.doubao.asr_client import ASRClient
    return ASRClient()


def _doubao_store():
    from doubao_input.doubao.params_store import ParamsStore
    return ParamsStore


def _volcengine_client():
    from doubao_input.doubao.volcengine_asr_client import VolcengineASRClient
    return VolcengineASRClient()


def _volcengine_store():
    from doubao_input.doubao.volcengine_credentials import VolcengineCredentialsStore
    return VolcengineCredentialsStore


_PROVIDERS = (
    RecognitionProvider(
        id="doubao",
        name_en="Doubao account",
        name_zh="豆包账号",
        client_factory=_doubao_client,
        credential_store_factory=_doubao_store,
        interactive_auth=True,
        clear_rejected_credentials=True,
    ),
    RecognitionProvider(
        id="volcengine",
        name_en="Volcengine official API",
        name_zh="火山引擎官方 API",
        client_factory=_volcengine_client,
        credential_store_factory=_volcengine_store,
        interactive_auth=False,
        clear_rejected_credentials=False,
    ),
)

RECOGNITION_PROVIDER_IDS = tuple(provider.id for provider in _PROVIDERS)
_PROVIDERS_BY_ID = {provider.id: provider for provider in _PROVIDERS}


def recognition_providers() -> tuple[RecognitionProvider, ...]:
    return _PROVIDERS


def recognition_provider(provider_id: str) -> RecognitionProvider:
    try:
        return _PROVIDERS_BY_ID[provider_id]
    except KeyError as error:
        raise ValueError(tr(
            "Unsupported recognition service",
            "不支持的语音识别服务",
        )) from error
