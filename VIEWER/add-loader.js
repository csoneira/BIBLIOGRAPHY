async function loadAddWorkspace() {
  const root = document.getElementById("addRoot");
  const support = document.getElementById("manageSupport");
  try {
    const response = await fetch(`manage.html?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error("The entry workspace could not be loaded");
    const documentCopy = new DOMParser().parseFromString(await response.text(), "text/html");
    const panel = documentCopy.getElementById("entryPanel");
    if (!panel) throw new Error("The entry workspace is missing");
    panel.removeAttribute("hidden");
    panel.open = true;
    root.replaceChildren(panel);
    [...documentCopy.querySelectorAll("main > :not(#entryPanel)")].forEach((element) => support.appendChild(element));
    const script = document.createElement("script");
    script.src = `manage.js?t=${Date.now()}`;
    document.body.appendChild(script);
  } catch (error) {
    document.getElementById("addLoading")?.remove();
    const message = document.createElement("p");
    message.textContent = `${error.message}. Keep the viewer server running and refresh this page.`;
    root.appendChild(message);
  }
}

loadAddWorkspace();
