// Guard against duplicate injection
if (!window.__humantrust_injected) {
  window.__humantrust_injected = true;

  const FRAME_INTERVAL_MS = 1500;
  let timer = null;
  let sessionId = null;
  let challengeBusy = false;

  // Stable participant mapping
  const tileToId = new Map();
  const videoById = new Map();
  const lastSeenTime = new Map();
  const latest = {};
  const rows = {}; // pid -> DOM row element
  const autoNames = {};
  const manualNames = {};

  // Participant Name Auto-Detection from Google Meet
  const FORBIDDEN_WORDS = new Set([
    "might", "still", "see", "your", "full", "video", "others", "call", "audio",
    "screen", "sharing", "presenting", "presentation", "reframe", "camera",
    "microphone", "turned", "off", "on", "waiting", "joining", "left", "meeting",
    "admit", "deny", "everyone", "chat", "details", "device", "devices", "click",
    "more", "options", "apply", "effects", "visual", "background", "blur", "pin",
    "unpin", "mute", "unmute", "raise", "hand", "switch", "settings", "captions",
    "cc", "reaction", "reactions", "leave", "end", "zoom", "framing", "auto",
    "change", "layout", "troubleshooting", "help", "report", "problem", "info",
    "apps", "people", "keep", "host", "cohost"
  ]);

  function looksLikeName(t) {
    if (!t || typeof t !== "string") return false;
    const clean = t.trim();
    if (clean.length < 2 || clean.length > 35) return false;

    // Discard sentences ending with punctuation like . ! ? : ;
    if (/[.:;?!]$/.test(clean)) return false;

    // Discard strings with punctuation/control symbols inside
    if (/[=+\\_{}\[\]<>\/|@#$%^&*~]/.test(clean)) return false;

    // A person's name has at most 4 words
    const words = clean.split(/\s+/);
    if (words.length > 4) return false;

    // Discard Material icon ligatures like more_vert, mic_off
    if (/^[a-z]+(_[a-z]+)+$/.test(clean)) return false;

    // Must contain letters
    if (!/[A-Za-z]/.test(clean)) return false;

    // Discard pure numbers or time strings like 12:34
    if (/^[\d:\s\.\-\+]+$/.test(clean)) return false;

    // Check individual words against forbidden sentence/control vocabulary
    for (const w of words) {
      const lower = w.toLowerCase().replace(/[^a-z]/g, "");
      if (FORBIDDEN_WORDS.has(lower)) return false;
    }

    return true;
  }

  function cleanName(t) {
    if (!t) return "";
    return t.trim().replace(/\s*\((You|you)\)\s*$/i, "").trim();
  }

  function extractNameFromTile(tile) {
    if (!tile) return null;

    // 1. Check data-self-name attribute on the tile or descendants
    const selfAttr = tile.hasAttribute("data-self-name")
      ? tile
      : tile.querySelector("[data-self-name]");
    if (selfAttr) {
      const val = (selfAttr.getAttribute("data-self-name") || "").trim();
      if (looksLikeName(val)) return cleanName(val);
    }

    // 2. Priority check: element with "(You)" (guaranteed user self-name in Meet)
    for (const el of tile.querySelectorAll("*")) {
      if (el.children.length > 0) continue;
      if (el.closest("button, [role='button'], [role='tooltip'], [role='menu'], [role='dialog'], [role='alert']")) continue;
      const text = (el.textContent || "").trim();
      if (/\((You|you)\)/i.test(text)) {
        const cleaned = cleanName(text);
        if (looksLikeName(cleaned)) return cleaned;
      }
    }

    // 3. Check elements with dir="auto" (Google Meet uses dir="auto" on participant names)
    for (const el of tile.querySelectorAll("[dir='auto']")) {
      if (el.children.length > 0) continue;
      if (el.closest("button, [role='button'], [role='tooltip'], [role='menu'], [role='dialog'], [role='alert']")) continue;
      const text = (el.textContent || "").trim();
      if (looksLikeName(text)) return cleanName(text);
    }

    // 4. Check visible leaf elements, strictly excluding buttons/controls/alerts
    for (const el of tile.querySelectorAll("*")) {
      if (el.children.length > 0) continue;
      if (el.closest("button, [role='button'], [role='tooltip'], [role='menu'], [role='menuitem'], [role='dialog'], [role='alert']")) continue;
      const text = (el.textContent || "").trim();
      if (looksLikeName(text)) return cleanName(text);
    }

    // 5. Global fallback for self-view: page-level data-self-name
    const pageSelf = document.querySelector("[data-self-name]");
    if (pageSelf) {
      const val = (pageSelf.getAttribute("data-self-name") || "").trim();
      if (looksLikeName(val)) return cleanName(val);
    }

    return null;
  }

  function labelOf(pid) {
    if (manualNames[pid]) return manualNames[pid];
    if (autoNames[pid]) return autoNames[pid];
    return "Participant " + pid.replace("p", "");
  }

  function getTile(video) {
    const tagged = video.closest('[data-participant-id], [data-requested-participant-id], [data-tile-id], [data-allocation-index], [data-self-name]');
    if (tagged) return tagged;

    // Fallback: climb parent chain while the parent contains only THIS single video element.
    let el = video;
    for (let i = 0; i < 8 && el.parentElement && el.parentElement.tagName !== "BODY"; i++) {
      if (el.parentElement.querySelectorAll("video").length > 1) {
        break;
      }
      el = el.parentElement;
    }
    return el;
  }

  function isScreenShare(video) {
    if (!video) return false;

    // 1. Direct presentation attributes on video element
    const vAria = (video.getAttribute("aria-label") || "").toLowerCase();
    if (vAria.includes("presentation") || vAria.includes("presenting") || vAria.includes("screen share")) {
      return true;
    }

    // 2. Direct ancestor attributes indicating a Google Meet presentation
    if (
      video.closest('[data-is-presentation="true"]') ||
      video.closest('[data-presentation-id]') ||
      video.closest('[data-is-screen-share="true"]') ||
      video.closest('[data-participant-id*="presentation" i]') ||
      video.closest('[data-requested-participant-id*="presentation" i]')
    ) {
      return true;
    }

    // 3. Inspect the enclosing tile container
    const tile = getTile(video);
    if (tile && tile !== document.body) {
      const pidAttr = (tile.getAttribute("data-participant-id") || "").toLowerCase();
      const reqPidAttr = (tile.getAttribute("data-requested-participant-id") || "").toLowerCase();
      if (
        tile.getAttribute("data-is-presentation") === "true" ||
        tile.hasAttribute("data-presentation-id") ||
        pidAttr.includes("presentation") ||
        reqPidAttr.includes("presentation")
      ) {
        return true;
      }

      const tileAria = (tile.getAttribute("aria-label") || "").toLowerCase();
      if (
        tileAria.includes("presentation") ||
        tileAria.includes("presenting") ||
        tileAria.includes("screen share") ||
        tileAria.includes("screen sharing")
      ) {
        return true;
      }

      // Check child element aria-labels (e.g. "Stop presenting" button, presentation badges)
      for (const el of tile.querySelectorAll("[aria-label]")) {
        const a = (el.getAttribute("aria-label") || "").toLowerCase();
        if (
          a.includes("presentation") ||
          a.includes("presenting") ||
          a.includes("screen share") ||
          a.includes("stop presenting")
        ) {
          return true;
        }
      }

      // Check visible text content inside the tile
      const text = (tile.innerText || tile.textContent || "").toLowerCase();
      if (
        text.includes("presentation") ||
        text.includes("is presenting") ||
        text.includes("stop presenting") ||
        text.includes("you're presenting") ||
        text.includes("you are presenting") ||
        text.includes("screen share") ||
        text.includes("screen sharing")
      ) {
        return true;
      }
    }

    return false;
  }

  function getVideos() {
    return Array.from(document.querySelectorAll("video")).filter(
      (v) => v.readyState >= 2 && v.videoWidth > 0 && !v.paused && !isScreenShare(v)
    );
  }

  function cleanupStaleTiles() {
    for (const [tile, pid] of Array.from(tileToId.entries())) {
      const v = videoById.get(pid);
      if (!document.body.contains(tile) || (v && isScreenShare(v))) {
        tileToId.delete(tile);
        videoById.delete(pid);
        lastSeenTime.delete(pid);
        delete latest[pid];
        delete autoNames[pid];
        delete manualNames[pid];
        if (rows[pid]) {
          rows[pid].remove();
          delete rows[pid];
        }
      }
    }
  }

  function getIdForVideo(video) {
    const tile = getTile(video);
    if (tileToId.has(tile)) {
      const id = tileToId.get(tile);
      videoById.set(id, video);
      return id;
    }

    const usedIds = new Set(tileToId.values());
    let num = 1;
    while (usedIds.has("p" + num)) {
      num++;
    }
    const assigned = "p" + num;
    tileToId.set(tile, assigned);
    videoById.set(assigned, video);
    return assigned;
  }

  function captureFrame(video, maxWidth = 640, quality = 0.7) {
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", quality).split(",")[1];
  }

  function tick() {
    cleanupStaleTiles();
    const videos = getVideos();
    const activePids = new Set();
    const now = Date.now();

    for (const v of videos) {
      if (isScreenShare(v)) continue;
      try {
        const pid = getIdForVideo(v);
        activePids.add(pid);
        lastSeenTime.set(pid, now);

        // Try extracting participant display name from the video's tile
        const detectedName = extractNameFromTile(getTile(v));
        if (detectedName && autoNames[pid] !== detectedName) {
          autoNames[pid] = detectedName;
          renderBadge();
        }

        const base64Data = captureFrame(v, 640, 0.7);
        chrome.runtime.sendMessage({
          type: "FRAME",
          sessionId,
          participantId: pid,
          name: labelOf(pid),
          ts: now,
          image: base64Data,
        });
      } catch (err) {
        if (String(err).includes("context invalidated")) {
          if (timer) clearInterval(timer);
          timer = null;
          return;
        }
        console.warn("[HumanTrust] frame capture exception:", err);
      }
    }

    // Prune stale participants who left the call
    let changed = false;
    for (const pid of Object.keys(latest)) {
      const last = lastSeenTime.get(pid) || 0;
      if (!activePids.has(pid) && now - last > 3500) {
        delete latest[pid];
        if (rows[pid]) {
          rows[pid].remove();
          delete rows[pid];
        }
        lastSeenTime.delete(pid);
        videoById.delete(pid);
        changed = true;
      }
    }
    if (changed) {
      renderBadge();
    }
  }

  // ---------- Prompt overlay ----------
  function showPrompt(text) {
    let el = document.getElementById("ht-prompt");
    if (!el) {
      el = document.createElement("div");
      el.id = "ht-prompt";
      Object.assign(el.style, {
        position: "fixed",
        top: "16px",
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: "2147483647",
        background: "#1a73e8",
        color: "#fff",
        padding: "14px 22px",
        borderRadius: "12px",
        font: "600 18px system-ui, -apple-system, sans-serif",
        boxShadow: "0 4px 16px rgba(0,0,0,.4)",
        pointerEvents: "none",
        transition: "all 0.2s ease",
      });
      document.body.appendChild(el);
    }
    el.textContent = text;
  }

  function hidePrompt() {
    document.getElementById("ht-prompt")?.remove();
  }

  function flash(text, ms = 4000) {
    showPrompt(text);
    setTimeout(hidePrompt, ms);
  }

  // ---------- Interactive Liveness Challenge ----------
  async function runChallenge(participantId, ch) {
    const video = videoById.get(participantId);
    if (!video || challengeBusy || isScreenShare(video)) return;
    challengeBusy = true;
    const label = labelOf(participantId);

    video.style.outline = "4px solid #1a73e8";
    showPrompt(`Ask ${label}: ${ch.instruction}`);

    const frames = [];
    const interval = 1000 / ch.fps;
    const end = performance.now() + ch.duration_s * 1000;

    while (performance.now() < end) {
      const t = performance.now();
      frames.push({ ts: Date.now(), image: captureFrame(video, 480, 0.6) });
      const wait = interval - (performance.now() - t);
      if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    }

    video.style.outline = "";
    showPrompt("Analyzing liveness response...");

    chrome.runtime.sendMessage({
      type: "BURST",
      sessionId,
      participantId,
      challengeId: ch.challenge_id,
      frames,
    });
    challengeBusy = false;
  }

  // ---------- Live Trust Badge HUD ----------
  const COLORS = { verified: "#1e8e3e", moderate: "#e37400", suspicious: "#d93025" };

  function renderBadge() {
    let el = document.getElementById("ht-badge");
    if (!el) {
      el = document.createElement("div");
      el.id = "ht-badge";
      Object.assign(el.style, {
        position: "fixed",
        top: "12px",
        right: "12px",
        zIndex: "2147483646",
        display: "flex",
        flexDirection: "column",
        gap: "6px",
        font: "600 13px system-ui, -apple-system, sans-serif",
        pointerEvents: "none",
      });
      document.body.appendChild(el);
    }

    const sortedKeys = Object.keys(latest).sort((a, b) => {
      const numA = parseInt(a.replace(/\D/g, "")) || 0;
      const numB = parseInt(b.replace(/\D/g, "")) || 0;
      return numA - numB;
    });

    for (const pid of sortedKeys) {
      const d = latest[pid];
      if (!d) continue;

      let row = rows[pid];
      if (!row) {
        row = document.createElement("div");
        Object.assign(row.style, {
          color: "#fff",
          padding: "8px 12px",
          borderRadius: "10px",
          boxShadow: "0 2px 8px rgba(0,0,0,.35)",
          display: "flex",
          alignItems: "center",
          gap: "8px",
          transition: "background 0.3s ease",
        });

        const label = document.createElement("span");

        // Rename pencil icon
        const edit = document.createElement("span");
        edit.textContent = "✎";
        edit.title = "Rename participant";
        Object.assign(edit.style, {
          pointerEvents: "auto",
          cursor: "pointer",
          fontSize: "13px",
          opacity: "0.85",
          userSelect: "none",
          marginLeft: "2px",
          marginRight: "4px",
        });
        edit.onclick = (e) => {
          e.stopPropagation();
          const curr = labelOf(pid);
          const val = prompt(`Rename ${curr} to:`, curr);
          if (val && val.trim()) {
            manualNames[pid] = val.trim();
            renderBadge();
          }
        };

        const btn = document.createElement("button");
        btn.textContent = "Challenge";
        Object.assign(btn.style, {
          pointerEvents: "auto",
          cursor: "pointer",
          border: "none",
          borderRadius: "6px",
          padding: "3px 8px",
          font: "600 12px system-ui, sans-serif",
          backgroundColor: "#ffffff",
          color: "#202124",
          boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
        });
        btn.onclick = (e) => {
          e.stopPropagation();
          chrome.runtime.sendMessage({
            type: "CHALLENGE",
            participantId: pid,
            participantName: labelOf(pid),
          });
        };

        row.append(label, edit, btn);
        row._label = label;
        rows[pid] = row;
        el.appendChild(row);
      }

      row.style.background = COLORS[d.status] || "#1e8e3e";
      row._label.textContent =
        labelOf(pid) + ": " + d.total +
        (d.reason ? " | " + d.reason : " | Verified");
    }
  }

  function clearBadge() {
    for (const k of Object.keys(latest)) delete latest[k];
    for (const k of Object.keys(rows)) {
      rows[k].remove();
      delete rows[k];
    }
    lastSeenTime.clear();
    tileToId.clear();
    videoById.clear();
    for (const k of Object.keys(autoNames)) delete autoNames[k];
    for (const k of Object.keys(manualNames)) delete manualNames[k];
    document.getElementById("ht-badge")?.remove();
    hidePrompt();
  }

  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "PING") {
      sendResponse({ pong: true });
      return true;
    }
    if (msg.type === "START_FRAMES") {
      sessionId = msg.sessionId;
      clearBadge();
      if (timer) clearInterval(timer);
      timer = setInterval(tick, FRAME_INTERVAL_MS);
      console.log("[HumanTrust] frame capture started for session:", sessionId);
      sendResponse({ ok: true });
      return true;
    }
    if (msg.type === "STOP_FRAMES") {
      if (timer) clearInterval(timer);
      timer = null;
      sessionId = null;
      clearBadge();
      hidePrompt();
      console.log("[HumanTrust] frame capture stopped");
      sendResponse({ ok: true });
      return true;
    }
    if (msg.type === "TRUST_UPDATE") {
      latest[msg.data.participant_id] = msg.data;
      renderBadge();
    }
    if (msg.type === "START_CHALLENGE") {
      runChallenge(msg.participantId, msg.challenge);
    }
    if (msg.type === "CHALLENGE_RESULT") {
      const r = msg.result;
      flash(
        r.ok === false
          ? "Challenge error: " + r.error
          : r.passed
          ? `✅ Liveness passed (${r.response_time}s)`
          : `❌ ${r.note}`
      );
    }
  });
}
