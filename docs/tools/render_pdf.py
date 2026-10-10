"""Render docs/TECHNICAL_DESIGN.md (Markdown + Mermaid) to PDF and export every diagram as SVG/PNG.

Setup (once):  cd docs/tools && npm install && pip install playwright
Run:           python docs/tools/render_pdf.py
               -> docs/TECHNICAL_DESIGN.pdf and docs/diagrams/*.svg|png
Uses the locally installed Google Chrome (or Playwright's Chromium if `playwright install chromium` was run).
"""

import asyncio
import json
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
MERMAID = HERE / "node_modules/mermaid/dist/mermaid.min.js"
MARKED = HERE / "node_modules/marked/marked.min.js"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><base href="__BASE__">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
  @page { size: A4; margin: 18mm 16mm 20mm; }
  body { font-family: Inter, system-ui, sans-serif; font-size: 10.2pt; line-height: 1.55; color: #0f172a; }
  .cover { height: 245mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always;
    background: radial-gradient(120mm 90mm at 15% 10%, #e0e7ff, transparent 70%), radial-gradient(120mm 90mm at 95% 95%, #fae8ff, transparent 70%);
    border-radius: 6mm; padding: 0 16mm; }
  .cover .logo { width: 22mm; height: 22mm; border-radius: 6mm; display: grid; place-items: center; font-size: 30pt; font-weight: 800; color: #fff;
    background: linear-gradient(135deg, #4f46e5, #7c3aed 55%, #c026d3); }
  .cover h1 { font-size: 38pt; margin: 10mm 0 2mm; letter-spacing: -.02em; border: 0; }
  .cover h2 { font-size: 18pt; color: #4f46e5; margin: 0 0 12mm; border: 0; page-break-before: avoid; }
  .cover table { width: auto; font-size: 11pt; } .cover td { border: 0; padding: 1.5mm 6mm 1.5mm 0; background: none !important; }
  h1 { font-size: 22pt; }
  h2 { font-size: 17pt; color: #312e81; border-bottom: 2px solid #c7d2fe; padding-bottom: 2mm; margin-top: 0; page-break-before: always; }
  h3 { font-size: 12.5pt; color: #4338ca; margin-top: 7mm; page-break-after: avoid; }
  h2 + h3 { margin-top: 3mm; }
  a { color: #4f46e5; text-decoration: none; }
  table { border-collapse: collapse; width: 100%; margin: 3mm 0 4mm; font-size: 9pt; page-break-inside: auto; }
  tr { page-break-inside: avoid; }
  th { background: #eef2ff; color: #312e81; text-align: left; }
  th, td { border: 1px solid #dbe1ee; padding: 1.6mm 2.2mm; vertical-align: top; }
  tr:nth-child(even) td { background: #f8fafc; }
  code { font-family: "JetBrains Mono", Menlo, monospace; font-size: 8.4pt; background: #f1f5f9; padding: .3mm 1mm; border-radius: 1mm; }
  pre { background: #0f172a; color: #e2e8f0; padding: 3.5mm 4mm; border-radius: 2mm; overflow: hidden; white-space: pre-wrap; page-break-inside: avoid; }
  pre code { background: none; color: inherit; padding: 0; font-size: 8pt; }
  .mermaid { text-align: center; margin: 4mm 0 6mm; page-break-inside: avoid; }
  .mermaid svg { max-width: 100% !important; height: auto; max-height: 215mm; }
  @page wide { size: A4 landscape; margin: 14mm 16mm 18mm; }
  .wide-figure { page: wide; display: flex; flex-direction: column; justify-content: center; min-height: 160mm; }
  .wide-figure .mermaid svg { max-height: 158mm; width: 100%; }
  .wide-figure figcaption, .fig-caption { text-align: center; font-size: 9pt; color: #475569; margin-top: 2mm; }
  img { max-width: 100%; border: 1px solid #e2e8f0; border-radius: 2mm; page-break-inside: avoid; }
  td img { width: 100%; } p > img { display: block; margin: 3mm auto; }
  blockquote { border-left: 3px solid #a5b4fc; margin: 0; padding-left: 4mm; color: #475569; }
  hr { display: none; }
  ul, ol { padding-left: 6mm; } li { margin: .6mm 0; }
</style>
<script src="__MARKED__"></script><script src="__MERMAID__"></script>
</head><body><div id="doc"></div>
<script>
  const md = __MD__;
  const slug = (t) => t.trim().toLowerCase().replace(/[^\\p{L}\\p{N}\\- ]+/gu, '').replace(/ /g, '-');
  document.getElementById('doc').innerHTML = marked.parse(md, { gfm: true });
  // cover page from the first table + title
  const doc = document.getElementById('doc');
  const firstTable = doc.querySelector('table');
  const cover = document.createElement('section'); cover.className = 'cover';
  cover.innerHTML = '<div class="logo">₹</div><h1>Rika — AI Expense &amp; Reimbursement Agent</h1><h2>Technical Design Document</h2>';
  const coverTable = firstTable.cloneNode(true);
  coverTable.querySelector('thead')?.remove();
  cover.appendChild(coverTable);
  doc.prepend(cover);
  firstTable.remove();
  // The document title and subtitle already appear on the cover.
  [...doc.querySelectorAll(':scope > h1, :scope > h2')].slice(0, 2).forEach((h) => h.remove());
  doc.querySelectorAll('h2, h3').forEach((h) => { if (!h.closest('.cover')) h.id = slug(h.textContent); });
  const blocks = [...doc.querySelectorAll('pre code.language-mermaid')];
  window.__diagrams = blocks.map((code) => code.textContent);
  blocks.forEach((code, i) => {
    const div = document.createElement('div'); div.className = 'mermaid'; div.id = 'diagram-' + i;
    div.textContent = code.textContent; code.parentElement.replaceWith(div);
  });
  mermaid.initialize({ startOnLoad: false, securityLevel: 'loose', theme: 'base', fontFamily: 'Inter',
    themeVariables: { primaryColor: '#eef2ff', primaryBorderColor: '#6366f1', primaryTextColor: '#1e1b4b',
      lineColor: '#64748b', secondaryColor: '#fdf4ff', tertiaryColor: '#f8fafc', fontSize: '15px',
      clusterBkg: '#f8fafc', clusterBorder: '#c7d2fe', noteBkgColor: '#fef9c3', noteBorderColor: '#facc15' },
    flowchart: { htmlLabels: true, curve: 'basis' }, sequence: { mirrorActors: false } });
  window.__errors = [];
  (async () => {
    // Mermaid sizes boxes by measuring text, so the web font must be loaded first or labels get clipped.
    await Promise.all(['400 15px Inter', '500 15px Inter', '600 15px Inter', '700 15px Inter'].map((f) => document.fonts.load(f)));
    await document.fonts.ready;
    for (const [i, src] of window.__diagrams.entries()) {
      try { await mermaid.parse(src); } catch (e) { window.__errors.push({ i, error: String(e.message || e).slice(0, 400) }); }
    }
    await mermaid.run({ querySelector: '.mermaid' });
    await document.fonts.ready;
    // Wide diagrams get their own landscape page, captioned with the section they belong to.
    document.querySelectorAll('.mermaid').forEach((div) => {
      const box = div.querySelector('svg').viewBox.baseVal;
      let heading = div.previousElementSibling;
      while (heading && !/^H[23]$/.test(heading.tagName)) heading = heading.previousElementSibling;
      const label = heading ? heading.textContent.trim() : '';
      if (box.width / box.height > 1.45) {
        const fig = document.createElement('figure'); fig.className = 'wide-figure';
        div.replaceWith(fig); fig.appendChild(div);
        const cap = document.createElement('figcaption'); cap.textContent = 'Figure — ' + label; fig.appendChild(cap);
      }
    });
    window.__done = true;
  })();
</script></body></html>"""

FOOTER = """<div style="font-family: Helvetica, Arial, sans-serif; font-size: 7.5pt; color: #64748b; width: 100%; padding: 0 16mm;
  display: flex; justify-content: space-between;"><span>Rika — Technical Design Document · AI Innovation Lab</span>
  <span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>"""

NAMES = [
    "high-level-architecture", "backend-layers", "frontend-architecture", "deployment", "end-to-end-journey",
    "receipt-pipeline", "two-pass-extraction", "claim-lifecycle", "question-engine", "approval-payout",
    "realtime-sse", "llm-fallback", "chat-actions", "data-model",
]


async def main(md_path: Path, pdf_path: Path, diagram_dir: Path) -> None:
    html = (PAGE.replace("__BASE__", md_path.parent.resolve().as_uri() + "/")
            .replace("__MARKED__", MARKED.as_uri()).replace("__MERMAID__", MERMAID.as_uri())
            .replace("__MD__", json.dumps(md_path.read_text())))
    page_file = HERE / ".render.html"
    page_file.write_text(html)
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(channel="chrome", headless=True)
        except Exception:  # no Google Chrome: fall back to Playwright's own Chromium
            browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1100, "height": 1400}, device_scale_factor=2)
        await page.goto(page_file.as_uri())
        await page.wait_for_function("window.__done === true", timeout=60000)
        errors = await page.evaluate("window.__errors")
        count = await page.evaluate("window.__diagrams.length")
        print(f"{count} diagrams, {len(errors)} errors")
        for err in errors:
            print("  diagram", err["i"], err["error"])
        diagram_dir.mkdir(parents=True, exist_ok=True)
        for i in range(count):
            name = f"{i + 1:02d}-{NAMES[i] if i < len(NAMES) else 'diagram'}"
            svg = await page.evaluate(f"document.querySelector('#diagram-{i} svg').outerHTML")
            (diagram_dir / f"{name}.svg").write_text(svg)
            await page.locator(f"#diagram-{i} svg").screenshot(path=str(diagram_dir / f"{name}.png"), omit_background=False)
        await page.pdf(path=str(pdf_path), format="A4", print_background=True, display_header_footer=True,
                       header_template="<span></span>", footer_template=FOOTER,
                       margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"})
        await browser.close()
    print("pdf:", pdf_path, round(pdf_path.stat().st_size / 1024), "KB")


if __name__ == "__main__":
    args = sys.argv[1:] or [DOCS / "TECHNICAL_DESIGN.md", DOCS / "TECHNICAL_DESIGN.pdf", DOCS / "diagrams"]
    asyncio.run(main(*(Path(a) for a in args)))
