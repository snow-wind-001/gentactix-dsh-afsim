// 模型输出是 Markdown（旧 Streamlit 用 st.markdown 渲染）。
// 安全子集：先转义HTML，再渲染标题、行内格式、列表、围栏代码及数据表。
function inline(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
}

function cells(line: string): string[] {
  const text = line.trim(), parts: string[] = [];
  let cell = "";
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === "\\" && (text[i+1] === "|" || text[i+1] === "\\")) cell += text[++i];
    else if (char === "|") { parts.push(cell.trim()); cell = ""; }
    else cell += char;
  }
  parts.push(cell.trim());
  if (text.startsWith("|")) parts.shift();
  if (parts.at(-1) === "" && text.endsWith("|")) parts.pop();
  return parts;
}

export function mdToHtml(text: string): string {
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const lines = esc.split("\n"), output: string[] = [], plain: string[] = [];
  const flush = () => {
    if (plain.length) output.push(inline(plain.join("\n"))
      .replace(/^#{2,4} (.*)$/gm, "<h4>$1</h4>")
      .replace(/^[-*] (.*)$/gm, "• $1").replace(/\n/g, "<br/>"));
    plain.length = 0;
  };
  for (let i = 0; i < lines.length; i++) {
    const fence = lines[i].trim().match(/^(`{3,}|~{3,})/);
    if (fence) {
      flush(); const body: string[] = [], marker = fence[1];
      while (++i < lines.length && !lines[i].trim().startsWith(marker)) body.push(lines[i]);
      output.push("<pre><code>" + body.join("\n") + "</code></pre>"); continue;
    }
    const head = cells(lines[i]), rule = cells(lines[i+1] ?? "");
    if (head.length > 1 && rule.length === head.length && rule.every(cell => /^:?-{3,}:?$/.test(cell))) {
      flush(); i++; const body: string[] = [];
      while (i+1 < lines.length && lines[i+1].includes("|")) {
        const row = cells(lines[i+1]); if (row.length !== head.length) break;
        body.push("<tr>" + row.map(cell => "<td>" + inline(cell) + "</td>").join("") + "</tr>"); i++;
      }
      output.push('<div class="markdown-table-scroll" tabindex="0" role="region" aria-label="数据表，可水平滚动"><table><thead><tr>'
        + head.map(cell => '<th scope="col">' + inline(cell) + "</th>").join("")
        + "</tr></thead><tbody>" + body.join("") + "</tbody></table></div>");
    } else plain.push(lines[i]);
  }
  flush(); return output.join("");
}
