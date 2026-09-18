function parseCsv(text) {
  const rows = [];
  let row = [], value = "", quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (char === '"') {
      if (quoted && text[index + 1] === '"') { value += '"'; index += 1; }
      else quoted = !quoted;
    } else if (char === "," && !quoted) {
      row.push(value); value = "";
    } else if ((char === "\n" || char === "\r") && !quoted) {
      if (value || row.length) { row.push(value); rows.push(row); row = []; value = ""; }
    } else value += char;
  }
  if (value || row.length) { row.push(value); rows.push(row); }
  return rows;
}

function csvRows(text) {
  const parsed = parseCsv(text);
  if (!parsed.length) return [];
  const headers = parsed[0].map((value) => value.trim());
  return parsed.slice(1).map((values) => Object.fromEntries(
    headers.map((header, index) => [header, (values[index] || "").trim()]),
  ));
}

function freshUrl(url) {
  return `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  const contentType = response.headers.get("Content-Type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) {
    const error = new Error(data.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.duplicates = data.duplicates || [];
    throw error;
  }
  return data;
}

async function attachPdf(code, file, replaceExisting = false) {
  const replace = replaceExisting ? "&replace=1" : "";
  const response = await fetch(`/attach-pdf?code=${encodeURIComponent(code)}${replace}`, {
    method: "POST",
    headers: { "Content-Type": "application/pdf" },
    body: file,
    cache: "no-store",
  });
  if (!response.ok) {
    const messages = {
      400: "The selected file is not a valid PDF.",
      409: "A PDF for this entry is already stored on this computer.",
      413: "The PDF is empty or larger than 250 MB.",
    };
    throw new Error(messages[response.status] || `PDF attachment failed (${response.status}).`);
  }
  return response.json();
}

const DRAFT_FIELDS = ["title", "author", "journal", "doi", "keywords", "abstract", "notes"];
const DRAFT_DB_NAME = "bibliography-add-drafts";
const DRAFT_STORE_NAME = "queues";
let entryDrafts = [];
let activeDraftIndex = 0;
let draftPersistenceTimer = null;

function isAddWorkspace() {
  return location.pathname.endsWith("/add.html");
}

function openDraftDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DRAFT_DB_NAME, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(DRAFT_STORE_NAME)) {
        request.result.createObjectStore(DRAFT_STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function persistDraftQueue() {
  if (!isAddWorkspace() || document.getElementById("entryForm")?.dataset.mode === "edit") return;
  const status = document.getElementById("draftPersistenceStatus");
  try {
    const database = await openDraftDatabase();
    await new Promise((resolve, reject) => {
      const transaction = database.transaction(DRAFT_STORE_NAME, "readwrite");
      transaction.objectStore(DRAFT_STORE_NAME).put({
        id: "current", drafts: entryDrafts, activeDraftIndex, savedAt: new Date().toISOString(),
      });
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
    });
    database.close();
    if (status) status.textContent = `Drafts saved automatically · ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    if (status) status.textContent = "Draft storage is unavailable; keep this page open.";
  }
}

function scheduleDraftPersistence() {
  if (!isAddWorkspace()) return;
  window.clearTimeout(draftPersistenceTimer);
  draftPersistenceTimer = window.setTimeout(() => { persistDraftQueue(); }, 180);
}

async function restoreDraftQueue() {
  if (!isAddWorkspace()) return false;
  try {
    const database = await openDraftDatabase();
    const saved = await new Promise((resolve, reject) => {
      const request = database.transaction(DRAFT_STORE_NAME, "readonly")
        .objectStore(DRAFT_STORE_NAME).get("current");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    database.close();
    if (!saved?.drafts?.length) return false;
    entryDrafts = saved.drafts;
    activeDraftIndex = Math.min(Number(saved.activeDraftIndex) || 0, entryDrafts.length - 1);
    renderDraft();
    const restoredAt = new Date(saved.savedAt);
    document.getElementById("draftPersistenceStatus").textContent = Number.isNaN(restoredAt.getTime())
      ? "Restored saved drafts"
      : `Restored saved drafts from ${restoredAt.toLocaleString()}`;
    return true;
  } catch (error) {
    document.getElementById("draftPersistenceStatus").textContent = "Draft storage is unavailable; keep this page open.";
    return false;
  }
}

function setupDraftPersistence() {
  if (!isAddWorkspace()) return;
  navigator.storage?.persist?.().catch(() => {});
  const form = document.getElementById("entryForm");
  const saveCurrent = (event) => {
    if (["entryPdf", "editPdf", "citationImport", "doiImport"].includes(event.target.id)) return;
    captureDraft();
  };
  form.addEventListener("input", saveCurrent);
  form.addEventListener("change", saveCurrent);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      captureDraft();
      persistDraftQueue();
    }
  });
  window.addEventListener("pagehide", () => {
    captureDraft();
    persistDraftQueue();
  });
}

function blankDraft() {
  return {
    title: "", publication_date: "", type: "article", author: "", journal: "", doi: "",
    keywords: "", my_keywords: "", abstract: "", notes: "", unread: true, star: false,
    annotated: false, pdfFile: null, sources: ["Manual draft"],
  };
}

function normalizeIdentifier(value) {
  return (value || "").trim().toLowerCase()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "").replace(/^doi:\s*/, "");
}

function selectedMyKeywords() {
  return [...document.querySelectorAll("#entryMyKeywords input:checked")]
    .map((input) => input.value).join(", ");
}

function setSelectedMyKeywords(value) {
  const wanted = String(value || "").split(/[;,]/).map((item) => item.trim()).filter(Boolean);
  wanted.forEach((keyword) => {
    addMyKeywordChoice(keyword);
  });
  const selected = new Set(wanted.map((keyword) => keyword.toLocaleLowerCase()));
  document.querySelectorAll("#entryMyKeywords input").forEach((input) => {
    input.checked = selected.has(input.value.toLocaleLowerCase());
  });
}

function addMyKeywordChoice(keyword) {
  const container = document.getElementById("entryMyKeywords");
  const existing = [...container.querySelectorAll("input")]
    .find((input) => input.value.toLocaleLowerCase() === keyword.toLocaleLowerCase());
  if (existing) return existing;
  const label = document.createElement("label");
  const input = document.createElement("input");
  input.type = "checkbox";
  input.value = keyword;
  label.append(input, document.createTextNode(keyword));
  container.appendChild(label);
  return input;
}

function draftIsEmpty(draft) {
  return !draft.pdfFile && !(draft.my_keywords || "").trim()
    && !DRAFT_FIELDS.some((field) => (draft[field] || "").trim());
}

function captureDraft() {
  if (!entryDrafts.length || document.getElementById("entryForm").dataset.mode === "edit") return;
  const draft = entryDrafts[activeDraftIndex];
  DRAFT_FIELDS.forEach((field) => {
    draft[field] = document.getElementById(`entry${field.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join("")}`).value;
  });
  draft.my_keywords = selectedMyKeywords();
  const selectedType = document.getElementById("entryType").value;
  draft.type = selectedType === "__new__" ? document.getElementById("entryNewType").value : selectedType;
  draft.publication_date = document.getElementById("entryPublicationDate").value.trim();
  draft.unread = document.getElementById("entryUnread").checked;
  draft.star = document.getElementById("entryStar").checked;
  draft.annotated = document.getElementById("entryAnnotated").checked;
  scheduleDraftPersistence();
}

function renderDraft() {
  const draft = entryDrafts[activeDraftIndex] || blankDraft();
  DRAFT_FIELDS.forEach((field) => {
    document.getElementById(`entry${field.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join("")}`).value = draft[field] || "";
  });
  setSelectedMyKeywords(draft.my_keywords);
  setPublicationDate(draft.publication_date || "");
  const type = document.getElementById("entryType");
  if ([...type.options].some((option) => option.value === draft.type)) {
    type.value = draft.type;
  } else {
    type.value = "__new__";
    document.getElementById("entryNewType").value = draft.type || "article";
  }
  updateNewTypeVisibility();
  document.getElementById("entryUnread").checked = draft.unread !== false;
  document.getElementById("entryStar").checked = Boolean(draft.star);
  document.getElementById("entryAnnotated").checked = Boolean(draft.annotated);
  document.getElementById("entryPdf").value = "";
  document.getElementById("draftCounter").textContent = `${activeDraftIndex + 1} / ${entryDrafts.length}`;
  const pdfStatus = document.getElementById("draftPdfStatus");
  pdfStatus.hidden = !draft.pdfFile;
  pdfStatus.textContent = draft.pdfFile ? `Current draft PDF: ${draft.pdfFile.name}` : "";
  document.getElementById("previousDraftBtn").disabled = activeDraftIndex === 0;
  document.getElementById("nextDraftBtn").disabled = activeDraftIndex >= entryDrafts.length - 1;
}

function startDraftQueue() {
  entryDrafts = [blankDraft()];
  activeDraftIndex = 0;
  document.getElementById("entryImportWorkspace").hidden = false;
  renderDraft();
}

function publicationDatePrecision(value) {
  const match = String(value || "").trim().match(/^\d{4}(?:-(\d{2})(?:-(\d{2}))?)?$/);
  if (!match) return 0;
  if (match[2]) return 3;
  if (match[1]) return 2;
  return 1;
}

function mergeDraft(draft, values, overwrite = false) {
  ["title", "publication_date", "type", "author", "journal", "doi", "keywords", "abstract"].forEach((field) => {
    const value = String(values[field] || "").trim();
    const current = String(draft[field] || "").trim();
    const losesDateDetail = field === "publication_date" && values.source === "Crossref"
      && publicationDatePrecision(value) < publicationDatePrecision(current);
    if (value && !losesDateDetail && (overwrite || !current)) draft[field] = value;
  });
  if (values.source && !draft.sources.includes(values.source)) draft.sources.push(values.source);
  if (values.annotated) draft.annotated = true;
  return draft;
}

function findDraft(values) {
  const doi = normalizeIdentifier(values.doi);
  if (doi) {
    const match = entryDrafts.find((draft) => normalizeIdentifier(draft.doi) === doi);
    if (match) return match;
  }
  const title = (values.title || "").trim().toLocaleLowerCase();
  return title ? entryDrafts.find((draft) => (draft.title || "").trim().toLocaleLowerCase() === title) : null;
}

function addDraft(values) {
  let draft = findDraft(values);
  if (!draft && entryDrafts.length === 1 && draftIsEmpty(entryDrafts[0])) draft = entryDrafts[0];
  if (!draft) {
    draft = blankDraft();
    entryDrafts.push(draft);
  }
  if (draftIsEmpty(draft)) draft.sources = [];
  mergeDraft(draft, values, false);
  scheduleDraftPersistence();
  return draft;
}

async function lookupIntoDraft(identifier, preferredDraft = null) {
  const item = await postJson("/lookup-reference", { identifier });
  let draft = findDraft({ doi: item.doi || identifier, title: item.title });
  if (!draft) draft = preferredDraft || addDraft({ doi: item.doi || identifier, source: item.source });
  mergeDraft(draft, item, true);
  scheduleDraftPersistence();
  return draft;
}

async function inspectPdf(file) {
  const response = await fetch(`/inspect-pdf?name=${encodeURIComponent(file.name)}`, {
    method: "POST", headers: { "Content-Type": "application/pdf" }, body: file, cache: "no-store",
  });
  if (!response.ok) throw new Error(`Could not inspect ${file.name} (${response.status}).`);
  return response.json();
}

function catalogTypes(rows) {
  return [...new Set(rows.map((row) => (row.type || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
}

function catalogMyKeywords(rows, config) {
  const keywords = new Map();
  rows.forEach((row) => {
    (row.my_keywords || "").split(/[;,]/).forEach((value) => {
      const keyword = value.trim();
      if (keyword && !keywords.has(keyword.toLocaleLowerCase())) {
        keywords.set(keyword.toLocaleLowerCase(), keyword);
      }
    });
  });
  (config.my_keywords || []).forEach((entry) => {
    const keyword = (typeof entry === "string" ? entry : entry?.tag || "").trim();
    if (keyword && !keywords.has(keyword.toLocaleLowerCase())) {
      keywords.set(keyword.toLocaleLowerCase(), keyword);
    }
  });
  return [...keywords.values()].sort((a, b) => a.localeCompare(b));
}

function setupMyKeywords(rows, config) {
  const keywords = catalogMyKeywords(rows, config);
  const entrySelect = document.getElementById("entryMyKeywords");
  const source = document.getElementById("manageKeywordSource");
  const known = document.getElementById("knownMyKeywords");
  entrySelect.innerHTML = "";
  source.innerHTML = "";
  known.innerHTML = "";
  keywords.forEach((keyword) => {
    addMyKeywordChoice(keyword);
    source.add(new Option(keyword, keyword));
    const suggestion = document.createElement("option");
    suggestion.value = keyword;
    known.appendChild(suggestion);
  });
  document.getElementById("manageKeywordBtn").disabled = !keywords.length;
  document.getElementById("deleteKeywordBtn").disabled = !keywords.length;
}

function setupTypes(rows) {
  const types = catalogTypes(rows);
  const entryType = document.getElementById("entryType");
  const source = document.getElementById("manageTypeSource");
  const known = document.getElementById("knownTypes");
  [entryType, source, known].forEach((element) => { element.innerHTML = ""; });
  types.forEach((type) => {
    entryType.add(new Option(type, type));
    source.add(new Option(type, type));
    const suggestion = document.createElement("option");
    suggestion.value = type;
    known.appendChild(suggestion);
  });
  entryType.add(new Option("+ Add new type…", "__new__"));
  entryType.value = types.includes("article") ? "article" : (types[0] || "__new__");
  entryType.addEventListener("change", updateNewTypeVisibility);
  updateNewTypeVisibility();
}

function updateNewTypeVisibility() {
  const adding = document.getElementById("entryType").value === "__new__";
  document.getElementById("entryNewTypeContainer").hidden = !adding;
  document.getElementById("entryNewType").required = adding;
}

function setupEntries(rows) {
  const list = document.getElementById("knownEntries");
  rows.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.code;
    option.label = row.title || row.code;
    list.appendChild(option);
  });
}

function setPublicationDate(value) {
  document.getElementById("entryPublicationDate").value = value || "";
}

function resetForm(clearUrl = true) {
  const form = document.getElementById("entryForm");
  form.reset();
  form.dataset.mode = "create";
  form.dataset.legacyYear = "";
  document.getElementById("entryCode").value = "";
  document.getElementById("entryFormTitle").textContent = "Add bibliography entry";
  document.getElementById("createEntryBtn").textContent = "Add entry";
  document.getElementById("cancelEditBtn").hidden = true;
  document.getElementById("entryPdfHostsContainer").hidden = true;
  document.getElementById("editPdfContainer").hidden = true;
  document.getElementById("entryStatus").textContent = "";
  document.getElementById("entryUnread").checked = true;
  document.getElementById("entryAnnotated").checked = false;
  const types = document.getElementById("entryType");
  if ([...types.options].some((option) => option.value === "article")) types.value = "article";
  setPublicationDate("");
  updateNewTypeVisibility();
  startDraftQueue();
  if (clearUrl) history.replaceState({}, "", location.pathname.endsWith("/add.html") ? "add.html" : "manage.html");
}

function editEntry(row) {
  const form = document.getElementById("entryForm");
  document.getElementById("entryPanel").open = true;
  document.getElementById("entryImportWorkspace").hidden = true;
  form.dataset.mode = "edit";
  form.dataset.legacyYear = row.publication_date ? "" : (row.year || "");
  document.getElementById("entryCode").value = row.code;
  document.getElementById("entryTitle").value = row.title || "";
  setPublicationDate(row.publication_date || "");
  const type = document.getElementById("entryType");
  if ([...type.options].some((option) => option.value === row.type)) type.value = row.type;
  document.getElementById("entryAuthor").value = row.author || "";
  document.getElementById("entryJournal").value = row.journal || "";
  document.getElementById("entryDoi").value = row.doi || "";
  document.getElementById("entryKeywords").value = row.keywords || "";
  setSelectedMyKeywords(row.my_keywords || "");
  document.getElementById("entryAbstract").value = row.abstract || "";
  document.getElementById("entryNotes").value = row.notes || "";
  document.getElementById("entryUnread").checked = row.unread === "1";
  document.getElementById("entryStar").checked = row.star === "1";
  document.getElementById("entryAnnotated").checked = row.annotated === "1";
  document.getElementById("entryPdfHosts").value = row.pdf_hosts || "";
  document.getElementById("entryPdfHostsContainer").hidden = false;
  document.getElementById("editPdfContainer").hidden = false;
  document.getElementById("cancelEditBtn").hidden = false;
  document.getElementById("entryFormTitle").textContent = `Edit: ${row.title || row.code}`;
  document.getElementById("createEntryBtn").textContent = "Save changes";
  updateNewTypeVisibility();
}

async function loadRows() {
  const [metadataResponse, abstractsResponse] = await Promise.all([
    fetch(freshUrl("../METADATA/metadata.csv"), { cache: "no-store" }),
    fetch(freshUrl("/abstracts"), { cache: "no-store" }),
  ]);
  if (!metadataResponse.ok) throw new Error("metadata.csv could not be loaded");
  const rows = csvRows(await metadataResponse.text());
  const abstracts = abstractsResponse.ok ? (await abstractsResponse.json()).abstracts || {} : {};
  rows.forEach((row) => { row.abstract = abstracts[row.code] || ""; });
  return rows;
}

async function loadSavedFilters() {
  const response = await fetch(freshUrl("/saved-filters"), { cache: "no-store" });
  if (!response.ok) throw new Error("Saved filters could not be loaded");
  const filters = (await response.json()).filter((item) => item.dynamic);
  return filters.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
}

async function loadKeywordConfig() {
  const response = await fetch(freshUrl("../CONFIGS/config.json"), { cache: "no-store" });
  if (!response.ok) return { my_keywords: [] };
  return response.json();
}

async function loadChangeHistory() {
  const response = await fetch(freshUrl("/change-history"), { cache: "no-store" });
  if (!response.ok) throw new Error("Change history could not be loaded");
  return (await response.json()).history || [];
}

function setupChangeHistory(items) {
  const list = document.getElementById("changeHistoryList");
  const empty = document.getElementById("changeHistoryEmpty");
  const undoButton = document.getElementById("undoBtn");
  list.innerHTML = "";
  empty.hidden = items.length > 0;
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "history-item";
    const description = document.createElement("div");
    const action = document.createElement("strong");
    action.textContent = item.action
      ? `${item.action.charAt(0).toUpperCase()}${item.action.slice(1)}`
      : "Change";
    const time = document.createElement("time");
    const parsedDate = new Date(item.created_at);
    time.textContent = Number.isNaN(parsedDate.getTime())
      ? item.created_at
      : parsedDate.toLocaleString();
    const state = document.createElement("span");
    state.className = `history-state${item.status === "undone" ? " undone" : ""}`;
    state.textContent = item.status === "undone"
      ? "Undone"
      : (item.undoable ? "Latest · can undo" : "Applied");
    description.append(action, time);
    row.append(description, state);
    list.appendChild(row);
  });
  undoButton.disabled = !items.some((item) => item.undoable);
}

async function refreshLibraryCheckpoint() {
  const response = await fetch(freshUrl("/library-status"), { cache: "no-store" });
  if (!response.ok) throw new Error("Library status could not be loaded");
  const data = await response.json();
  const badge = document.getElementById("checkpointBadge");
  badge.textContent = data.clean ? "No pending data changes" : `${data.changes.length} pending data change(s)`;
  badge.classList.toggle("clean", data.clean);
  const sync = document.getElementById("checkpointSync");
  sync.textContent = data.ahead === null
    ? "Git synchronization unavailable"
    : `GitHub: ${data.ahead} ahead, ${data.behind} behind`;
  const files = document.getElementById("checkpointFiles");
  files.replaceChildren();
  data.changes.forEach((change) => {
    const item = document.createElement("li");
    item.textContent = change;
    files.appendChild(item);
  });
  document.getElementById("checkpointCommands").textContent = data.commands.join("\n");
  return data;
}

function setupLibraryCheckpoint() {
  const status = document.getElementById("checkpointStatus");
  const output = document.getElementById("validationOutput");
  document.getElementById("refreshCheckpointBtn").addEventListener("click", async () => {
    status.textContent = "Refreshing…";
    try {
      await refreshLibraryCheckpoint();
      status.textContent = "Status refreshed";
    } catch (error) { status.textContent = error.message; }
  });
  document.getElementById("validateLibraryBtn").addEventListener("click", async () => {
    status.textContent = "Validating…";
    output.hidden = true;
    try {
      const result = await postJson("/validate-library", {});
      output.textContent = result.checks
        .map((check) => `${check.ok ? "✓" : "✗"} ${check.label}\n${check.output}`)
        .join("\n\n");
      output.hidden = false;
      status.textContent = result.ok ? "Library validation passed" : "Validation found problems";
    } catch (error) { status.textContent = `Validation failed: ${error.message}`; }
  });
  document.getElementById("checkpointLibraryBtn").addEventListener("click", async () => {
    status.textContent = "Creating backup…";
    try {
      const result = await postJson("/checkpoint-library", {});
      status.textContent = `Backup created: ${result.path}`;
    } catch (error) { status.textContent = `Backup failed: ${error.message}`; }
  });
  refreshLibraryCheckpoint().catch((error) => { status.textContent = error.message; });
}

function setupSavedFilterManager(filters) {
  const select = document.getElementById("savedFilterSelect");
  const nameInput = document.getElementById("savedFilterName");
  select.innerHTML = "";
  filters.forEach((filter) => select.add(new Option(filter.name || filter.filename, filter.filename)));
  const updateSelection = () => {
    const selected = filters.find((filter) => filter.filename === select.value);
    nameInput.value = selected?.name || "";
    nameInput.disabled = !selected;
    document.getElementById("renameFilterBtn").disabled = !selected;
    document.getElementById("deleteFilterBtn").disabled = !selected;
  };
  select.addEventListener("change", updateSelection);
  updateSelection();
}

async function setupWallpaperOptions() {
  const wallpaper = window.bibliographyWallpaper;
  if (!wallpaper) return;
  try {
    const response = await fetch(freshUrl("/wallpapers"), { cache: "no-store" });
    if (response.ok) {
      const customContainer = document.getElementById("customWallpaperOptions");
      const data = await response.json();
      (data.custom || []).forEach((item) => {
        const label = document.createElement("label");
        label.className = "wallpaper-option";
        const preview = document.createElement("span");
        preview.className = "wallpaper-preview";
        preview.style.backgroundImage = `url("${item.url}")`;
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "wallpaper";
        input.value = item.id;
        label.appendChild(preview);
        label.appendChild(input);
        label.appendChild(document.createTextNode(` ${item.name}`));
        customContainer.appendChild(label);
      });
    }
  } catch (error) {
    document.getElementById("wallpaperUploadStatus").textContent = "Custom pictures unavailable";
  }
  const current = wallpaper.current();
  document.querySelectorAll('input[name="wallpaper"]').forEach((input) => {
    input.checked = input.value === current;
    input.addEventListener("change", () => {
      if (input.checked) wallpaper.save(input.value);
    });
  });
  const transparency = document.getElementById("wallpaperTransparency");
  const transparencyValue = document.getElementById("wallpaperTransparencyValue");
  transparency.value = wallpaper.currentTransparency();
  transparencyValue.value = `${transparency.value}%`;
  transparency.addEventListener("input", () => {
    transparencyValue.value = `${transparency.value}%`;
    wallpaper.saveTransparency(transparency.value);
  });

  document.getElementById("uploadWallpaperBtn").addEventListener("click", async () => {
    const file = document.getElementById("customWallpaperUpload").files[0];
    const status = document.getElementById("wallpaperUploadStatus");
    if (!file) { alert("Choose a JPEG, PNG, or WebP image first."); return; }
    status.textContent = "Uploading…";
    try {
      const response = await fetch(`/upload-wallpaper?name=${encodeURIComponent(file.name)}`, {
        method: "POST",
        headers: { "Content-Type": file.type || "application/octet-stream" },
        body: file,
      });
      if (!response.ok) throw new Error(await response.text() || "Upload failed");
      const item = await response.json();
      wallpaper.save(item.id);
      status.textContent = "Picture added";
      window.setTimeout(() => location.reload(), 400);
    } catch (error) {
      status.textContent = "Upload failed";
      alert(error.message);
    }
  });
}

async function init() {
  try {
    const [rows, savedFilters, keywordConfig, changeHistory] = await Promise.all([
      loadRows(), loadSavedFilters(), loadKeywordConfig(), loadChangeHistory(),
    ]);
    const editCode = new URLSearchParams(location.search).get("edit");
    setupTypes(rows);
    setupEntries(rows);
    setupMyKeywords(rows, keywordConfig);
    setupChangeHistory(changeHistory);
    setupSavedFilterManager(savedFilters);
    await setupWallpaperOptions();
    resetForm(false);
    if (location.pathname.endsWith("/manage.html")) setupLibraryCheckpoint();

    if (editCode) {
      const row = rows.find((item) => item.code === editCode);
      if (row) editEntry(row);
    } else {
      await restoreDraftQueue();
    }
    setupDraftPersistence();

    document.getElementById("cancelEditBtn").addEventListener("click", async () => {
      resetForm(true);
      await restoreDraftQueue();
    });
    document.getElementById("showNewKeywordBtn").addEventListener("click", () => {
      const container = document.getElementById("entryNewKeywordContainer");
      container.hidden = !container.hidden;
      if (!container.hidden) document.getElementById("entryNewKeyword").focus();
    });
    const addNewMyKeyword = () => {
      const input = document.getElementById("entryNewKeyword");
      const keyword = input.value.trim();
      if (!keyword || keyword.length > 80 || /[;,\r\n]/.test(keyword)) {
        alert("Enter a keyword of 80 characters or fewer without commas or semicolons.");
        return;
      }
      const choice = addMyKeywordChoice(keyword);
      choice.checked = true;
      input.value = "";
      document.getElementById("entryNewKeywordContainer").hidden = true;
      captureDraft();
    };
    document.getElementById("addNewKeywordBtn").addEventListener("click", addNewMyKeyword);
    document.getElementById("entryNewKeyword").addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      addNewMyKeyword();
    });

    document.getElementById("undoBtn").addEventListener("click", async () => {
      if (!confirm("Undo the most recent viewer change?")) return;
      const status = document.getElementById("undoStatus");
      status.textContent = "Undoing…";
      try {
        const result = await postJson("/undo-last-change", {});
        status.textContent = `Undid: ${result.action}`;
        location.reload();
      } catch (error) { status.textContent = "Undo failed"; alert(error.message); }
    });

    document.getElementById("auditBtn").addEventListener("click", async () => {
      const button = document.getElementById("auditBtn");
      button.disabled = true;
      button.textContent = "Checking…";
      try {
        const response = await fetch(freshUrl("/pdf-audit"), { cache: "no-store" });
        if (!response.ok) throw new Error("Audit failed");
        const audit = await response.json();
        const duplicateText = audit.duplicates.length
          ? `\nDuplicate-file groups:\n${audit.duplicates.map((codes) => codes.join(", ")).join("\n")}`
          : "\nNo duplicate local PDF files.";
        const annotationText = audit.annotation_scan
          ? `\nAnnotation scan: ${audit.annotation_scan.checked} checked, ${audit.annotation_scan.updated} newly marked`
          : "";
        alert(`Local PDFs: ${audit.summary.local}\nChecksums OK: ${audit.summary.ok}\nNot yet recorded: ${audit.summary.unrecorded}\nChanged/mismatched: ${audit.summary.mismatch}${annotationText}${duplicateText}`);
      } catch (error) {
        alert("Could not audit local PDFs. Keep the viewer server running.");
      } finally {
        button.disabled = false;
        button.textContent = "Audit PDFs";
      }
    });

    document.getElementById("renameFilterBtn").addEventListener("click", async () => {
      const filename = document.getElementById("savedFilterSelect").value;
      const newName = document.getElementById("savedFilterName").value.trim();
      const current = savedFilters.find((filter) => filter.filename === filename);
      if (!current || !newName) { alert("Choose a filter and enter its new name."); return; }
      if (!confirm(`Rename “${current.name}” to “${newName}”?`)) return;
      try {
        await postJson("/manage-saved-filter", { action: "rename", filename, new_name: newName });
        document.getElementById("savedFilterManageStatus").textContent = "Filter renamed";
        window.setTimeout(() => location.reload(), 500);
      } catch (error) {
        document.getElementById("savedFilterManageStatus").textContent = "Rename failed";
        alert(error.message);
      }
    });

    document.getElementById("deleteFilterBtn").addEventListener("click", async () => {
      const filename = document.getElementById("savedFilterSelect").value;
      const current = savedFilters.find((filter) => filter.filename === filename);
      if (!current) { alert("Choose a saved filter first."); return; }
      if (!confirm(`Delete the saved filter “${current.name}”? You can undo this action.`)) return;
      try {
        await postJson("/manage-saved-filter", { action: "delete", filename });
        document.getElementById("savedFilterManageStatus").textContent = "Filter deleted";
        window.setTimeout(() => location.reload(), 500);
      } catch (error) {
        document.getElementById("savedFilterManageStatus").textContent = "Delete failed";
        alert(error.message);
      }
    });

    document.getElementById("previousDraftBtn").addEventListener("click", () => {
      captureDraft();
      if (activeDraftIndex > 0) activeDraftIndex -= 1;
      renderDraft();
    });
    document.getElementById("nextDraftBtn").addEventListener("click", () => {
      captureDraft();
      if (activeDraftIndex < entryDrafts.length - 1) activeDraftIndex += 1;
      renderDraft();
    });
    document.getElementById("discardDraftBtn").addEventListener("click", () => {
      captureDraft();
      const draft = entryDrafts[activeDraftIndex];
      if (!draftIsEmpty(draft) && !confirm("Discard this unsaved draft?")) return;
      entryDrafts.splice(activeDraftIndex, 1);
      if (!entryDrafts.length) entryDrafts.push(blankDraft());
      activeDraftIndex = Math.min(activeDraftIndex, entryDrafts.length - 1);
      renderDraft();
      scheduleDraftPersistence();
      document.getElementById("entryStatus").textContent = "Draft discarded; no catalog changes were made";
    });

    document.getElementById("importCitationsBtn").addEventListener("click", async () => {
      const text = document.getElementById("citationImport").value.trim();
      const status = document.getElementById("entryStatus");
      if (!text) { alert("Paste one or more RIS or BibTeX records first."); return; }
      captureDraft();
      status.textContent = "Parsing citation records…";
      try {
        const result = await postJson("/parse-citations", { text });
        const imported = result.entries.map((entry) => addDraft(entry));
        let enriched = 0;
        for (const draft of imported) {
          if (!draft.doi) continue;
          try { await lookupIntoDraft(draft.doi, draft); enriched += 1; } catch (error) { /* Keep citation metadata. */ }
        }
        activeDraftIndex = Math.max(0, entryDrafts.indexOf(imported[0]));
        document.getElementById("citationImport").value = "";
        renderDraft();
        status.textContent = `Added ${imported.length} citation record(s); enriched ${enriched} from DOI`;
      } catch (error) { status.textContent = "Citation import failed"; alert(error.message); }
    });

    document.getElementById("importDoisBtn").addEventListener("click", async () => {
      const identifiers = document.getElementById("doiImport").value
        .split(/[\n,;]+/).map((value) => value.trim()).filter(Boolean);
      if (!identifiers.length) { alert("Enter one or more DOI or arXiv identifiers first."); return; }
      captureDraft();
      const status = document.getElementById("entryStatus");
      status.textContent = `Retrieving 0 / ${identifiers.length}…`;
      let completed = 0;
      const failures = [];
      for (const identifier of identifiers) {
        try { await lookupIntoDraft(identifier); } catch (error) { failures.push(identifier); }
        completed += 1;
        status.textContent = `Retrieving ${completed} / ${identifiers.length}…`;
      }
      document.getElementById("doiImport").value = "";
      renderDraft();
      status.textContent = `Processed ${completed - failures.length} identifier(s)${failures.length ? `; ${failures.length} failed` : ""}`;
      if (failures.length) alert(`These identifiers could not be retrieved:\n${failures.join("\n")}`);
    });

    document.getElementById("inspectPdfsBtn").addEventListener("click", async () => {
      const files = [...document.getElementById("entryPdf").files];
      if (!files.length) { alert("Choose one or more PDF files first."); return; }
      captureDraft();
      const status = document.getElementById("entryStatus");
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        status.textContent = `Inspecting PDF ${index + 1} / ${files.length}…`;
        try {
          const values = await inspectPdf(file);
          let draft = findDraft(values);
          if (!draft && files.length === 1 && !entryDrafts[activeDraftIndex].pdfFile) draft = entryDrafts[activeDraftIndex];
          if (!draft) draft = addDraft(values);
          if (draftIsEmpty(draft)) draft.sources = [];
          mergeDraft(draft, values, false);
          draft.pdfFile = file;
          if (!draft.sources.includes("PDF scan")) draft.sources.push("PDF scan");
          if (values.doi) {
            try { await lookupIntoDraft(values.doi, draft); } catch (error) { /* Keep cautious PDF values. */ }
          }
          activeDraftIndex = entryDrafts.indexOf(draft);
        } catch (error) { alert(error.message); }
      }
      renderDraft();
      scheduleDraftPersistence();
      status.textContent = `Added ${files.length} PDF file(s) to the review queue`;
    });

    document.getElementById("entryForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = document.getElementById("createEntryBtn");
      const status = document.getElementById("entryStatus");
      const selectedType = document.getElementById("entryType").value;
      captureDraft();
      const pdfFile = form.dataset.mode === "edit"
        ? document.getElementById("editPdf").files[0]
        : entryDrafts[activeDraftIndex]?.pdfFile;
      const payload = {
        code: document.getElementById("entryCode").value,
        title: document.getElementById("entryTitle").value,
        publication_date: document.getElementById("entryPublicationDate").value.trim(),
        year: form.dataset.legacyYear || "",
        type: selectedType === "__new__" ? document.getElementById("entryNewType").value : selectedType,
        author: document.getElementById("entryAuthor").value,
        journal: document.getElementById("entryJournal").value,
        doi: document.getElementById("entryDoi").value,
        keywords: document.getElementById("entryKeywords").value,
        my_keywords: selectedMyKeywords(),
        abstract: document.getElementById("entryAbstract").value,
        notes: document.getElementById("entryNotes").value,
        unread: document.getElementById("entryUnread").checked,
        star: document.getElementById("entryStar").checked,
        annotated: document.getElementById("entryAnnotated").checked,
      };
      if (form.dataset.mode === "edit") payload.pdf_hosts = document.getElementById("entryPdfHosts").value;
      button.disabled = true;
      status.textContent = "Saving…";
      const editing = form.dataset.mode === "edit";
      let saved = null;
      try {
        try {
          saved = await postJson(editing ? "/update-entry" : "/create-entry", payload);
        } catch (error) {
          if (error.status !== 409 || !error.duplicates.length) throw error;
          const names = error.duplicates.map((item) => item.title || item.code).join("\n");
          if (!confirm(`Possible duplicate found:\n${names}\n\nSave anyway?`)) {
            status.textContent = "Cancelled: possible duplicate";
            button.disabled = false;
            return;
          }
          payload.allow_duplicate = true;
          saved = await postJson(editing ? "/update-entry" : "/create-entry", payload);
        }
        if (pdfFile) {
          status.textContent = `Saved ${saved.code}; adding PDF…`;
          await attachPdf(saved.code, pdfFile, editing);
        }
        status.textContent = `${editing ? "Updated" : "Created"} ${saved.code}${pdfFile ? " with a local PDF" : ""}`;
        if (editing) {
          window.setTimeout(() => { location.href = `add.html?edit=${encodeURIComponent(saved.code)}`; }, 500);
        } else {
          entryDrafts.splice(activeDraftIndex, 1);
          if (!entryDrafts.length) entryDrafts.push(blankDraft());
          activeDraftIndex = Math.min(activeDraftIndex, entryDrafts.length - 1);
          renderDraft();
          scheduleDraftPersistence();
          button.disabled = false;
        }
      } catch (error) {
        if (saved && pdfFile) {
          status.textContent = `Saved ${saved.code}, but the PDF was not attached`;
          form.dataset.mode = "edit";
          document.getElementById("entryCode").value = saved.code;
          document.getElementById("entryFormTitle").textContent = `Edit: ${saved.title || saved.code}`;
          document.getElementById("createEntryBtn").textContent = "Save changes";
          document.getElementById("cancelEditBtn").hidden = false;
          document.getElementById("entryPdfHostsContainer").hidden = false;
          document.getElementById("editPdfContainer").hidden = false;
          document.getElementById("entryImportWorkspace").hidden = true;
          history.replaceState({}, "", `add.html?edit=${encodeURIComponent(saved.code)}`);
          alert(`The bibliography entry was saved, but the PDF was not attached. You can correct the file selection and try again.\n\n${error.message}`);
        } else {
          status.textContent = "Save failed";
          alert(error.message);
        }
        button.disabled = false;
      }
    });

    document.getElementById("mergeEntriesBtn").addEventListener("click", async () => {
      const source = document.getElementById("mergeSource").value.trim();
      const target = document.getElementById("mergeTarget").value.trim();
      const sourceRow = rows.find((row) => row.code === source);
      const targetRow = rows.find((row) => row.code === target);
      if (!sourceRow || !targetRow || source === target) { alert("Choose two different entries from the suggestions."); return; }
      if (!confirm(`Merge “${sourceRow.title}” into “${targetRow.title}”? The second entry will be kept.`)) return;
      try {
        await postJson("/merge-entries", { source, target });
        document.getElementById("mergeEntriesStatus").textContent = "Merged successfully";
        window.setTimeout(() => location.reload(), 500);
      } catch (error) { document.getElementById("mergeEntriesStatus").textContent = "Merge failed"; alert(error.message); }
    });

    document.getElementById("manageTypeBtn").addEventListener("click", async () => {
      const source = document.getElementById("manageTypeSource").value;
      const target = document.getElementById("manageTypeTarget").value.trim();
      if (!source || !target) { alert("Choose an existing type and its destination type."); return; }
      if (!confirm(`Change every “${source}” entry to “${target}”?`)) return;
      try {
        const result = await postJson("/manage-type", { action: "merge", source, target });
        document.getElementById("manageTypeStatus").textContent = `Updated ${result.updated} entries`;
        window.setTimeout(() => location.reload(), 500);
      } catch (error) { document.getElementById("manageTypeStatus").textContent = "Change failed"; alert(error.message); }
    });

    document.getElementById("manageKeywordBtn").addEventListener("click", async () => {
      const source = document.getElementById("manageKeywordSource").value;
      const target = document.getElementById("manageKeywordTarget").value.trim();
      const status = document.getElementById("manageKeywordStatus");
      if (!source || !target) { alert("Choose an existing keyword and its destination keyword."); return; }
      if (!confirm(`Change every “${source}” keyword to “${target}”?`)) return;
      try {
        const result = await postJson("/manage-my-keyword", { action: "merge", source, target });
        status.textContent = `Updated ${result.updated} entries`;
        window.setTimeout(() => location.reload(), 500);
      } catch (error) { status.textContent = "Change failed"; alert(error.message); }
    });

    document.getElementById("deleteKeywordBtn").addEventListener("click", async () => {
      const source = document.getElementById("manageKeywordSource").value;
      const status = document.getElementById("manageKeywordStatus");
      if (!source) { alert("Choose an existing keyword."); return; }
      if (!confirm(`Delete “${source}” from every entry and the automatic tagging rules?`)) return;
      try {
        const result = await postJson("/manage-my-keyword", { action: "delete", source });
        status.textContent = `Removed from ${result.updated} entries`;
        window.setTimeout(() => location.reload(), 500);
      } catch (error) { status.textContent = "Delete failed"; alert(error.message); }
    });
  } catch (error) {
    document.getElementById("entryStatus").textContent = error.message;
  }
}

init();
