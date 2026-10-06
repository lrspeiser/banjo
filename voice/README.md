# Banjo voice

October 5, 2026: shared typed-chat integration and a Windows live-provider
checkpoint. See [verification and remaining bounds](../docs/voice-shared-chat-checkpoint.md).
The original voice branch is a source reference; its hover lens and F1 narration
are not part of this interface.

Hold the visible microphone button, or hold Y outside a text field, to talk.
Release to submit the transcript to the selected chat. World uses the selected
Guide, rover, character, Players or AI Actions audience. Build uses the current
source and component selection; without a draft it uses game help. Source
selection, draft edits and native commands follow the same handlers as typing.
Existing permissions, paid-work reviews and native guards still apply.

Menu → Audio starts Off and persists in this browser. Text replies remain
visible. On speaks successful chat replies; changing the setting alone creates
no provider request. Microphone input is deliberate press/hold in either output
mode. A canceled touch, lost capture, hidden page or window blur discards the
held turn. Tracks stop on release, cancellation and disconnect. A quick release
before connection completes does not request a microphone. Hold again after an
error to retry; there are no automatic reconnect calls.

## Transport and current state

The authenticated server mints a client secret with a 60-second creation
expiry. The standard API key remains on the server. The browser exchanges SDP
with OpenAI over WebRTC, using the client secret. Voice requires a supported
secure browser context (HTTPS or local loopback), named world and own character.

Input transcription enters the existing form submission, then the authoritative
text reply can be supplied as an out-of-band audio response. Realtime has no
Banjo action tools. Source catalogs and game facts come from fresh authenticated
observations. A supplied voice transcript cannot supply wallet, inventory,
solver or ownership state.

Defaults are `gpt-realtime-2.1-mini`, voice `marin`, input transcription
`gpt-live-transcribe`, and disabled automatic turn detection.
`BANJO_VOICE_MODEL` and `BANJO_VOICE_NAME` are server configuration overrides.
The page policy allows the OpenAI API connection and local media blobs while
retaining exact inline script/style hashes.

Guide exchanges use bounded private durable text history scoped by world and
player. If the current typed request has no recent history, the server supplies
that history; every answer still takes a fresh snapshot. Existing browser Guide
history, Lab draft history and rover/character continuity retain their own
typed-chat behavior. Banjo does not store raw microphone audio.
The retained `/api/world/voice/ask` compatibility route is read-only Guide help;
the shared UI does not use it. The memory endpoint supports private status and
clear, without returning transcripts.

## Verified boundary

CI uses synthetic transport and isolated native worlds. A separate live OpenAI
test used a locally generated synthetic “Stop” recording and Chrome fake audio
capture, never the owner's ambient microphone or retained world. Its transcript
reached the selected native rover, and the returned audio transcript matched
the visible reply. Browser audio progressed with output enabled.

This verifies one live turn, not a latency distribution, real phone hardware,
audible speaker quality or noisy-microphone recognition. Physical phone and
human audio acceptance remain open. There is no new physics validation here.

Current API references:

- [WebRTC voice transport](https://developers.openai.com/api/docs/guides/voice-webrtc?voice-api=realtime)
- [Manual Realtime turns](https://developers.openai.com/api/docs/guides/realtime-conversations)
- [Input transcription model](https://developers.openai.com/api/docs/models/gpt-live-transcribe)
