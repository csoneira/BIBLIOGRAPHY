function parseCsv(text) {
  const rows = [];
  let current = [];
  let value = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    const next = text[i + 1];

    if (char === '"') {
      if (inQuotes && next === '"') {
        value += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === ',' && !inQuotes) {
      current.push(value);
      value = "";
      continue;
    }

    if ((char === '\n' || char === '\r') && !inQuotes) {
      if (value || current.length) {
        current.push(value);
        rows.push(current);
        current = [];
        value = "";
      }
      continue;
    }

    value += char;
  }

  if (value || current.length) {
    current.push(value);
    rows.push(current);
  }

  return rows;
}

window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    window.location.reload();
  }
});

function toRows(csvText) {
  const parsed = parseCsv(csvText);
  if (parsed.length === 0) {
    return [];
  }
  const headers = parsed[0].map((h) => h.trim());
  return parsed.slice(1).map((row) => {
    const entry = {};
    headers.forEach((header, index) => {
      entry[header] = (row[index] || "").trim();
    });
    return entry;
  });
}

function toAbstractMap(rows) {
  const map = {};
  rows.forEach((row) => {
    const code = (row.code || "").trim();
    if (!code) {
      return;
    }
    map[code] = (row.abstract || "").trim();
  });
  return map;
}

function isIsoDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test((value || "").trim());
}

function publicationDateRange(row) {
  const publicationDate = (row.publication_date || "").trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(publicationDate)) {
    return { start: publicationDate, end: publicationDate };
  }
  if (/^\d{4}-\d{2}$/.test(publicationDate)) {
    const [year, month] = publicationDate.split("-").map(Number);
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return {
      start: `${publicationDate}-01`,
      end: `${publicationDate}-${String(lastDay).padStart(2, "0")}`,
    };
  }
  const year = (row.year || "").trim();
  if (/^\d{4}$/.test(year)) {
    return { start: `${year}-01-01`, end: `${year}-12-31` };
  }
  return null;
}

function applyFilters(rows, filters) {
  return rows.filter((row) => {
    const publicationRange = publicationDateRange(row);
    const typeValue = (row.type || "").toLowerCase();
    const starValue = (row.star || "").toString();
    const unreadValue = (row.unread || "").toString();
    const addedAt = (row.added_at || "").trim();
    if (filters.fromDate && (!publicationRange || publicationRange.end < filters.fromDate)) {
      return false;
    }
    if (filters.toDate && (!publicationRange || publicationRange.start > filters.toDate)) {
      return false;
    }
    if (filters.types.length && !filters.types.includes(typeValue)) {
      return false;
    }
    if (filters.title && !(row.title || "").toLowerCase().includes(filters.title)) {
      return false;
    }
    if (filters.starOnly && starValue !== "1") {
      return false;
    }
    if (filters.unreadOnly && unreadValue !== "1") {
      return false;
    }
    if (filters.location && row.pdf_status !== filters.location) {
      return false;
    }
    if (filters.hideRecent && row.last_viewed) {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - 30);
      const cutoffText = cutoff.toISOString().slice(0, 10);
      if (row.last_viewed >= cutoffText) {
        return false;
      }
    }
    if (filters.journal && !(row.journal || "").toLowerCase().includes(filters.journal)) {
      return false;
    }
    if (filters.keyword && !(row.keywords || "").toLowerCase().includes(filters.keyword)) {
      return false;
    }
    if (filters.myKeyword && !(row.my_keywords || "").toLowerCase().includes(filters.myKeyword)) {
      return false;
    }
    if (filters.abstract && !(row.abstract || "").toLowerCase().includes(filters.abstract)) {
      return false;
    }
    if (filters.addedFrom) {
      if (!isIsoDate(addedAt) || addedAt < filters.addedFrom) {
        return false;
      }
    }
    if (filters.addedTo) {
      if (!isIsoDate(addedAt) || addedAt > filters.addedTo) {
        return false;
      }
    }
    return true;
  });
}

function sortByAddedDate(rows, direction) {
  if (!direction) {
    return rows;
  }

  const withDate = [];
  const withoutDate = [];
  rows.forEach((row) => {
    if (isIsoDate(row.added_at || "")) {
      withDate.push(row);
    } else {
      withoutDate.push(row);
    }
  });

  withDate.sort((a, b) => (a.added_at || "").localeCompare(b.added_at || ""));
  if (direction === "desc") {
    withDate.reverse();
  }
  return withDate.concat(withoutDate);
}

function publicationSortKey(row) {
  const publicationDate = (row.publication_date || "").trim();
  if (/^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/.test(publicationDate)) {
    return publicationDate;
  }
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(publicationDate)) {
    return `${publicationDate}-00`;
  }
  const year = (row.year || "").trim();
  return /^\d{4}$/.test(year) ? `${year}-00-00` : null;
}

function sortByPublicationDate(rows, direction) {
  if (!direction) {
    return rows;
  }

  const withYear = [];
  const withoutYear = [];
  rows.forEach((row) => {
    if (publicationSortKey(row) === null) {
      withoutYear.push(row);
    } else {
      withYear.push(row);
    }
  });

  withYear.sort((a, b) => publicationSortKey(a).localeCompare(publicationSortKey(b)));
  if (direction === "desc") {
    withYear.reverse();
  }
  return withYear.concat(withoutYear);
}

function sortRows(rows, sortMode) {
  if (!sortMode) {
    return rows;
  }

  if (sortMode === "random") {
    const shuffled = [...rows];
    for (let index = shuffled.length - 1; index > 0; index -= 1) {
      const randomIndex = Math.floor(Math.random() * (index + 1));
      [shuffled[index], shuffled[randomIndex]] = [shuffled[randomIndex], shuffled[index]];
    }
    return shuffled;
  }

  // Backward compatibility for older saved lists that stored only asc/desc.
  if (sortMode === "asc" || sortMode === "desc") {
    return sortByAddedDate(rows, sortMode);
  }
  if (sortMode === "added_asc") {
    return sortByAddedDate(rows, "asc");
  }
  if (sortMode === "added_desc") {
    return sortByAddedDate(rows, "desc");
  }
  if (sortMode === "publication_asc") {
    return sortByPublicationDate(rows, "asc");
  }
  if (sortMode === "publication_desc") {
    return sortByPublicationDate(rows, "desc");
  }
  return rows;
}

function applySavedList(rows, savedList) {
  const codes = new Set((savedList.codes || []).filter(Boolean));
  if (!codes.size) {
    return [];
  }
  return rows.filter((row) => codes.has(row.code));
}

function renderResults(rows) {
  const container = document.getElementById("results");
  container.innerHTML = "";

  if (rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "card";
    empty.textContent = "No matches. Try relaxing the filters.";
    container.appendChild(empty);
    return;
  }

  rows.forEach((row) => {
    const card = document.createElement("div");
    card.className = "card";

    const header = document.createElement("div");
    header.className = "card-header";

    const title = document.createElement("h3");
    const link = document.createElement("a");
    link.textContent = row.title || row.code || "Untitled";
    link.href = `../PDFs/${row.code}.pdf`;
    link.target = "_blank";
    link.rel = "noopener";
    link.addEventListener("click", async (event) => {
      // Keep modified clicks working normally for open-in-new-tab behavior.
      if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      markViewedOnServer(row.code).catch(() => {});
      try {
        await openPdfOnServer(row.code);
      } catch (err) {
        if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
          if (row.pdf_status === "remote") {
            alert(`This PDF is recorded on ${row.pdf_hosts}, but is not available on this computer.`);
          } else if (row.pdf_status === "not_added") {
            alert("No PDF has been added for this entry yet.");
          } else {
            alert("The local PDF could not be opened.");
          }
        } else {
          window.open(link.href, "_blank", "noopener");
        }
      }
    });
    title.appendChild(link);
    header.appendChild(title);

    const star = document.createElement("button");
    star.className = "star";
    star.textContent = row.star === "1" ? "★" : "☆";
    star.title = "Toggle star";
    star.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const next = row.star === "1" ? "" : "1";
      try {
        await setStarOnServer(row.code, next);
        row.star = next;
        star.textContent = row.star === "1" ? "★" : "☆";
      } catch (err) {
        alert("Failed to save star. Start the viewer server with: python3 CODE/viewer_server.py");
      }
    });
    const unread = document.createElement("button");
    unread.className = "unread";
    unread.textContent = row.unread === "1" ? "Unread" : "Read";
    unread.title = "Toggle unread";
    unread.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      const next = row.unread === "1" ? "" : "1";
      try {
        await setUnreadOnServer(row.code, next);
        row.unread = next;
        unread.textContent = row.unread === "1" ? "Unread" : "Read";
      } catch (err) {
        alert("Failed to save unread. Start the viewer server with: python3 CODE/viewer_server.py");
      }
    });

    const actions = document.createElement("div");
    actions.className = "card-actions";
    const location = document.createElement("span");
    const storedHosts = (row.pdf_hosts || "").trim();
    if (row.pdf_status === "local") {
      location.className = "location-badge local";
      location.textContent = "Local";
      location.title = storedHosts ? `Recorded on: ${storedHosts}` : "Available locally";
    } else if (row.pdf_status === "remote") {
      location.className = "location-badge remote";
      location.textContent = "Remote";
      location.title = `Recorded on: ${storedHosts}`;
    } else {
      location.className = "location-badge not-added";
      location.textContent = "Not added";
      location.title = "No PDF has been added on any recorded computer";
    }
    actions.appendChild(unread);
    actions.appendChild(star);
    actions.appendChild(location);
    header.appendChild(actions);

    card.appendChild(header);

    const meta = document.createElement("div");
    meta.className = "meta";
    const addedLabel = row.added_at ? `added ${row.added_at}` : "";
    const viewedLabel = row.last_viewed ? `viewed ${row.last_viewed}` : "never viewed";
    const publicationLabel = row.publication_date || row.year;
    meta.textContent = [row.author, row.journal, publicationLabel, addedLabel, viewedLabel]
      .filter(Boolean)
      .join(" · ");
    card.appendChild(meta);

    const code = document.createElement("div");
    code.className = "code";
    code.textContent = row.code || "";
    card.appendChild(code);

    if (row.code) {
      const manageActions = document.createElement("div");
      manageActions.className = "actions";

      const editButton = document.createElement("button");
      editButton.className = "secondary compact";
      editButton.textContent = "Edit";
      editButton.addEventListener("click", () => startEditingEntry(row));
      manageActions.appendChild(editButton);

      if (!row.is_local) {
        const attachButton = document.createElement("button");
        attachButton.className = "secondary compact";
        attachButton.textContent = "Attach PDF";
        attachButton.addEventListener("click", () => {
          const upload = document.getElementById("pdfUpload");
          upload.dataset.code = row.code;
          upload.value = "";
          upload.click();
        });
        manageActions.appendChild(attachButton);
      }

      const deleteButton = document.createElement("button");
      deleteButton.className = "danger compact";
      deleteButton.textContent = "Delete";
      deleteButton.addEventListener("click", async () => {
        const message = row.is_local
          ? "Delete this entry? Its local PDF will be moved to the recoverable .trash folder."
          : "Delete this bibliography entry?";
        if (!confirm(message)) {
          return;
        }
        try {
          await postJson("/delete-entry", { code: row.code });
          window.location.reload();
        } catch (err) {
          alert(err.message);
        }
      });
      manageActions.appendChild(deleteButton);
      card.appendChild(manageActions);
    }

    const abstractText = (row.abstract || "").trim();
    const abstractToggle = document.createElement("button");
    abstractToggle.className = "toggle-abstract";
    abstractToggle.textContent = abstractText ? "Show abstract" : "No abstract";
    abstractToggle.disabled = !abstractText;

    const abstract = document.createElement("div");
    abstract.className = "abstract";
    abstract.textContent = abstractText;
    abstract.style.display = "none";

    abstractToggle.addEventListener("click", () => {
      const hidden = abstract.style.display === "none";
      abstract.style.display = hidden ? "" : "none";
      abstractToggle.textContent = hidden ? "Hide abstract" : "Show abstract";
    });

    card.appendChild(abstractToggle);
    card.appendChild(abstract);

    const notesToggle = document.createElement("button");
    notesToggle.className = "toggle-notes";

    const notesSection = document.createElement("div");
    notesSection.className = "notes-section";
    notesSection.style.display = "none";

    const notesLabel = document.createElement("div");
    notesLabel.className = "notes-label";
    notesLabel.textContent = "Notes";

    const notesInput = document.createElement("textarea");
    notesInput.className = "notes-editor";
    notesInput.placeholder = "Write notes for this paper...";
    notesInput.value = row.notes || "";

    const notesControls = document.createElement("div");
    notesControls.className = "notes-controls";

    const notesSave = document.createElement("button");
    notesSave.className = "notes-save";
    notesSave.textContent = "Save notes";

    const notesStatus = document.createElement("span");
    notesStatus.className = "notes-status";

    const updateNotesToggleText = () => {
      const hidden = notesSection.style.display === "none";
      if (!hidden) {
        notesToggle.textContent = "Hide notes";
        return;
      }
      notesToggle.textContent = notesInput.value.trim() ? "Show notes" : "Add notes";
    };

    notesToggle.addEventListener("click", () => {
      const hidden = notesSection.style.display === "none";
      notesSection.style.display = hidden ? "" : "none";
      updateNotesToggleText();
    });

    notesInput.addEventListener("input", () => {
      notesStatus.textContent = "Unsaved changes";
    });

    notesSave.addEventListener("click", async () => {
      const nextNotes = notesInput.value;
      notesSave.disabled = true;
      notesSave.textContent = "Saving...";
      try {
        await saveNotesOnServer(row.code, nextNotes);
        row.notes = nextNotes;
        notesStatus.textContent = "Saved";
        updateNotesToggleText();
      } catch (err) {
        notesStatus.textContent = "Save failed";
        alert("Failed to save notes. Start the viewer server with: python3 CODE/viewer_server.py");
      } finally {
        notesSave.disabled = false;
        notesSave.textContent = "Save notes";
      }
    });

    notesControls.appendChild(notesSave);
    notesControls.appendChild(notesStatus);
    notesSection.appendChild(notesLabel);
    notesSection.appendChild(notesInput);
    notesSection.appendChild(notesControls);
    updateNotesToggleText();
    card.appendChild(notesToggle);
    card.appendChild(notesSection);

    container.appendChild(card);
  });
}

function getFilters() {
  return {
    fromDate: document.getElementById("fromDate").value,
    toDate: document.getElementById("toDate").value,
    types: [...document.querySelectorAll("#typeFilterOptions input:checked")]
      .map((input) => input.value),
    title: document.getElementById("titleFilter").value.trim().toLowerCase(),
    starOnly: document.getElementById("starOnly").checked,
    unreadOnly: document.getElementById("unreadOnly").checked,
    hideRecent: document.getElementById("hideRecent").checked,
    location: document.getElementById("locationFilter").value,
    journal: document.getElementById("journal").value.trim().toLowerCase(),
    keyword: document.getElementById("keyword").value.trim().toLowerCase(),
    myKeyword: document.getElementById("myKeyword").value.trim().toLowerCase(),
    abstract: document.getElementById("abstractFilter").value.trim().toLowerCase(),
    addedFrom: document.getElementById("addedFrom").value.trim(),
    addedTo: document.getElementById("addedTo").value.trim(),
    addedSort: document.getElementById("addedSort").value,
  };
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

async function markViewedOnServer(code) {
  return postJson("/mark-viewed", { code });
}

async function updateEntryOnServer(payload) {
  return postJson("/update-entry", payload);
}

async function attachPdfOnServer(code, file) {
  const response = await fetch(`/attach-pdf?code=${encodeURIComponent(code)}`, {
    method: "POST",
    headers: { "Content-Type": "application/pdf" },
    body: file,
  });
  if (!response.ok) {
    throw new Error(`PDF attachment failed (${response.status}).`);
  }
  return response.json();
}

async function setStarOnServer(code, star) {
  const response = await fetch("/toggle-star", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, star }),
  });
  if (!response.ok) {
    throw new Error("Failed to save star.");
  }
  return response.json();
}

async function setUnreadOnServer(code, unread) {
  const response = await fetch("/toggle-unread", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, unread }),
  });
  if (!response.ok) {
    throw new Error("Failed to save unread.");
  }
  return response.json();
}

async function openPdfOnServer(code) {
  const response = await fetch("/open-pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error("Failed to open local PDF.");
  }
  return response.json();
}

async function saveNotesOnServer(code, notes) {
  const response = await fetch("/save-notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, notes }),
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error("Failed to save notes.");
  }
  return response.json();
}

async function saveListToServer(name, rows, filters) {
  const payload = {
    name,
    filters,
    codes: rows.map((row) => row.code).filter(Boolean),
  };
  const response = await fetch("/save-list", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error("Server did not accept the list.");
  }
  return response.json();
}

async function createEntryOnServer(payload) {
  return postJson("/create-entry", payload);
}

function setupEntryTypeOptions(rows) {
  const select = document.getElementById("entryType");
  const types = catalogTypes(rows);
  select.innerHTML = "";
  types.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    select.appendChild(option);
  });
  const addOption = document.createElement("option");
  addOption.value = "__new__";
  addOption.textContent = "+ Add new type…";
  select.appendChild(addOption);
  select.value = types.includes("article") ? "article" : (types[0] || "__new__");

  const container = document.getElementById("entryNewTypeContainer");
  const input = document.getElementById("entryNewType");
  const updateNewTypeVisibility = () => {
    const adding = select.value === "__new__";
    container.hidden = !adding;
    input.required = adding;
    if (adding) {
      input.focus();
    }
  };
  select.addEventListener("change", updateNewTypeVisibility);
  updateNewTypeVisibility();
}

function catalogTypes(rows) {
  return [...new Set(rows.map((row) => (row.type || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b));
}

function setupFilterTypeOptions(rows) {
  const container = document.getElementById("typeFilterOptions");
  container.innerHTML = "";
  catalogTypes(rows).forEach((type, index) => {
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = type.toLowerCase();
    checkbox.id = `typeFilter-${index}`;
    label.htmlFor = checkbox.id;
    label.appendChild(checkbox);
    label.appendChild(document.createTextNode(type));
    container.appendChild(label);
  });
}

function setupTypeManager(rows) {
  const types = catalogTypes(rows);
  const source = document.getElementById("manageTypeSource");
  const datalist = document.getElementById("knownTypes");
  source.innerHTML = "";
  datalist.innerHTML = "";
  types.forEach((type) => {
    const option = document.createElement("option");
    option.value = type;
    option.textContent = type;
    source.appendChild(option);
    const suggestion = document.createElement("option");
    suggestion.value = type;
    datalist.appendChild(suggestion);
  });
}

function setupPublicationDateInputs() {
  const month = document.getElementById("entryPublicationMonth");
  const day = document.getElementById("entryPublicationDay");
  const updateDayState = () => {
    day.disabled = !month.value;
    if (day.disabled) {
      day.value = "";
    }
  };
  month.addEventListener("input", updateDayState);
  updateDayState();
}

function setPublicationDateInputs(value) {
  const parts = (value || "").split("-");
  const month = document.getElementById("entryPublicationMonth");
  const day = document.getElementById("entryPublicationDay");
  month.value = parts.length >= 2 ? `${parts[0]}-${parts[1]}` : "";
  day.disabled = !month.value;
  day.value = parts.length === 3 ? String(parseInt(parts[2], 10)) : "";
}

function startEditingEntry(row) {
  const form = document.getElementById("entryForm");
  form.dataset.mode = "edit";
  form.dataset.legacyYear = row.publication_date ? "" : (row.year || "");
  document.getElementById("entryCode").value = row.code;
  document.getElementById("entryTitle").value = row.title || "";
  setPublicationDateInputs(row.publication_date || "");
  document.getElementById("entryType").value = row.type || "article";
  document.getElementById("entryNewTypeContainer").hidden = true;
  document.getElementById("entryNewType").required = false;
  document.getElementById("entryAuthor").value = row.author || "";
  document.getElementById("entryJournal").value = row.journal || "";
  document.getElementById("entryDoi").value = row.doi || "";
  document.getElementById("entryKeywords").value = row.keywords || "";
  document.getElementById("entryMyKeywords").value = row.my_keywords || "";
  document.getElementById("entryNotes").value = row.notes || "";
  document.getElementById("entryUnread").checked = row.unread === "1";
  document.getElementById("entryStar").checked = row.star === "1";
  document.getElementById("entryPdfHosts").value = row.pdf_hosts || "";
  document.getElementById("entryPdfHostsContainer").hidden = false;
  document.getElementById("cancelEditBtn").hidden = false;
  document.getElementById("entryFormTitle").textContent = `Edit: ${row.title || row.code}`;
  document.getElementById("createEntryBtn").textContent = "Save changes";
  document.getElementById("entryStatus").textContent = "";
  const panel = form.closest("details");
  panel.open = true;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function resetEntryForm() {
  const form = document.getElementById("entryForm");
  form.reset();
  form.dataset.mode = "create";
  form.dataset.legacyYear = "";
  document.getElementById("entryCode").value = "";
  document.getElementById("entryType").value = [...document.getElementById("entryType").options]
    .some((option) => option.value === "article") ? "article" : document.getElementById("entryType").value;
  setPublicationDateInputs("");
  document.getElementById("entryPdfHostsContainer").hidden = true;
  document.getElementById("entryNewTypeContainer").hidden = true;
  document.getElementById("entryNewType").required = false;
  document.getElementById("cancelEditBtn").hidden = true;
  document.getElementById("entryFormTitle").textContent = "Create a metadata-only entry";
  document.getElementById("createEntryBtn").textContent = "Create entry";
  document.getElementById("entryStatus").textContent = "";
}

function updateDashboard(rows) {
  document.getElementById("countTotal").textContent = rows.length;
  document.getElementById("countLocal").textContent = rows.filter((row) => row.pdf_status === "local").length;
  document.getElementById("countRemote").textContent = rows.filter((row) => row.pdf_status === "remote").length;
  document.getElementById("countNotAdded").textContent = rows.filter((row) => row.pdf_status === "not_added").length;
  document.getElementById("countMultiple").textContent = rows.filter(
    (row) => (row.pdf_hosts || "").split(";").filter((host) => host.trim()).length > 1,
  ).length;
}

function setFilters(filters = {}) {
  document.getElementById("fromDate").value = filters.fromDate || (filters.fromYear ? `${filters.fromYear}-01-01` : "");
  document.getElementById("toDate").value = filters.toDate || (filters.toYear ? `${filters.toYear}-12-31` : "");
  const selectedTypes = new Set(filters.types || (filters.type ? [filters.type] : []));
  document.querySelectorAll("#typeFilterOptions input").forEach((input) => {
    input.checked = selectedTypes.has(input.value);
  });
  document.getElementById("titleFilter").value = filters.title || "";
  document.getElementById("starOnly").checked = Boolean(filters.starOnly);
  document.getElementById("unreadOnly").checked = Boolean(filters.unreadOnly);
  document.getElementById("hideRecent").checked = Boolean(filters.hideRecent);
  document.getElementById("locationFilter").value = filters.location || "";
  document.getElementById("journal").value = filters.journal || "";
  document.getElementById("keyword").value = filters.keyword || "";
  document.getElementById("myKeyword").value = filters.myKeyword || "";
  document.getElementById("abstractFilter").value = filters.abstract || "";
  document.getElementById("addedFrom").value = filters.addedFrom || "";
  document.getElementById("addedTo").value = filters.addedTo || "";
  document.getElementById("addedSort").value = filters.addedSort || "";
}

function freshUrl(url) {
  const joiner = url.includes("?") ? "&" : "?";
  return `${url}${joiner}t=${Date.now()}`;
}

async function loadData() {
  const metadataResponse = await fetch(freshUrl("../METADATA/metadata.csv"), {
    cache: "no-store",
  });
  if (!metadataResponse.ok) {
    throw new Error("metadata.csv not found. Run python3 CODE/bib.py scan.");
  }
  const text = await metadataResponse.text();
  const rows = toRows(text);
  const [abstractsByCode, localPdfCodes] = await Promise.all([
    loadAbstractsMap(),
    loadLocalPdfCodes(),
  ]);
  rows.forEach((row) => {
    row.abstract = abstractsByCode[row.code] || "";
    row.is_local = localPdfCodes.has(row.code);
    row.pdf_status = row.is_local
      ? "local"
      : (row.pdf_hosts || "").trim()
        ? "remote"
        : "not_added";
  });
  return rows;
}

async function loadLocalPdfCodes() {
  try {
    const response = await fetch(freshUrl("/pdf-status"), { cache: "no-store" });
    if (!response.ok) {
      return new Set();
    }
    const payload = await response.json();
    return new Set(Array.isArray(payload.local_codes) ? payload.local_codes : []);
  } catch (err) {
    return new Set();
  }
}

async function loadAbstractsMap() {
  try {
    const response = await fetch(freshUrl("/abstracts"), { cache: "no-store" });
    if (response.ok) {
      const payload = await response.json();
      if (payload && typeof payload === "object") {
        if (payload.abstracts && typeof payload.abstracts === "object") {
          return payload.abstracts;
        }
        return payload;
      }
    }
  } catch (err) {
    // Fall through to local CSV loading.
  }

  try {
    const response = await fetch(freshUrl("../METADATA/abstracts.csv"), {
      cache: "no-store",
    });
    if (!response.ok) {
      return {};
    }
    const text = await response.text();
    return toAbstractMap(toRows(text));
  } catch (err) {
    return {};
  }
}

async function loadSavedLists() {
  const select = document.getElementById("savedList");
  select.innerHTML = "";
  const defaultOption = document.createElement("option");
  defaultOption.value = "";
  defaultOption.textContent = "Select saved list";
  select.appendChild(defaultOption);

  try {
    const response = await fetch(freshUrl("/saved-lists"), { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Saved lists not available.");
    }
    const lists = await response.json();
    lists.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    lists.forEach((list) => {
      const option = document.createElement("option");
      option.value = list.filename;
      option.textContent = list.name || list.filename;
      select.appendChild(option);
    });
    return lists;
  } catch (err) {
    defaultOption.textContent = "Saved lists unavailable (use viewer_server.py)";
    select.disabled = true;
    return [];
  }
}

async function init() {
  try {
    const rows = await loadData();
    const savedLists = await loadSavedLists();
    let filteredRows = rows;
    setupFilterTypeOptions(rows);
    setupEntryTypeOptions(rows);
    setupTypeManager(rows);
    setupPublicationDateInputs();
    resetEntryForm();
    updateDashboard(rows);
    renderResults(rows);

    document.getElementById("applyBtn").addEventListener("click", () => {
      const filters = getFilters();
      filteredRows = sortRows(applyFilters(rows, filters), filters.addedSort);
      renderResults(filteredRows);
    });

    document.getElementById("resetBtn").addEventListener("click", () => {
      setFilters();
      document.getElementById("savedList").value = "";
      filteredRows = rows;
      renderResults(rows);
    });

    document.getElementById("loadListBtn").addEventListener("click", () => {
      const selection = document.getElementById("savedList").value;
      if (!selection) {
        alert("Pick a saved list first.");
        return;
      }
      const selectedList = savedLists.find((list) => list.filename === selection);
      if (!selectedList) {
        alert("Saved list not found. Refresh the page.");
        return;
      }
      setFilters(selectedList.filters || {});
      const restoredFilters = getFilters();
      filteredRows = sortRows(
        applyFilters(applySavedList(rows, selectedList), restoredFilters),
        restoredFilters.addedSort,
      );
      renderResults(filteredRows);
    });

    document.getElementById("surpriseBtn").addEventListener("click", () => {
      const candidates = applyFilters(rows, getFilters());
      if (!candidates.length) {
        alert("No entries match the current filters.");
        return;
      }
      const choice = candidates[Math.floor(Math.random() * candidates.length)];
      filteredRows = [choice];
      renderResults(filteredRows);
    });

    document.getElementById("undoBtn").addEventListener("click", async () => {
      if (!confirm("Undo the most recent change made through the viewer?")) {
        return;
      }
      try {
        const result = await postJson("/undo-last-change", {});
        alert(`Undid: ${result.action}`);
        window.location.reload();
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("cancelEditBtn").addEventListener("click", resetEntryForm);

    document.getElementById("pdfUpload").addEventListener("change", async (event) => {
      const file = event.target.files[0];
      const code = event.target.dataset.code;
      if (!file || !code) {
        return;
      }
      try {
        await attachPdfOnServer(code, file);
        alert("PDF attached to the existing entry.");
        window.location.reload();
      } catch (err) {
        alert(err.message);
      }
    });

    document.getElementById("manageTypeBtn").addEventListener("click", async () => {
      const source = document.getElementById("manageTypeSource").value;
      const target = document.getElementById("manageTypeTarget").value.trim();
      const status = document.getElementById("manageTypeStatus");
      if (!source || !target) {
        alert("Choose an existing type and provide its new or merged type.");
        return;
      }
      if (!confirm(`Change every “${source}” entry to “${target}”?`)) {
        return;
      }
      try {
        const result = await postJson("/manage-type", { action: "merge", source, target });
        status.textContent = `Updated ${result.updated} entries`;
        window.setTimeout(() => window.location.reload(), 500);
      } catch (err) {
        status.textContent = "Change failed";
        alert(err.message);
      }
    });

    document.getElementById("saveBtn").addEventListener("click", async () => {
      if (!filteredRows.length) {
        alert("No results to save.");
        return;
      }
      const name = prompt("Name for this list (saved to download):");
      if (!name) {
        return;
      }
      try {
        const result = await saveListToServer(name.trim(), filteredRows, getFilters());
        alert(`Saved to ${result.path}`);
      } catch (err) {
        alert("Save failed. Start the viewer server with: python3 CODE/viewer_server.py");
      }
    });

    document.getElementById("entryForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = document.getElementById("createEntryBtn");
      const status = document.getElementById("entryStatus");
      const selectedType = document.getElementById("entryType").value;
      const publicationMonth = document.getElementById("entryPublicationMonth").value;
      const publicationDay = document.getElementById("entryPublicationDay").value;
      const publicationDate = publicationMonth && publicationDay
        ? `${publicationMonth}-${publicationDay.padStart(2, "0")}`
        : publicationMonth;
      const payload = {
        code: document.getElementById("entryCode").value,
        title: document.getElementById("entryTitle").value,
        publication_date: publicationDate,
        year: document.getElementById("entryForm").dataset.legacyYear || "",
        type: selectedType === "__new__"
          ? document.getElementById("entryNewType").value
          : selectedType,
        author: document.getElementById("entryAuthor").value,
        journal: document.getElementById("entryJournal").value,
        doi: document.getElementById("entryDoi").value,
        keywords: document.getElementById("entryKeywords").value,
        my_keywords: document.getElementById("entryMyKeywords").value,
        notes: document.getElementById("entryNotes").value,
        unread: document.getElementById("entryUnread").checked,
        star: document.getElementById("entryStar").checked,
      };
      if (document.getElementById("entryForm").dataset.mode === "edit") {
        payload.pdf_hosts = document.getElementById("entryPdfHosts").value;
      }
      button.disabled = true;
      status.textContent = "Saving...";
      try {
        const editing = document.getElementById("entryForm").dataset.mode === "edit";
        let saved;
        try {
          saved = editing
            ? await updateEntryOnServer(payload)
            : await createEntryOnServer(payload);
        } catch (err) {
          if (err.status !== 409 || !err.duplicates.length) {
            throw err;
          }
          const duplicateTitles = err.duplicates.map((item) => item.title || item.code).join("\n");
          if (!confirm(`Possible duplicate found:\n${duplicateTitles}\n\nSave anyway?`)) {
            status.textContent = "Cancelled: possible duplicate";
            button.disabled = false;
            return;
          }
          payload.allow_duplicate = true;
          saved = editing
            ? await updateEntryOnServer(payload)
            : await createEntryOnServer(payload);
        }
        status.textContent = `${editing ? "Updated" : "Created"} ${saved.code}`;
        window.setTimeout(() => window.location.reload(), 500);
      } catch (err) {
        status.textContent = "Save failed";
        alert(err.message || "Failed to save the entry. Check the required fields and keep the viewer server running.");
        button.disabled = false;
      }
    });
  } catch (err) {
    renderResults([{ title: err.message, code: "" }]);
  }
}

init();
