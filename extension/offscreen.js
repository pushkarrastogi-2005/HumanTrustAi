let stream = null;
let audioCtx = null;
let running = false;
const CHUNK_MS = 4000;

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target !== "offscreen") return;
  if (msg.type === "START_AUDIO") {
    startAudio(msg);
  }
  if (msg.type === "STOP_AUDIO") {
    stopAudio();
    if (sendResponse) sendResponse({ ok: true });
  }
});

async function startAudio({ streamId, sessionId, apiUrl }) {
  try {
    // Release any previous stream first
    stopAudio();

    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: "tab",
          chromeMediaSourceId: streamId,
        },
      },
      video: false,
    });

    // Capturing tab audio mutes it in Chrome; route through AudioContext so the user can still hear
    audioCtx = new AudioContext();
    audioCtx.createMediaStreamSource(stream).connect(audioCtx.destination);

    running = true;
    recordChunk(sessionId, apiUrl);
    console.log("[HumanTrust Offscreen] Audio capture started for session:", sessionId);
  } catch (err) {
    console.error("[HumanTrust Offscreen] Failed to capture tab audio:", err);
  }
}

function recordChunk(sessionId, apiUrl) {
  if (!running || !stream) return;

  try {
    const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
    const parts = [];

    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        parts.push(e.data);
      }
    };

    recorder.onstop = async () => {
      if (parts.length > 0) {
        const form = new FormData();
        form.append("session_id", sessionId);
        form.append("ts", Date.now());
        form.append("file", new Blob(parts, { type: "audio/webm" }), "chunk.webm");
        fetch(apiUrl + "/audio", { method: "POST", body: form }).catch((e) =>
          console.warn("[HumanTrust Offscreen] Audio chunk upload failed:", e)
        );
      }
      if (running) {
        recordChunk(sessionId, apiUrl); // start the next chunk
      }
    };

    recorder.start();
    setTimeout(() => {
      if (recorder.state === "recording") {
        recorder.stop();
      }
    }, CHUNK_MS);
  } catch (err) {
    console.error("[HumanTrust Offscreen] Error in recordChunk:", err);
  }
}

function stopAudio() {
  running = false;
  if (stream) {
    try {
      stream.getTracks().forEach((t) => t.stop());
    } catch (e) {
      console.warn("[HumanTrust Offscreen] Track stop error:", e);
    }
    stream = null;
  }
  if (audioCtx) {
    try {
      audioCtx.close().catch(() => {});
    } catch (e) {}
    audioCtx = null;
  }
  console.log("[HumanTrust Offscreen] Audio capture stopped");
}
