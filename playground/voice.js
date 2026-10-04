const REALTIME_CALLS = "https://api.openai.com/v1/realtime/calls";

function editableTarget(target) {
  return !!target?.closest?.("input, textarea, select, [contenteditable='true']");
}

function waitForChannel(channel, timeoutMs = 10000) {
  if (channel.readyState === "open") return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("Voice connection did not open"));
    }, timeoutMs);
    const cleanup = () => {
      clearTimeout(timer);
      channel.removeEventListener("open", opened);
      channel.removeEventListener("close", closed);
      channel.removeEventListener("error", failed);
    };
    const opened = () => { cleanup(); resolve(); };
    const closed = () => { cleanup(); reject(new Error("Voice connection closed")); };
    const failed = () => { cleanup(); reject(new Error("Voice connection failed")); };
    channel.addEventListener("open", opened);
    channel.addEventListener("close", closed);
    channel.addEventListener("error", failed);
  });
}

export function createVoiceController({
  api,
  mount,
  canTalk = () => true,
  getFocus = () => null,
  onUser = () => {},
  onReply = () => {},
  onStatus = () => {},
} = {}) {
  if (typeof api !== "function") throw new Error("Banjo voice requires the game API");
  const form = mount || document.querySelector("#ask");
  if (!form) throw new Error("Banjo voice needs the chat form");

  const button = document.createElement("button");
  button.type = "button";
  button.id = "voice-talk";
  button.textContent = "Hold V";
  button.title = "Hold V, or press and hold this button, to talk to AI Guide";
  button.setAttribute("aria-label", button.title);

  const status = document.createElement("small");
  status.id = "voice-status";
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  status.hidden = true;

  const send = form.querySelector("#ask-send");
  form.insertBefore(button, send || null);
  form.insertAdjacentElement("afterend", status);

  let peer = null;
  let channel = null;
  let media = null;
  let mic = null;
  let remoteAudio = null;
  let connecting = null;
  let holding = false;
  let asking = false;
  let speaking = false;
  let activePointer = null;
  let speechCounter = 0;
  let activeSpeech = null;
  let closed = false;

  function setStatus(state, text = "") {
    button.dataset.voiceState = state;
    button.setAttribute("aria-pressed", state === "listening" ? "true" : "false");
    button.textContent = state === "listening" ? "Release" :
      state === "thinking" ? "Thinking…" :
      state === "speaking" ? "Speaking…" :
      state === "connecting" ? "Voice…" : "Hold V";
    status.textContent = text;
    status.hidden = !text;
    onStatus({ state, text });
  }

  function emit(event) {
    if (!channel || channel.readyState !== "open")
      throw new Error("Voice connection is not ready");
    channel.send(JSON.stringify(event));
  }

  function stopRemoteSpeech() {
    if (!speaking || !channel || channel.readyState !== "open") return;
    // With WebRTC audio and the data channel travelling separately, both the
    // server response and already-buffered playback have to be stopped.
    emit({ type: "response.cancel" });
    emit({ type: "output_audio_buffer.clear" });
    speaking = false;
    activeSpeech = null;
  }

  function cleanupConnection() {
    try { if (mic) mic.enabled = false; } catch {}
    for (const track of media?.getTracks?.() || []) {
      try { track.stop(); } catch {}
    }
    try { channel?.close(); } catch {}
    try { peer?.close(); } catch {}
    try { if (remoteAudio) remoteAudio.srcObject = null; } catch {}
    media = null;
    mic = null;
    channel = null;
    peer = null;
    remoteAudio?.remove();
    remoteAudio = null;
    connecting = null;
    speaking = false;
    activeSpeech = null;
  }

  async function handleTranscript(event) {
    const transcript = String(event.transcript || "").trim();
    if (!transcript || asking || closed) {
      if (!asking) setStatus("idle");
      return;
    }
    asking = true;
    onUser(transcript);
    setStatus("thinking", "AI Guide is checking the current game state.");
    try {
      const focus = getFocus();
      const answer = await api("/api/world/voice/ask", {
        message: transcript,
        ...(focus ? { focus } : {}),
        screen: "world",
      });
      const reply = String(answer.reply || "").trim();
      if (!reply) throw new Error("AI Guide returned no answer");
      onReply(reply, answer);
      asking = false;
      await speak(reply);
    } catch (error) {
      asking = false;
      setStatus("error", error.message || String(error));
    }
  }

  function handleEvent(message) {
    let event;
    try { event = JSON.parse(message.data); }
    catch { return; }
    if (event.type === "conversation.item.input_audio_transcription.completed") {
      handleTranscript(event);
      return;
    }
    if (event.type === "response.done") {
      const id = event.response?.metadata?.banjo_speech;
      if (id && id === activeSpeech) {
        speaking = false;
        activeSpeech = null;
        setStatus("idle");
      }
      return;
    }
    if (event.type === "error") {
      const detail = event.error?.message || "Voice service error";
      setStatus("error", detail);
    }
  }

  async function connect() {
    if (closed) throw new Error("Voice is closed");
    if (channel?.readyState === "open") return;
    if (connecting) return connecting;
    if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection)
      throw new Error("This browser does not support microphone voice");
    if (!canTalk()) throw new Error("Open your character's world before using voice");
    // A dead prior peer must not keep its microphone/track around when the
    // player reconnects after Wi-Fi or server recovery.
    if (peer || channel || media) cleanupConnection();

    connecting = (async () => {
      setStatus("connecting", "Connecting voice…");
      const secret = await api("/api/world/voice/session", {});
      if (!secret?.value) throw new Error("Banjo did not receive a voice client secret");

      media = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mic = media.getAudioTracks()[0];
      if (!mic) throw new Error("No microphone is available");
      mic.enabled = false;

      peer = new RTCPeerConnection();
      remoteAudio = document.createElement("audio");
      remoteAudio.autoplay = true;
      remoteAudio.hidden = true;
      document.body.append(remoteAudio);
      peer.ontrack = (event) => {
        remoteAudio.srcObject = event.streams[0] || new MediaStream([event.track]);
        remoteAudio.play?.().catch(() => {});
      };
      peer.addTrack(mic, media);

      channel = peer.createDataChannel("oai-events");
      channel.addEventListener("message", handleEvent);
      channel.addEventListener("close", () => {
        if (!closed) setStatus("error", "Voice disconnected. Hold V to reconnect.");
      });

      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      const response = await fetch(REALTIME_CALLS, {
        method: "POST",
        body: offer.sdp,
        headers: {
          "Authorization": "Bearer " + secret.value,
          "Content-Type": "application/sdp",
        },
      });
      if (!response.ok)
        throw new Error(`Voice connection failed (HTTP ${response.status})`);
      const answer = await response.text();
      await peer.setRemoteDescription({ type: "answer", sdp: answer });
      await waitForChannel(channel);
      setStatus("idle");
    })().catch((error) => {
      cleanupConnection();
      setStatus("error", error.message || String(error));
      throw error;
    }).finally(() => {
      connecting = null;
    });
    return connecting;
  }

  async function start() {
    if (holding || asking || closed) return;
    holding = true;
    try {
      await connect();
      if (!holding || closed) return;
      stopRemoteSpeech();
      emit({ type: "input_audio_buffer.clear" });
      mic.enabled = true;
      setStatus("listening", "Listening… release to ask AI Guide.");
    } catch {
      holding = false;
    }
  }

  function stop() {
    if (!holding) return;
    holding = false;
    if (!mic || !channel || channel.readyState !== "open") return;
    mic.enabled = false;
    emit({ type: "input_audio_buffer.commit" });
    setStatus("thinking", "Transcribing…");
  }

  async function speak(text) {
    text = String(text || "").trim();
    if (!text || closed) return;
    await connect();
    stopRemoteSpeech();
    const id = `banjo-${++speechCounter}`;
    activeSpeech = id;
    speaking = true;
    setStatus("speaking", "AI Guide is speaking.");
    emit({
      type: "response.create",
      response: {
        conversation: "none",
        input: [],
        output_modalities: ["audio"],
        metadata: { banjo_speech: id },
        instructions:
          "Say exactly the following Banjo guide reply naturally. Do not add, remove, " +
          "summarize, answer, or introduce anything.\n\n" + JSON.stringify(text),
      },
    });
  }

  button.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    activePointer = event.pointerId;
    button.setPointerCapture?.(event.pointerId);
    start();
  });
  button.addEventListener("pointerup", (event) => {
    if (activePointer !== event.pointerId) return;
    event.preventDefault();
    activePointer = null;
    stop();
  });
  button.addEventListener("pointercancel", (event) => {
    if (activePointer !== event.pointerId) return;
    activePointer = null;
    stop();
  });
  button.addEventListener("keydown", (event) => {
    if (!["Space", "Enter"].includes(event.code) || event.repeat) return;
    event.preventDefault();
    start();
  });
  button.addEventListener("keyup", (event) => {
    if (!["Space", "Enter"].includes(event.code)) return;
    event.preventDefault();
    stop();
  });

  const keydown = (event) => {
    if (event.code !== "KeyV" || event.repeat || event.altKey || event.ctrlKey ||
        event.metaKey || editableTarget(event.target)) return;
    event.preventDefault();
    start();
  };
  const keyup = (event) => {
    // If V began outside a text box, always honor its release even if focus
    // moved while the microphone was held.
    if (event.code !== "KeyV" || !holding) return;
    event.preventDefault();
    stop();
  };
  const releaseOnBlur = () => { if (holding) stop(); };
  const releaseWhenHidden = () => { if (document.hidden && holding) stop(); };
  addEventListener("keydown", keydown);
  addEventListener("keyup", keyup);
  addEventListener("blur", releaseOnBlur);
  document.addEventListener("visibilitychange", releaseWhenHidden);

  function destroy() {
    if (closed) return;
    closed = true;
    removeEventListener("keydown", keydown);
    removeEventListener("keyup", keyup);
    removeEventListener("blur", releaseOnBlur);
    document.removeEventListener("visibilitychange", releaseWhenHidden);
    cleanupConnection();
    button.remove();
    status.remove();
  }

  setStatus("idle");
  return { button, status, start, stop, speak, destroy };
}
