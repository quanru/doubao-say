# Doubao and the official Volcengine speech API

Doubao Say supports two cloud recognition backends. Neither is an offline local model: microphone audio is sent to the selected provider while recording.

| Backend | Requirements | Trade-off |
| --- | --- | --- |
| Doubao web sign-in (default) | A Doubao account and saved web session | No separate Volcengine API purchase, but it relies on an unofficial web protocol that can change |
| Official Volcengine API | A Volcengine account, Streaming Speech Recognition 2.0 activation, and an API key | Official authentication, live partial text, and separately metered usage |

Final text is pasted into the target application only after recording ends. “Live” means that the Doubao Say overlay displays incremental recognition while you speak.

## Doubao web sign-in

Keep **Doubao account** selected on the Recognition step, complete sign-in in the web window, then run the microphone and voice tests. This mode doesn't require a Volcengine console account or API key. Credentials are stored locally, but availability can be affected by changes to the Doubao website.

## Enable Volcengine bidirectional streaming ASR 2.0

These instructions apply to the **new Doubao Speech console**. Do not enter the App ID and Access Token described by legacy-console documentation.

1. Sign in to the [Volcengine console](https://console.volcengine.com/) and complete any required account verification.
2. Open the [new Doubao Speech activation page](https://console.volcengine.com/speech/new/setting/activate).
3. Select a project, such as `default`. Service activation and the API key must belong to the same project; resources are isolated between projects.
4. Under **Activation management**, find **Streaming Speech Recognition 2.0** in the large-model section.
5. Activate the service and accept any billing agreement shown by the console. The console displays remaining trial or purchased audio-processing time; limits and prices depend on the account.
6. Open **API Key** in the same project and create or copy a key. Treat it as a long-lived secret.

Volcengine describes bidirectional streaming as returning text while speech is still being received. The mode used by Doubao Say primarily supports Chinese and English; don't assume other languages or the broader non-bidirectional dialect coverage is available.

Official references:

- [Streaming ASR product description](https://www.volcengine.com/docs/6561/1354871?lang=zh)
- [Bidirectional streaming ASR WebSocket](https://docs.volcengine.com/docs/6561/2630027?lang=zh)

## Configure Doubao Say

1. Open **Settings → Recognition service**.
2. Select **Volcengine official API**.
3. Paste the API key. It saves automatically.
4. Select **Test API key**. A successful test verifies authentication and entitlement without uploading a recording.
5. Run the real voice test. Incremental text should appear in the overlay before recording finishes.

Doubao Say supplies these values internally; users don't need to configure them:

```text
WebSocket:    wss://openspeech.bytedance.com/api/v3/sauc/bigmodel
Resource ID: volc.seedasr.sauc.duration
Auth header: X-Api-Key
Audio:       16 kHz / 16-bit / mono PCM
```

The key is stored at `~/.config/doubao-say/volcengine_api_key` with owner-only permissions. Switching back to Doubao web sign-in keeps the key; **Clear API key** removes it.

## Troubleshooting

- **HTTP 401:** verify that the key comes from the new console, its project matches the activated service, and Streaming Speech Recognition 2.0 is active. Newly created access may take a short time to propagate.
- **Key test passes but no transcript appears:** verify the selected microphone with the local three-second microphone test, then run the real voice test.
- **Text appears only after release:** use a current build whose endpoint ends in `bigmodel`, not `bigmodel_nostream`.
- **Unexpected charges or quota errors:** inspect Usage statistics and the billing center in the Volcengine console. Doubao Say never purchases quota or adds funds for you.

Never publish an API key, configuration directory, VM disk, or full logs containing private transcripts. A timestamp, HTTP status, and Volcengine Log ID are normally sufficient for support.
