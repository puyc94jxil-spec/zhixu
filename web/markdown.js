/** 只生成结构化块。渲染时必须用 textContent，不能把原文交给 innerHTML。 */

export function parseMarkdown(source) {
  const lines = String(source || "").replaceAll("\r\n", "\n").split("\n");
  const blocks = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line.startsWith("```")) {
      const body = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        body.push(lines[index]);
        index += 1;
      }
      blocks.push({ type: "code", text: body.join("\n") });
      index += 1;
      continue;
    }
    if (line.includes("|") && index + 1 < lines.length && /^\s*\|?\s*-+/.test(lines[index + 1])) {
      const rows = [];
      rows.push(splitRow(line));
      index += 2;
      while (index < lines.length && lines[index].includes("|")) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      blocks.push({ type: "table", rows });
      continue;
    }
    if (/^#{1,3}\s+/.test(line)) {
      blocks.push({ type: "heading", text: line.replace(/^#{1,3}\s+/, "") });
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push({ type: "list", items });
      continue;
    }
    if (line.trim() === "") {
      index += 1;
      continue;
    }
    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !lines[index].startsWith("```") &&
      !/^#{1,3}\s+/.test(lines[index]) &&
      !/^\s*[-*]\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraph.join("\n") });
  }
  return blocks;
}

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function renderMarkdown(parent, source) {
  parent.replaceChildren();
  for (const block of parseMarkdown(source)) {
    if (block.type === "heading") {
      const node = document.createElement("h3");
      node.textContent = block.text;
      parent.append(node);
    } else if (block.type === "list") {
      const node = document.createElement("ul");
      for (const item of block.items) {
        const li = document.createElement("li");
        li.textContent = item;
        node.append(li);
      }
      parent.append(node);
    } else if (block.type === "code") {
      const node = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = block.text;
      node.append(code);
      parent.append(node);
    } else if (block.type === "table") {
      const table = document.createElement("table");
      for (const row of block.rows) {
        const tr = document.createElement("tr");
        for (const cell of row) {
          const td = document.createElement("td");
          td.textContent = cell;
          tr.append(td);
        }
        table.append(tr);
      }
      parent.append(table);
    } else {
      const node = document.createElement("p");
      node.textContent = block.text;
      parent.append(node);
    }
  }
}
