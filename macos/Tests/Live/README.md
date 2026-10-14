# Opt-in native ChatGPT connection check

Build `bash macos/Tests/Live/build-chatgpt.sh` under a heavy resource slot.
After compilation exits, run the prebuilt helper under a runtime slot:

```sh
python3 macos/Tests/Live/chatgpt_check.py build/macos/tests/chatgpt-live-check \
  artifacts/verification/siwc/mac-live --sign-in --request
```

The helper creates a unique ad-hoc signed bundle and app-owned Keychain item.
The output directory retains its bundle identifier so a later invocation without
`--sign-in` checks actual restart restoration and expiry renewal. Never use a
production bundle identifier or copy another application's credentials.
Use the exact same probe binary and signer for later invocations. The runner
refuses to replace them in an existing profile: rebuilding an ad-hoc signed app
changes its Keychain identity and can prompt for user authentication. Set
`DOUBAO_SIWC_CODESIGN_IDENTITY` to the app's Developer ID signing identity when
verifying the distribution signing configuration; it does not publish a build.
The original executable remains in the output bundle. Pass
`PRIVATE_OUTPUT/NativeSIWCCheck.app/Contents/MacOS/NativeSIWCCheck` as the binary
for later expiry checks when the repository's build output has been rebuilt.

During sign-in, `browser.json` is an owner-only browser handoff file. Open its
URL in the verification browser session without logging the URL or callback
query. It can contain identity hints on a later sign-in. A pending authorization
expires after five minutes; the runner terminates its own process after six.
Do not publish this file, Keychain data, or screenshots with personal account
details. `result.json` contains only safe status, counts and request timing.

`--request` sends synthetic text (`hello world`) through the actual shared
`PolishClient`, fixed Responses endpoint and five-second deadline without an API
key. The real server may reject a request for plan or application usage limits;
record that result separately from successful sign-in and model access. This
check does not record audio, install an app, inject input or release a build.
`--comparison` uses the existing 25-second comparison/vocabulary deadline instead
of the five-second dictation deadline. Record which mode was used; a completed
comparison request does not prove five-second dictation success.
