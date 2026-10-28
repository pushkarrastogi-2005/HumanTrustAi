const status = document.getElementById("status");

document.getElementById("start").onclick = async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      status.textContent = "Error: No active tab found.";
      return;
    }
    if (!tab.url || !tab.url.startsWith("https://meet.google.com/")) {
      status.textContent = "Error: Please open on an active Google Meet call.";
      return;
    }
    status.textContent = "Starting session...";
    const res = await chrome.runtime.sendMessage({ type: "START", tabId: tab.id });
    if (res && res.ok) {
      status.textContent = "Running (session " + res.sessionId + ")";
    } else {
      status.textContent = res && res.error ? res.error : "Failed to start session";
    }
  } catch (err) {
    status.textContent = "Error: " + err.message;
  }
};

document.getElementById("stop").onclick = async () => {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab) {
      await chrome.runtime.sendMessage({ type: "STOP", tabId: tab.id });
    }
    status.textContent = "Stopped";
  } catch (err) {
    status.textContent = "Error: " + err.message;
  }
};
