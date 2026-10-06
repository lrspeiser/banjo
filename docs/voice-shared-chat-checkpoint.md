# Voice through the selected chat

October 5, 2026. Host/UI implementation, synthetic regression and one live
Windows provider check. Verification base: published main
`1572c27514ef06814c119c3d042344af58e6c192`, plus this checkpoint.
The typed Build/shared-chat checkpoint is on main and installed in `C:/play`.
Only the applicable transport, private-memory and test foundations were taken
from `origin/voice` at `37f206faf83d9bd46545c1fb76a9e562e774a953`;
that branch's unrelated native changes, lens and F1 narration were not merged.

## Implemented behavior

A visible microphone in World and the combined hubs supports press/hold/release
with mouse, touch and Y outside editable controls. Transcripts enter the same
form as typed text: current Guide/audience in World, selected source/component
in Lab, or game help without a draft. The resulting chat text remains visible.
There is no alternate action authority or direct Realtime game mutation.
Guide source selection and Lab changes remain reversible; manufacturing,
equipping, placement and rover execution keep their existing paid/permission
boundaries and native guards.

Menu → Audio is Off by default and persists in local browser storage. Turning
it On permits spoken successful chat replies; turning it Off mutes and cancels
pending output. Muted chats make no synthesis request. The setting alone does
not connect or capture input. Press/hold always governs the microphone.
Tracks stop on release, cancellation, disconnect and page teardown. Touch
cancellation, capture loss, hidden page and blur discard an uncommitted turn.
Release before the connection or permission result arrives cannot start late
capture. Failures leave typing usable and require a deliberate retry.
Idle sessions close after 30 seconds; no polling narration or automatic
reconnect is installed.

Authenticated session creation accepts no client configuration. Standard API
credentials remain server-side; the browser receives a client secret configured
to expire after 60 seconds. The server uses a pseudonymous safety identifier.
The page's restrictive policy explicitly permits the OpenAI API connection and
local media blobs while retaining exact inline hashes. Realtime transports
input transcription and supplied reply audio, with automatic turn detection
disabled. Defaults: `gpt-realtime-2.1-mini`, `marin`,
`gpt-live-transcribe`. Reply synthesis requests an exact reading of the
authoritative text and no additional advice.

Guide text exchanges also populate bounded private durable history (20 message
rows per player/world; at most 10 supplied as recent context). A request without
browser history receives that context. A fresh authenticated state snapshot is
still required for every answer, including repeated words. Lab and
rover/character routes retain their existing typed continuity. Raw microphone
audio is not persisted by Banjo.

## Measured evidence

Windows 11 Pro, Python 3.13, Chrome, Node.js. Native fixture bundle:
`C:/play/bin`; runner SHA-256
`d547855a13889b13292952c928f64e0839a1304c3f216d6337506eeaa9b2e7a0`;
platform CLI SHA-256
`5a49e7f5d771756573acd034bc0f6cb61a06e7f9312fa02da0a6b8d1fb8c8817`.
Native binaries and material laws are unchanged.

CMake-registered voice client/controller checks cover default mute, setting
without calls, supplied reply output, failed output cancellation, actual typed
submission, duplicate item IDs, repeated words in new turns, mouse/Y/touch
cancel boundaries, late microphone permission, errors and deliberate reconnect.
Four Python contract tests cover private durable/restart history, bounded
inputs, fresh snapshots and server-key/client-secret separation. Two native
HTTP/browser checks cover policy/authentication/shared Guide history, a spoken
supported source selection, reversible candidate edit without a paid job,
844 × 390 touch rover stop, output On/Off and reload, failed session recovery,
and zero browser runtime exceptions. The source-selection provider and WebRTC
transport are mocked in these repeatable browser tests.

The separate live provider experiment uses a local synthetic Windows speech
recording, 48 kHz mono 16-bit PCM, through Chrome's fake audio capture.
It never opens an ambient microphone or uses the owner's retained world.
OpenAI transcribed “Stop.”; the selected rover requested native `waiting`.
The visible reply and output transcript both read
“Stopping. I will hold here until you say.”

| Live observation | One measured turn |
| --- | ---: |
| Press to ready/listening | 3.140 s |
| Release to authoritative chat reply | 3.540 s |
| Reply to response completion / progressing audio check | 1.007 s |
| Remote audio element time at check | 8.112 s |
| Browser runtime exceptions | 0 |

Chrome's test launch mutes the device output; the remote stream and audio
element progress with the element itself unmuted. This is transport/playback
evidence, not a human listening test. Connection time includes session minting
and WebRTC establishment. These are individual observations, not p95 or a
latency guarantee. Desktop 1440 × 900 and landscape 844 × 390 captures show the
reachable microphone and chat. Real phone permission/capture/speaker behavior,
noise handling, accessibility and human audio acceptance remain open.

The three typed Build/shared-chat checks and 38 Workshop chat/CSP checks also
pass after voice integration. Source registration remains 302/302 with no
intentional exclusions. The pre-existing game-guidance processing priority
failure (`order-rover` where `process-input` is expected) remains documented
in the [typed checkpoint](build-lab-chat-checkpoint.md); this is not an
all-main-tests-green claim. No new material realism, conservation,
cross-platform physics or construction completeness is established.

## Next gates

Complete human desktop and physical phone audio/permission acceptance, measure
several fresh and warm provider turns, and retain cancellation/privacy checks.
Resolve the pre-existing processing guidance priority independently. Broader
construction and native matter qualification remain governed by the roadmap.

API configuration was checked against the current official
[WebRTC voice guide](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=realtime),
[manual Realtime turn guide](https://developers.openai.com/api/docs/guides/realtime-conversations)
and [transcription model reference](https://developers.openai.com/api/docs/models/gpt-live-transcribe).
