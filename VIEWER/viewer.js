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

function applyFilters(rows, filters) {
  return rows.filter((row) => {
    const year = parseInt(row.year || "0", 10);
    const typeValue = (row.type || "").toLowerCase();
    if (filters.fromYear && year < filters.fromYear) {
      return false;
    }
    if (filters.toYear && year > filters.toYear) {
      return false;
    }
    if (filters.type && !typeValue.includes(filters.type)) {
      return false;
    }
    if (filters.journal && !row.journal.toLowerCase().includes(filters.journal)) {
      return false;
    }
    if (filters.keyword && !row.keywords.toLowerCase().includes(filters.keyword)) {
      return false;
    }
    if (filters.myKeyword && !row.my_keywords.toLowerCase().includes(filters.myKeyword)) {
      return false;
    }
    return true;
  });
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

    const title = document.createElement("h3");
    title.textContent = row.title || row.code || "Untitled";
    card.appendChild(title);

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = [row.author, row.journal, row.year]
      .filter(Boolean)
      .join(" · ");
    card.appendChild(meta);

    const code = document.createElement("div");
    code.className = "code";
    code.textContent = row.code || "";
    card.appendChild(code);

    container.appendChild(card);
  });
}

function getFilters() {
  return {
    fromYear: parseInt(document.getElementById("fromYear").value, 10) || null,
    toYear: parseInt(document.getElementById("toYear").value, 10) || null,
    type: document.getElementById("typeFilter").value.trim().toLowerCase(),
    journal: document.getElementById("journal").value.trim().toLowerCase(),
    keyword: document.getElementById("keyword").value.trim().toLowerCase(),
    myKeyword: document.getElementById("myKeyword").value.trim().toLowerCase(),
  };
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
  const response = await fetch("../METADATA/metadata.csv");
  if (!response.ok) {
    throw new Error("metadata.csv not found. Run python3 CODE/bib.py scan.");
  }
  const text = await response.text();
  return toRows(text);
}

async function init() {
  try {
    const rows = await loadData();
    let filteredRows = rows;
    renderResults(rows);

    document.getElementById("applyBtn").addEventListener("click", () => {
      const filters = getFilters();
      filteredRows = applyFilters(rows, filters);
      renderResults(filteredRows);
    });

    document.getElementById("resetBtn").addEventListener("click", () => {
      document.getElementById("fromYear").value = "";
      document.getElementById("toYear").value = "";
      document.getElementById("typeFilter").value = "";
      document.getElementById("journal").value = "";
      document.getElementById("keyword").value = "";
      document.getElementById("myKeyword").value = "";
      filteredRows = rows;
      renderResults(rows);
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
