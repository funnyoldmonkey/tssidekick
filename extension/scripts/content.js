console.log("Gemma Sidekick Content Script Loaded.");

// Listener for simple interactions if needed
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "ping") {
        sendResponse({ status: "ok" });
    }
});
