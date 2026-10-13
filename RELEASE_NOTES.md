# Doubao Say 1.7.0

## Personal speech evaluation

Mac and Linux now provide an in-app speech evaluation page. Record locally, review what you actually said, then compare the same recording with raw official ASR, personal hotwords and optional polishing. Review character errors, target terms, protected-term loss, failed samples and replay timings. Starting comparison explicitly uploads recordings to your configured paid official ASR. Reference text is only used for scoring and never becomes vocabulary or enters recognition requests. Drafts save automatically; recordings remain until deleted.

## Selected corrections and input timings

Select a wrong term to fill the correction form, review the exact occurrence replacement and confirm before it becomes memory. Original recognition and polishing output remain available. Future polishing uses confirmed corrections as contextual references. Input history shows recognition, remaining polishing, delivery and total waiting time after recording stops. Mac computes evaluation statistics in the background and reads timings in batches.

## Input reliability

API-key drafts survive saves and provider changes across onboarding and settings. Polishing requests support cancellation during connection, TLS and response reads, reject redirects and incomplete output, and free the final request worker after timeout. Recording, retry delivery, microphone checks, evaluation and updates are coordinated. Mac synthetic paste shortcuts carry an event marker to prevent feedback into voice triggers.

## Downloads and verification

Developer ID signed, Apple-notarized Mac DMGs are available for Apple Silicon and Intel. Linux app/plugin archives support Python 3.11–3.14. Settings, login data, vocabulary and history are retained. SHA256SUMS covers all packages; update.json is the public update source.

Automated verification uses synthetic credentials, recordings and loopback network services. It covers protocol framing, selected corrections, scoring, credential persistence, cancellation, input state transitions and native interfaces. Actual personal-accent accuracy, competitor parity, physical microphones, cross-application input and Intel hardware behavior have not been established by these checks.

[Full changes](https://github.com/quanru/doubao-say/compare/v1.6.0...v1.7.0)
