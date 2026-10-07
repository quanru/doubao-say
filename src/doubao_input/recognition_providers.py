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
    def save(cls, credentials) -> None: ...

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
    secret_credentials_factory: Callable[[str], object] | None
    setup_heading_en: str
    setup_heading_zh: str
    setup_body_en: str
    setup_body_zh: str
    credential_help_en: str
    credential_help_zh: str
    privacy_en: str
    privacy_zh: str
    failure_en: str
    failure_zh: str

    @property
    def name(self) -> str:
        return tr(self.name_en, self.name_zh)

    def new_client(self):
        return self.client_factory()

    @property
    def credential_store(self) -> type[CredentialStore]:
        return self.credential_store_factory()

    @property
    def uses_api_key(self) -> bool:
        return self.secret_credentials_factory is not None

    @property
    def setup_heading(self) -> str:
        return tr(self.setup_heading_en, self.setup_heading_zh)

    @property
    def setup_body(self) -> str:
        return tr(self.setup_body_en, self.setup_body_zh)

    @property
    def credential_help(self) -> str:
        return tr(self.credential_help_en, self.credential_help_zh)

    @property
    def privacy(self) -> str:
        return tr(self.privacy_en, self.privacy_zh)

    @property
    def failure_message(self) -> str:
        return tr(self.failure_en, self.failure_zh)

    @property
    def is_local(self) -> bool:
        return not self.interactive_auth and not self.uses_api_key

    def credentials_from_secret(self, secret: str):
        if self.secret_credentials_factory is None:
            raise ValueError("Recognition provider does not use an API key")
        return self.secret_credentials_factory(secret)


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


def _volcengine_credentials(secret):
    from doubao_input.doubao.volcengine_credentials import VolcengineCredentials
    return VolcengineCredentials(secret)


def _deepgram_client():
    from doubao_input.deepgram.asr_client import DeepgramASRClient
    return DeepgramASRClient()


def _deepgram_store():
    from doubao_input.deepgram.credentials import DeepgramCredentialsStore
    return DeepgramCredentialsStore


def _deepgram_credentials(secret):
    from doubao_input.deepgram.credentials import DeepgramCredentials
    return DeepgramCredentials(secret)


def _voxtype_client():
    from doubao_input.voxtype.asr_client import VoxtypeASRClient
    return VoxtypeASRClient()


def _voxtype_store():
    from doubao_input.voxtype.runtime import VoxtypeRuntimeStore
    return VoxtypeRuntimeStore


_PROVIDERS = (
    RecognitionProvider(
        id="doubao",
        name_en="Doubao account",
        name_zh="豆包账号",
        client_factory=_doubao_client,
        credential_store_factory=_doubao_store,
        interactive_auth=True,
        clear_rejected_credentials=True,
        secret_credentials_factory=None,
        setup_heading_en="Your voice, wherever you type.",
        setup_heading_zh="让声音变成文字。",
        setup_body_en="Connect your Doubao account in a secure web window. Complete the sign-in method offered by Doubao, then return here. We never ask you to type a password into this app's settings.\n\nAudio is sent to Doubao only during recording. Sign-in data is stored on this device. This is an unofficial client.",
        setup_body_zh="在网页窗口中连接豆包账号。按照豆包页面提供的方式完成登录，再回到这里；无需在本软件设置中填写密码。\n\n仅录音期间会向豆包发送音频。登录信息保存在本机。这是非官方客户端。",
        credential_help_en="",
        credential_help_zh="",
        privacy_en="Doubao receives audio during dictation and voice tests. Microphone checks stay local. No recording files or transcript history are saved. Recent text stays in memory until cleared or the app exits.",
        privacy_zh="听写和语音测试会向豆包发送音频，麦克风检查仅在本机进行。不保存录音文件和转写历史，最近文字仅在内存保留，清除或退出后消失。",
        failure_en="Connection failed; check your network and retry",
        failure_zh="连接出错，请检查网络后重试",
    ),
    RecognitionProvider(
        id="volcengine",
        name_en="Volcengine official API",
        name_zh="火山引擎官方 API",
        client_factory=_volcengine_client,
        credential_store_factory=_volcengine_store,
        interactive_auth=False,
        clear_rejected_credentials=False,
        secret_credentials_factory=_volcengine_credentials,
        setup_heading_en="Use the official Volcengine speech API.",
        setup_heading_zh="使用火山引擎官方语音 API。",
        setup_body_en="Add your API key in Settings. Audio is sent to Volcengine only while recording; usage is billed by Volcengine to your account. The key is stored separately on this device with owner-only permissions.",
        setup_body_zh="请在设置中填写 API Key。仅录音期间会向火山引擎发送音频，用量由火山引擎向你的账号计费。API Key 单独保存在本机，且仅当前用户可读。",
        credential_help_en="The new Doubao Speech console uses one API Key. Resource ID volc.seedasr.sauc.duration is built in. App ID and Access Key are only for the legacy console and are not required here.",
        credential_help_zh="新版豆包语音控制台只使用一个 API Key；资源 ID volc.seedasr.sauc.duration 已内置。App ID 和 Access Key 仅用于旧版控制台，这里不需要填写。",
        privacy_en="Volcengine receives audio during dictation and voice tests. Usage and data handling follow your Volcengine account and service terms. Microphone checks stay local. No recording files or transcript history are saved; recent text stays in memory until cleared or the app exits.",
        privacy_zh="听写和试说时会向火山引擎发送音频，用量和数据处理遵循你的火山引擎账号及服务条款。麦克风检查仅在本机进行。不保存录音文件和转写历史；最近文字仅在内存保留，清除或退出后消失。",
        failure_en="Connection failed; check your network and retry",
        failure_zh="连接出错，请检查网络后重试",
    ),
    RecognitionProvider(
        id="deepgram",
        name_en="Deepgram Nova-3 (English)",
        name_zh="Deepgram Nova-3（英语）",
        client_factory=_deepgram_client,
        credential_store_factory=_deepgram_store,
        interactive_auth=False,
        clear_rejected_credentials=False,
        secret_credentials_factory=_deepgram_credentials,
        setup_heading_en="Use Deepgram Nova-3 for English dictation.",
        setup_heading_zh="使用 Deepgram Nova-3 进行英语听写。",
        setup_body_en="Add a Deepgram API key in Settings. Audio is streamed to Deepgram only while recording. Usage is billed to your Deepgram account, and the key is stored separately on this device with owner-only permissions.",
        setup_body_zh="请在设置中填写 Deepgram API Key。仅录音期间会向 Deepgram 流式发送音频，用量由 Deepgram 向你的账号计费。API Key 单独保存在本机，且仅当前用户可读。",
        credential_help_en="Uses Deepgram Nova-3 with US English, interim results, punctuation, and smart formatting. Create and manage the API key in the Deepgram console.",
        credential_help_zh="使用 Deepgram Nova-3 美式英语模型，并启用中间结果、标点和智能格式化。请在 Deepgram 控制台创建和管理 API Key。",
        privacy_en="Deepgram receives audio during dictation and voice tests. Usage and data handling follow your Deepgram account and service terms. Microphone checks stay local. No recording files or transcript history are saved; recent text stays in memory until cleared or the app exits.",
        privacy_zh="听写和试说时会向 Deepgram 发送音频，用量和数据处理遵循你的 Deepgram 账号及服务条款。麦克风检查仅在本机进行。不保存录音文件和转写历史；最近文字仅在内存保留，清除或退出后消失。",
        failure_en="Connection failed; check your network and retry",
        failure_zh="连接出错，请检查网络后重试",
    ),
    RecognitionProvider(
        id="voxtype",
        name_en="Voxtype (local)",
        name_zh="Voxtype（本地）",
        client_factory=_voxtype_client,
        credential_store_factory=_voxtype_store,
        interactive_auth=False,
        clear_rejected_credentials=False,
        secret_credentials_factory=None,
        setup_heading_en="Use your local Voxtype daemon.",
        setup_heading_zh="使用本机 Voxtype 服务。",
        setup_body_en="Voxtype records and transcribes locally with its configured engine and model. Install Voxtype 1.0.0 or newer, complete `voxtype setup --download`, and keep its daemon running. Doubao Say requests file output and reads the finalized transcript; it does not change your Voxtype configuration.",
        setup_body_zh="Voxtype 会用已配置的引擎和模型在本机录音、转写。请安装 Voxtype 1.0.0 或更高版本，完成 `voxtype setup --download`，并保持 daemon 运行。豆包说只请求文件输出并读取最终文字，不会修改你的 Voxtype 配置。",
        credential_help_en="Requires a running Voxtype 1.0.0+ daemon and an installed model. Settings shows the active engine and model. Choosing a model updates Voxtype's configuration and restarts its daemon.",
        credential_help_zh="需要运行中的 Voxtype 1.0.0+ daemon 和已安装模型。设置页显示当前引擎、模型；选择模型会更新 Voxtype 配置并重启 daemon。",
        privacy_en="Voxtype owns microphone capture for this provider. Local engines keep audio on this device; cloud engines configured inside Voxtype follow their own service terms. Doubao Say reads a private transcript file and deletes it and its completion record after each session.",
        privacy_zh="使用该服务时，麦克风由 Voxtype 采集。本地引擎不会把音频发出设备；若你在 Voxtype 中配置了云端引擎，则适用对应服务条款。豆包说会读取一份私有转写文件，并在每次结束后删除该文件及完成记录。",
        failure_en="Voxtype failed; check that its daemon is running, idle, and configured with a model",
        failure_zh="Voxtype 运行失败，请确认 daemon 正在运行、处于空闲状态且已配置模型",
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
