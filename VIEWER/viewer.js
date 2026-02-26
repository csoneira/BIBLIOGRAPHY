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

function applyFilters(rows, filters) {
  return rows.filter((row) => {
    const year = parseInt(row.year || "0", 10);
    const typeValue = (row.type || "").toLowerCase();
    const starValue = (row.star || "").toString();
    const unreadValue = (row.unread || "").toString();
    const addedAt = (row.added_at || "").trim();
    if (filters.fromYear && year < filters.fromYear) {
      return false;
    }
    if (filters.toYear && year > filters.toYear) {
      return false;
    }
    if (filters.type && !typeValue.includes(filters.type)) {
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
    link.href = `../${row.file}`;
    link.target = "_blank";
    link.rel = "noopener";
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
        await setStarOnServer(row.file, next);
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
        await setUnreadOnServer(row.file, next);
        row.unread = next;
        unread.textContent = row.unread === "1" ? "Unread" : "Read";
      } catch (err) {
        alert("Failed to save unread. Start the viewer server with: python3 CODE/viewer_server.py");
      }
    });

    const actions = document.createElement("div");
    actions.className = "card-actions";
    actions.appendChild(unread);
    actions.appendChild(star);
    header.appendChild(actions);

    card.appendChild(header);

    const meta = document.createElement("div");
    meta.className = "meta";
    const addedLabel = row.added_at ? `added ${row.added_at}` : "";
    meta.textContent = [row.author, row.journal, row.year, addedLabel]
      .filter(Boolean)
      .join(" · ");
    card.appendChild(meta);

    const code = document.createElement("div");
    code.className = "code";
    code.textContent = row.code || "";
    card.appendChild(code);

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

    container.appendChild(card);
  });
}

function getFilters() {
  return {
    fromYear: parseInt(document.getElementById("fromYear").value, 10) || null,
    toYear: parseInt(document.getElementById("toYear").value, 10) || null,
    type: document.getElementById("typeFilter").value.trim().toLowerCase(),
    title: document.getElementById("titleFilter").value.trim().toLowerCase(),
    starOnly: document.getElementById("starOnly").checked,
    unreadOnly: document.getElementById("unreadOnly").checked,
    journal: document.getElementById("journal").value.trim().toLowerCase(),
    keyword: document.getElementById("keyword").value.trim().toLowerCase(),
    myKeyword: document.getElementById("myKeyword").value.trim().toLowerCase(),
    abstract: document.getElementById("abstractFilter").value.trim().toLowerCase(),
    addedFrom: document.getElementById("addedFrom").value.trim(),
    addedTo: document.getElementById("addedTo").value.trim(),
    addedSort: document.getElementById("addedSort").value,
  };
}

async function setStarOnServer(file, star) {
  const response = await fetch("/toggle-star", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file, star }),
  });
  if (!response.ok) {
    throw new Error("Failed to save star.");
  }
  return response.json();
}

async function setUnreadOnServer(file, unread) {
  const response = await fetch("/toggle-unread", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ file, unread }),
  });
  if (!response.ok) {
    throw new Error("Failed to save unread.");
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

async function loadData() {
  const metadataResponse = await fetch("../METADATA/metadata.csv");
  if (!metadataResponse.ok) {
    throw new Error("metadata.csv not found. Run python3 CODE/bib.py scan.");
  }
  const text = await metadataResponse.text();
  const rows = toRows(text);
  const abstractsByCode = await loadAbstractsMap();
  rows.forEach((row) => {
    row.abstract = abstractsByCode[row.code] || "";
  });
  return rows;
}

async function loadAbstractsMap() {
  try {
    const response = await fetch("/abstracts");
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
    const response = await fetch("../METADATA/abstracts.csv");
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
    const response = await fetch("/saved-lists");
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
    renderResults(rows);

    document.getElementById("applyBtn").addEventListener("click", () => {
      const filters = getFilters();
      filteredRows = sortByAddedDate(applyFilters(rows, filters), filters.addedSort);
      renderResults(filteredRows);
    });

    document.getElementById("resetBtn").addEventListener("click", () => {
      document.getElementById("fromYear").value = "";
      document.getElementById("toYear").value = "";
      document.getElementById("typeFilter").value = "";
      document.getElementById("titleFilter").value = "";
      document.getElementById("starOnly").checked = false;
      document.getElementById("unreadOnly").checked = false;
      document.getElementById("journal").value = "";
      document.getElementById("keyword").value = "";
      document.getElementById("myKeyword").value = "";
      document.getElementById("abstractFilter").value = "";
      document.getElementById("addedFrom").value = "";
      document.getElementById("addedTo").value = "";
      document.getElementById("addedSort").value = "";
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
      filteredRows = applySavedList(rows, selectedList);
      renderResults(filteredRows);
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
  } catch (err) {
    renderResults([{ title: err.message, code: "" }]);
  }
}

init();
