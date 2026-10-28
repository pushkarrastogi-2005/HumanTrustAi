const API = "http://localhost:8000";
const WS_API = "ws://localhost:8000";

let ws = null;
let pingTimer = null;
const lastNotified = {}; // pid -> { status, ts }
const participantNames = {}; // pid -> display name

const STATUS_TITLE = {
  verified: "✅ Verified",
  moderate: "⚠️ Moderate risk",
  suspicious: "🚨 Suspicious",
};

function clearAllNotifications() {
  try {
    chrome.notifications.getAll((items) => {
      if (items) {
        for (const id in items) {
          if (id.startsWith("ht-")) {
            chrome.notifications.clear(id, () => {
              const _ = chrome.runtime.lastError;
            });
          }
        }
      }
    });
  } catch (e) {
    console.warn("[HumanTrust] clearAllNotifications error:", e);
  }
  for (const k in lastNotified) delete lastNotified[k];
  for (const k in participantNames) delete participantNames[k];
}

async function ensureOffscreen() {
  const existing = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
  if (existing && existing.length > 0) return;
  await chrome.offscreen.createDocument({
    url: "offscreen.html",
    reasons: ["USER_MEDIA"],
    justification: "Record meeting tab audio for authenticity analysis",
  });
  await new Promise((r) => setTimeout(r, 150));
}

async function closeOffscreen() {
  try {
    const existing = await chrome.runtime.getContexts({ contextTypes: ["OFFSCREEN_DOCUMENT"] });
    if (existing && existing.length > 0) {
      await chrome.offscreen.closeDocument();
      await new Promise((r) => setTimeout(r, 150));
    }
  } catch (e) {}
}

async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: "PING" });
  } catch (err) {
    console.log("[HumanTrust] Content script not active on tab, injecting content.js...");
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["content.js"],
    });
    await new Promise((r) => setTimeout(r, 200));
  }
}

// ---------- live results over WebSocket ----------
function connectWS(sessionId, tabId) {
  closeWS();
  ws = new WebSocket(`${WS_API}/ws/${sessionId}`);

  ws.onopen = () => {
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 20000);
  };

  ws.onmessage = (e) => {
    if (e.data === "pong") return;
    try {
      const data = JSON.parse(e.data);
      if (data.type === "result") handleResult(data, tabId);
    } catch (err) {
      console.warn("[HumanTrust] WS parse error:", err);
    }
  };

  ws.onclose = async () => {
    clearInterval(pingTimer);
    const { sessionId: current } = await chrome.storage.session.get("sessionId");
    if (current === sessionId) {
      setTimeout(() => connectWS(sessionId, tabId), 3000);
    }
  };
}

function closeWS() {
  clearInterval(pingTimer);
  if (ws) {
    ws.close();
    ws = null;
  }
}

function handleResult(d, tabId) {
  // 1) Update live HUD badge on Google Meet page
  chrome.tabs.sendMessage(tabId, { type: "TRUST_UPDATE", data: d }).catch(() => {});

  // 2) Chrome desktop notification
  const pid = d.participant_id;
  const now = Date.now();
  const prev = lastNotified[pid];

  const isFirstCheck = !prev;
  const statusChanged = prev && prev.status !== d.status;
  const isSuspicious = d.status === "suspicious";
  const intervalPassed = prev && (now - prev.ts > 15000);

  if (isFirstCheck || statusChanged || isSuspicious || intervalPassed) {
    lastNotified[pid] = { status: d.status, ts: now };
    const label = d.name || participantNames[pid] || pid.replace("p", "Participant ");
    if (d.name) participantNames[pid] = d.name;
    const notifId = `ht-${d.session_id || "s"}-${pid}`;

    chrome.notifications.create(
      notifId,
      {
        type: "basic",
        iconUrl: "icons/icon128.png",
        title: `${STATUS_TITLE[d.status] || "HumanTrust"}: ${label}`,
        message: d.reason
          ? `Score ${d.total}. ${d.reason}`
          : `Score ${d.total}. No anomalies detected`,
        priority: 2,
        requireInteraction: isSuspicious,
      },
      () => {
        if (chrome.runtime.lastError) {
          console.warn("[HumanTrust] Notification message:", chrome.runtime.lastError.message);
        }
      }
    );
  }
}

// Service worker restarted mid-session: reconnect
chrome.storage.session.get(["sessionId", "tabId"]).then(({ sessionId, tabId }) => {
  if (sessionId) connectWS(sessionId, tabId);
});

// ---------- session control ----------
async function startSession(tabId) {
  try {
    clearAllNotifications();
    await stopSession(tabId).catch(() => {});
    await closeOffscreen();

    let r;
    try {
      r = await fetch(API + "/session/start", { method: "POST" });
    } catch (netErr) {
      throw new Error(`Cannot connect to backend at ${API}. Is uvicorn running?`);
    }
    const { session_id } = await r.json();

    await chrome.storage.session.set({ sessionId: session_id, tabId });
    connectWS(session_id, tabId);

    // Acquire tab capture stream ID
    let streamId = null;
    try {
      streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
    } catch (err) {
      if (String(err).includes("active stream")) {
        console.warn("[HumanTrust] Active stream detected, resetting offscreen and retrying...");
        await closeOffscreen();
        await new Promise((r) => setTimeout(r, 300));
        streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
      } else {
        throw err;
      }
    }

    await ensureOffscreen();
    chrome.runtime.sendMessage({
      target: "offscreen",
      type: "START_AUDIO",
      streamId,
      sessionId: session_id,
      apiUrl: API,
    });

    await ensureContentScript(tabId);
    await chrome.tabs.sendMessage(tabId, { type: "START_FRAMES", sessionId: session_id });

    return { ok: true, sessionId: session_id };
  } catch (e) {
    console.error("[HumanTrust] startSession error:", e);
    return { ok: false, error: String(e) };
  }
}

async function stopSession(tabId) {
  clearAllNotifications();
  const { sessionId } = await chrome.storage.session.get("sessionId");
  await chrome.storage.session.remove(["sessionId", "tabId"]);
  closeWS();

  if (tabId) {
    chrome.tabs.sendMessage(tabId, { type: "STOP_FRAMES" }).catch(() => {});
  }

  try {
    chrome.runtime.sendMessage({ target: "offscreen", type: "STOP_AUDIO" }).catch(() => {});
  } catch (e) {}
  await closeOffscreen();

  if (sessionId) {
    fetch(API + "/session/end", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId }),
    }).catch((e) => console.warn("[HumanTrust] stopSession end error:", e));
  }
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.target === "offscreen") return;

  if (msg.type === "START") {
    startSession(msg.tabId).then(sendResponse);
    return true;
  }
  if (msg.type === "STOP") {
    stopSession(msg.tabId).then(() => sendResponse({ ok: true }));
    return true;
  }

  // Phase 3: Interactive Liveness challenge trigger from content script button
  if (msg.type === "CHALLENGE") {
    (async () => {
      const { sessionId } = await chrome.storage.session.get("sessionId");
      if (!sessionId || !sender.tab) return;
      const r = await fetch(API + "/liveness/challenge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          participant_id: msg.participantId,
          participant_name: msg.participantName || null,
        }),
      });
      const challenge = await r.json();
      chrome.tabs.sendMessage(sender.tab.id, {
        type: "START_CHALLENGE",
        participantId: msg.participantId,
        challenge,
      });
    })().catch((e) => console.warn("[HumanTrust] challenge failed:", e));
    return;
  }

  // Phase 3: Process burst frames for liveness analysis
  if (msg.type === "BURST") {
    (async () => {
      const r = await fetch(API + "/liveness/burst", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: msg.sessionId,
          participant_id: msg.participantId,
          challenge_id: msg.challengeId,
          frames: msg.frames,
        }),
      });
      const result = await r.json();
      if (sender.tab) {
        chrome.tabs.sendMessage(sender.tab.id, { type: "CHALLENGE_RESULT", result });
      }
    })().catch((e) => console.warn("[HumanTrust] burst upload failed:", e));
    return;
  }

  if (msg.type === "FRAME") {
    if (msg.name) {
      participantNames[msg.participantId] = msg.name;
    }
    fetch(API + "/frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: msg.sessionId,
        participant_id: msg.participantId,
        name: msg.name || null,
        ts: msg.ts,
        image: msg.image,
      }),
    }).catch((e) => console.warn("[HumanTrust] frame upload failed", e));
  }
});
