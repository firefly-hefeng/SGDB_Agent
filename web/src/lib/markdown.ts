/* Minimal markdown → HTML renderer.
 *
 * Subset: headings (#…######), unordered lists (-/*), blockquotes (>),
 * pipe-tables (| a | b |), code spans (`code`), bold (**), italic (*),
 * inline links ([text](url)), and horizontal rules (---). Designed to
 * cover what the discovery agent's Synthesizer emits without pulling in
 * react-markdown (~80 kB gzipped).
 *
 * Used by `<MarkdownView markdown={…} />`. The output is treated as
 * trusted (Synthesizer is server-side), but every interpolated value
 * still goes through `escapeHtml`. */

function escapeHtml(s: string): string {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

// Allowlist: http(s), mailto, relative paths, anchors, query-only.
// Rejects javascript:, data:, vbscript:, file:, etc.
function safeUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) return '#';
  if (/^(?:https?:|mailto:|ftp:|\/|#|\?|\.)/i.test(trimmed)) {
    return trimmed;
  }
  return '#';
}

function inline(s: string): string {
  return escapeHtml(s)
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_match, text: string, url: string) => {
      // Both `text` and `url` are already HTML-escaped (entity encoded);
      // the safeUrl gate operates on the escaped string but the dangerous
      // `javascript:` prefix survives escaping unchanged, so the allowlist
      // still catches it.
      return `<a href="${safeUrl(url)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    })
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

export function renderMarkdown(md: string): string {
  const lines = md.split('\n');
  const html: string[] = [];
  let inTable = false;
  let inList = false;

  const closeList = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
  };
  const closeTable = () => {
    if (inTable) {
      html.push('</tbody></table>');
      inTable = false;
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.trimEnd();

    if (/^\s*$/.test(line)) {
      closeList();
      closeTable();
      continue;
    }

    if (line.startsWith('|') && lines[i + 1] && /^\|[-:\s|]+\|/.test(lines[i + 1].trim())) {
      closeList();
      const headers = line.slice(1, -1).split('|').map((s) => s.trim());
      html.push(
        '<table><thead><tr>' +
          headers.map((h) => `<th>${inline(h)}</th>`).join('') +
          '</tr></thead><tbody>',
      );
      i += 1;
      inTable = true;
      continue;
    }
    if (inTable && line.startsWith('|')) {
      const cells = line.slice(1, -1).split('|').map((s) => s.trim());
      html.push('<tr>' + cells.map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>');
      continue;
    }
    closeTable();

    let m: RegExpMatchArray | null;
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      closeList();
      html.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`);
    } else if ((m = line.match(/^[-*]\s+(.*)$/))) {
      if (!inList) {
        html.push('<ul>');
        inList = true;
      }
      html.push(`<li>${inline(m[1])}</li>`);
    } else if ((m = line.match(/^>\s+(.*)$/))) {
      closeList();
      html.push(`<blockquote>${inline(m[1])}</blockquote>`);
    } else if (line === '---') {
      closeList();
      html.push('<hr/>');
    } else {
      closeList();
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  closeList();
  closeTable();
  return html.join('\n');
}
