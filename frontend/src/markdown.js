// Tiny, dependency-free markdown renderer for scraped job descriptions.
//
// Postings scraped from LinkedIn/Indeed arrive as ad-hoc markdown: **bold**
// section titles, bullets, numbered lists, bare URLs — and LinkedIn often
// CRAMS the bullets inline into one long line ("Responsibilities * A. * B.").
// This renderer turns all of that into clean rich text (like the original
// dashboard reads) without pulling in a markdown library.
//
// Security: descriptions come from external sites, so the input is
// HTML-ESCAPED FIRST — only tags this function itself emits can appear in
// the output (safe for dangerouslySetInnerHTML).

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => ESCAPES[ch])
}

function inline(text) {
  let out = escapeHtml(text)
  // Bare URLs become links. Runs after escaping, so &amp; inside the href is
  // valid HTML and quotes can't break out of the attribute.
  out = out.replace(
    /\bhttps?:\/\/[^\s<>"')\]]+/g,
    (url) => `<a href="${url}" target="_blank" rel="noreferrer noopener">${url}</a>`,
  )
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // Single-star emphasis: must open with a non-space and stay short, so a
  // stray bullet marker ("…science. * Create…") can never italicize the
  // whole sentence between two bullet asterisks.
  out = out.replace(/\*(\S[^*\n]{0,300}?)\*/g, '<em>$1</em>')
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>')
  return out
}

// LinkedIn variants cram bullets into one line:
//   "Compensation * **$245–$280/hour** * **Remote** * **Flexible schedule**"
// Splitting on " * " (a lone star surrounded by whitespace — `**bold**` never
// matches because its stars are doubled) turns that into a real list.
// Needs >= 2 separators so "a * b" math/prose is never mangled.
function splitInlineBullets(line) {
  const parts = line.split(/\s\*\s+/)
  if (parts.length >= 3 && parts.slice(1).every((part) => part.trim())) {
    return parts
  }
  return null
}

export function renderMarkdown(source) {
  if (!source) return ''
  const lines = String(source).replace(/\r\n?/g, '\n').split('\n')
  const html = []
  let list = null // 'ul' | 'ol' | null
  let para = []

  const flushPara = () => {
    if (para.length) {
      html.push(`<p>${para.map(inline).join('<br>')}</p>`)
      para = []
    }
  }
  const openList = (kind) => {
    if (list !== kind) {
      flushList()
      html.push(`<${kind}>`)
      list = kind
    }
  }
  const flushList = () => {
    if (list) {
      html.push(`</${list}>`)
      list = null
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd()
    const bullet = line.match(/^\s*(?:[*\-•‣])\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)
    const heading = line.match(/^\s*(#{1,6})\s+(.*)$/)
    const inlineBullets = !bullet && !numbered && !heading ? splitInlineBullets(line) : null

    if (!line.trim()) {
      flushPara()
      flushList()
    } else if (heading) {
      // Scraped headings render as a bold line — keeps the sizing sane in
      // both the compact card preview and the modal.
      flushPara()
      flushList()
      html.push(`<p><strong>${inline(heading[2])}</strong></p>`)
    } else if (bullet) {
      flushPara()
      openList('ul')
      html.push(`<li>${inline(bullet[1])}</li>`)
    } else if (numbered) {
      flushPara()
      openList('ol')
      html.push(`<li>${inline(numbered[1])}</li>`)
    } else if (inlineBullets) {
      // Lead-in text (e.g. "Key Responsibilities") stays a paragraph; the
      // rest become list items.
      flushList()
      para.push(inlineBullets[0].trim())
      flushPara()
      openList('ul')
      for (const item of inlineBullets.slice(1)) {
        html.push(`<li>${inline(item.trim())}</li>`)
      }
    } else {
      flushList()
      para.push(line)
    }
  }
  flushPara()
  flushList()
  // Joined without newlines: the card preview keeps `white-space: pre-wrap`,
  // so any literal \n here would render as a stray blank line.
  return html.join('')
}
