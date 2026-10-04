# Banjo Voice

Status: implementation started on the `voice` branch, October 4, 2026.

Banjo Voice is an audio interface to the existing authenticated player-guidance
system. Voice does **not** become a second source of game truth. Inventory,
machines, goals, build readiness, materials, energy, and next actions continue
to come from Banjo's server-side observations.

## Product experience

The intended interaction has three layers:

1. **Voice lens** — after a deliberate stable look at an object, material,
   machine, or terrain target, Banjo can briefly identify it and say the useful
   action or blocker. This will reuse the existing 1.5 s target dwell and the
   material preview model; it should not call an LLM just to discover facts the
   game already knows.
2. **Explain this** — the existing authenticated `Ask AI · F1` explanation can
   be spoken. The exact `next_action`, blockers, selected project, and build
   readiness stay authoritative.
3. **Push to talk** — hold V or a microphone button and ask natural questions:
   “What should I do?”, “Why isn't this working?”, or “What is this?” The
   current looked-at/held object is supplied as focus.

Later, the same audio plumbing can support conversations with AI characters and
rovers, but those remain distinct audiences with their existing permissions and
state.

## The important memory rule

Voice has two kinds of memory:

- **Live Realtime session memory.** OpenAI Realtime sessions are stateful while
  connected, so audio turns have a coherent live session.
- **Banjo per-player voice memory.** Banjo persists a small bounded transcript
  of the player's voice questions and Banjo's answers. It is scoped by
  `world_id + player_id`, survives a browser reconnect/server restart, and is
  supplied as recent conversation to the existing game guide. This is what
  prevents “What now?” / “Why?” exchanges from starting from scratch after a
  reconnect.

Only transcript text and Banjo's reply are stored. Raw microphone audio is not
stored by Banjo.

Fresh authenticated game observations always override remembered conversation.
Memory is context for continuity and avoiding repetition, never evidence that an
old machine state, balance, inventory quantity, or blocker is still true.

The first implementation also deduplicates an exact retried question when the
last stored exchange already has an answer, avoiding an unnecessary model call.

## First implementation architecture

The first slice intentionally separates **audio transport** from **game
reasoning**:

```
microphone
   |
   v
OpenAI Realtime over WebRTC
   |  input transcription
   v
Banjo /api/world/voice/ask
   |
   +--> fresh authenticated game_guidance.snapshot(...)
   +--> bounded per-player recent voice history
   +--> existing game_guidance.answer(...)
   |
   v
authoritative text reply
   |
   v
OpenAI Realtime speaks that exact Banjo reply
```

This gives us natural low-latency microphone/audio handling without allowing the
Realtime model to improvise game state. The existing guide remains read-only and
has no action tools.

The browser receives only a short-lived Realtime client secret. Banjo's normal
OpenAI API key never goes to JavaScript. The server sets a pseudonymous
`OpenAI-Safety-Identifier` when creating the client secret.

## Realtime configuration

Initial defaults:

- Realtime model: `gpt-realtime-2.1-mini`
- Voice: `marin`
- Input transcription: `gpt-live-transcribe`
- Turn detection: disabled; Banjo uses explicit push-to-talk commit
- Connection: browser WebRTC
- Audio answers: out-of-band Realtime responses so spoken UI/help does not
  accidentally become game-state conversation history

Environment overrides:

- `BANJO_VOICE_MODEL`
- `BANJO_VOICE_NAME`

Current OpenAI references:

- https://developers.openai.com/api/docs/guides/realtime-webrtc
- https://developers.openai.com/api/docs/guides/realtime-conversations
- https://developers.openai.com/api/docs/guides/realtime-transcription
- https://developers.openai.com/api/docs/guides/voice-agents

## Security and trust boundaries

- A named world and authenticated Banjo player are required.
- Standard API key remains server-side.
- Ephemeral Realtime client secrets are short-lived and returned only to the
  authenticated player that requested them.
- The Realtime model gets no Banjo mutation tools in this phase.
- Voice questions are answered from a fresh server snapshot, not client-supplied
  balances or machine facts.
- Remembered transcript is untrusted conversation data, not instructions.
- Voice memory is private to one player in one world and bounded.
- No raw audio persistence.
- Watching another character remains read-only.

## Ordered implementation

### Phase 1 — push-to-talk foundation

- [x] Create `voice` branch and this design boundary.
- [ ] Add private durable voice-memory module.
- [ ] Add server endpoint to mint Realtime client secrets.
- [ ] Add `/api/world/voice/ask` backed by `game_guidance`.
- [ ] Add browser `voice.js` WebRTC/push-to-talk controller.
- [ ] Add hold-V and microphone-button UI.
- [ ] Show voice transcript/reply in the existing AI Guide chat.
- [ ] Add focused-object context.
- [ ] Unit-test memory isolation, boundedness, session config, and answer routing.

### Phase 2 — spoken authenticated guidance

- Speak an explicit `Ask AI · F1` result on request.
- Add a speaker control next to short guide explanations.
- Interrupt speech immediately if the player begins another push-to-talk turn.
- Keep narration responses out of the conversational memory unless they add
  information the player explicitly asked for.

### Phase 3 — voice lens

- Reuse `makeTargetHover(1500)`.
- Speak only stable, useful changes: first identification, changed blocker,
  newly available action, machine completion, or meaningful failure.
- Key dedupe by target identity + relevant revision/state, not by frame.
- Never narrate the same unchanged target repeatedly just because the player
  glances away and back.
- Prefer deterministic text built from the existing target model; invoke AI only
  for “why/how” explanation.

### Phase 4 — world actions and characters

- Spoken conversations with AI characters and rovers use their existing
  authenticated audiences.
- Any future voice-triggered mutation uses the same existing bounded action
  APIs and explicit receipts as typed controls. Voice never gets a bypass.

## Acceptance criteria for Phase 1

1. Player can press and hold V (or the mic button), speak, release, and receive
   a spoken AI Guide answer.
2. The transcript and answer appear in the normal Guide conversation.
3. “What is this?” resolves the same currently focused body as typed Guide help.
4. Two different players in the same world do not share voice memory.
5. The same player retains recent voice context after reconnect/restart.
6. Repeating the exact last acknowledged question can reuse the stored answer
   rather than issuing another paid reasoning call.
7. A fresh game snapshot is taken for every new question; old memory never
   substitutes for current game state.
8. Standard OpenAI API credentials never appear in browser responses or logs.
9. Voice remains usable if the proactive guide is disabled.
10. Failure to start voice does not break ordinary keyboard/mouse/chat play.

## Non-goals of the first slice

- Always-listening microphone.
- Wake-word detection.
- Autonomous AI actions from speech.
- LLM-generated hover facts.
- Raw audio recording or replay.
- Cross-world/player memory.
- Replacing the existing text chat or F1 guide.
- Claiming any new physics, material, or gameplay capability.
