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

async function attachPdf(code, file) {
  const response = await fetch(`/attach-pdf?code=${encodeURIComponent(code)}`, {
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

const DRAFT_FIELDS = ["title", "author", "journal", "doi", "keywords", "my_keywords", "abstract", "notes"];
let entryDrafts = [];
let activeDraftIndex = 0;

function blankDraft() {
  return {
    title: "", publication_date: "", type: "article", author: "", journal: "", doi: "",
    keywords: "", my_keywords: "", abstract: "", notes: "", unread: true, star: false,
    pdfFile: null, sources: ["Manual draft"],
  };
}

function normalizeIdentifier(value) {
  return (value || "").trim().toLowerCase()
    .replace(/^https?:\/\/(?:dx\.)?doi\.org\//, "").replace(/^doi:\s*/, "");
}

function draftIsEmpty(draft) {
  return !draft.pdfFile && !DRAFT_FIELDS.some((field) => (draft[field] || "").trim());
}

function captureDraft() {
  if (!entryDrafts.length || document.getElementById("entryForm").dataset.mode === "edit") return;
  const draft = entryDrafts[activeDraftIndex];
  const month = document.getElementById("entryPublicationMonth").value;
  const day = document.getElementById("entryPublicationDay").value;
  DRAFT_FIELDS.forEach((field) => {
    draft[field] = document.getElementById(`entry${field.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join("")}`).value;
  });
  const selectedType = document.getElementById("entryType").value;
  draft.type = selectedType === "__new__" ? document.getElementById("entryNewType").value : selectedType;
  draft.publication_date = month && day ? `${month}-${day.padStart(2, "0")}` : month;
  draft.unread = document.getElementById("entryUnread").checked;
  draft.star = document.getElementById("entryStar").checked;
}

function renderDraft() {
  const draft = entryDrafts[activeDraftIndex] || blankDraft();
  DRAFT_FIELDS.forEach((field) => {
    document.getElementById(`entry${field.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join("")}`).value = draft[field] || "";
  });
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
  document.getElementById("entryPdf").value = "";
  document.getElementById("draftCounter").textContent = `${activeDraftIndex + 1} / ${entryDrafts.length}`;
  document.getElementById("draftSource").textContent = `${draft.sources.join(" + ")}${draft.pdfFile ? ` · PDF: ${draft.pdfFile.name}` : ""}`;
  document.getElementById("previousDraftBtn").disabled = activeDraftIndex === 0;
  document.getElementById("nextDraftBtn").disabled = activeDraftIndex >= entryDrafts.length - 1;
}

function startDraftQueue() {
  entryDrafts = [blankDraft()];
  activeDraftIndex = 0;
  document.getElementById("entryImportWorkspace").hidden = false;
  renderDraft();
}

function mergeDraft(draft, values, overwrite = false) {
  ["title", "publication_date", "type", "author", "journal", "doi", "keywords", "abstract"].forEach((field) => {
    const value = String(values[field] || "").trim();
    if (value && (overwrite || !String(draft[field] || "").trim())) draft[field] = value;
  });
  if (values.source && !draft.sources.includes(values.source)) draft.sources.push(values.source);
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
  return mergeDraft(draft, values, false);
}

async function lookupIntoDraft(identifier, preferredDraft = null) {
  const item = await postJson("/lookup-reference", { identifier });
  let draft = findDraft({ doi: item.doi || identifier, title: item.title });
  if (!draft) draft = preferredDraft || addDraft({ doi: item.doi || identifier, source: item.source });
  mergeDraft(draft, item, true);
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
  const source = document.getElementById("manageKeywordSource");
  const known = document.getElementById("knownMyKeywords");
  source.innerHTML = "";
  known.innerHTML = "";
  keywords.forEach((keyword) => {
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
  const parts = (value || "").split("-");
  const month = document.getElementById("entryPublicationMonth");
  const day = document.getElementById("entryPublicationDay");
  month.value = parts.length >= 2 ? `${parts[0]}-${parts[1]}` : "";
  day.disabled = !month.value;
  day.value = parts.length === 3 ? String(parseInt(parts[2], 10)) : "";
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
  document.getElementById("entryMyKeywords").value = row.my_keywords || "";
  document.getElementById("entryAbstract").value = row.abstract || "";
  document.getElementById("entryNotes").value = row.notes || "";
  document.getElementById("entryUnread").checked = row.unread === "1";
  document.getElementById("entryStar").checked = row.star === "1";
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

    if (editCode) {
      const row = rows.find((item) => item.code === editCode);
      if (row) editEntry(row);
    }

    document.getElementById("entryPublicationMonth").addEventListener("input", (event) => {
      const day = document.getElementById("entryPublicationDay");
      day.disabled = !event.target.value;
      if (day.disabled) day.value = "";
    });
    document.getElementById("cancelEditBtn").addEventListener("click", () => resetForm(true));

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
        alert(`Local PDFs: ${audit.summary.local}\nChecksums OK: ${audit.summary.ok}\nNot yet recorded: ${audit.summary.unrecorded}\nChanged/mismatched: ${audit.summary.mismatch}${duplicateText}`);
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
      status.textContent = `Added ${files.length} PDF file(s) to the review queue`;
    });

    document.getElementById("entryForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const button = document.getElementById("createEntryBtn");
      const status = document.getElementById("entryStatus");
      const month = document.getElementById("entryPublicationMonth").value;
      const day = document.getElementById("entryPublicationDay").value;
      const selectedType = document.getElementById("entryType").value;
      captureDraft();
      const pdfFile = form.dataset.mode === "edit"
        ? document.getElementById("editPdf").files[0]
        : entryDrafts[activeDraftIndex]?.pdfFile;
      const payload = {
        code: document.getElementById("entryCode").value,
        title: document.getElementById("entryTitle").value,
        publication_date: month && day ? `${month}-${day.padStart(2, "0")}` : month,
        year: form.dataset.legacyYear || "",
        type: selectedType === "__new__" ? document.getElementById("entryNewType").value : selectedType,
        author: document.getElementById("entryAuthor").value,
        journal: document.getElementById("entryJournal").value,
        doi: document.getElementById("entryDoi").value,
        keywords: document.getElementById("entryKeywords").value,
        my_keywords: document.getElementById("entryMyKeywords").value,
        abstract: document.getElementById("entryAbstract").value,
        notes: document.getElementById("entryNotes").value,
        unread: document.getElementById("entryUnread").checked,
        star: document.getElementById("entryStar").checked,
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
          await attachPdf(saved.code, pdfFile);
        }
        status.textContent = `${editing ? "Updated" : "Created"} ${saved.code}${pdfFile ? " with a local PDF" : ""}`;
        if (editing) {
          window.setTimeout(() => { location.href = `add.html?edit=${encodeURIComponent(saved.code)}`; }, 500);
        } else {
          entryDrafts.splice(activeDraftIndex, 1);
          if (!entryDrafts.length) entryDrafts.push(blankDraft());
          activeDraftIndex = Math.min(activeDraftIndex, entryDrafts.length - 1);
          renderDraft();
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
