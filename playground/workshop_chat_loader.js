// Keep the main world untouched. Workshop's existing module builds the editor
// dynamically, so wait for that form before importing the conversational layer.
if (new URLSearchParams(location.search).has("workshop")) {
  const ready = () => document.querySelector("#ws-component-chat");
  if (ready()) {
    await import("/workshop_chat_ui.js");
  } else {
    await new Promise((resolve) => {
      const observer = new MutationObserver(() => {
        if (!ready()) return;
        observer.disconnect();
        resolve();
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
    });
    await import("/workshop_chat_ui.js");
  }
}
