(function exposeNotesCleanup(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.BibliographyNotes = api;
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const ITEM_START = /^(?:[-*•–—](?:\s+|$)|\d+[.)](?:\s+|$))/;
  const SHORT_LOWER_FRAGMENT = /^([a-zà-öø-ÿ]{1,4})(?=\b)/i;
  const LONG_WORD_END = /([a-zà-öø-ÿ]{5,})-$/i;

  function joinWrappedLine(current, continuation) {
    if (current.endsWith("\u00ad")) return current.slice(0, -1) + continuation;
    const left = current.match(LONG_WORD_END);
    const right = continuation.match(SHORT_LOWER_FRAGMENT);
    if (left && right && right[1] === right[1].toLocaleLowerCase()) {
      return current.slice(0, -1) + continuation;
    }
    if (/[a-zà-öø-ÿ]-$/i.test(current)) return current + continuation;
    return `${current} ${continuation}`;
  }

  function cleanPastedNotes(value) {
    const lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
    const items = [];
    let current = "";
    const flush = () => {
      if (current) items.push(current);
      current = "";
    };

    lines.forEach((rawLine) => {
      const indent = (rawLine.match(/^[\t ]*/) || [""])[0].replace(/\t/g, "    ");
      const line = rawLine.replace(/\s+/g, " ").trim();
      if (!line) return;
      if (ITEM_START.test(line)) {
        flush();
        current = `${indent}${line}`;
      } else if (!current) {
        current = line;
      } else {
        current = joinWrappedLine(current, line);
      }
    });
    flush();
    return items.join("\n");
  }

  function cleanPastedAbstract(value) {
    const cleaned = cleanPastedNotes(value);
    const items = cleaned.split("\n").filter(Boolean);
    const quotedItems = items.map((item) => {
      const content = item.replace(ITEM_START, "").trim();
      const straight = content.match(/^"([\s\S]+)"$/);
      const curly = content.match(/^“([\s\S]+)”$/);
      return straight?.[1] || curly?.[1] || "";
    }).filter(Boolean);

    // Some copied summaries wrap the real abstract in quotes and surround it
    // with bibliography notes or empty headings. Only extract when there is
    // exactly one unambiguous quoted item, so genuine abstract lists survive.
    if (items.length > 1 && quotedItems.length === 1) {
      return quotedItems[0].trim();
    }
    return cleaned;
  }

  return { cleanPastedNotes, cleanPastedAbstract };
}));
