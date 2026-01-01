
#!/usr/bin/env python3
"""
Generate a publications HTML page from a BibTeX file.

Layout & features:
- One-column content (years on the right).
- Left pane: sticky, scrollable & searchable year list.
- Two lines of topic filters (color-coded) fixed while scrolling.
- Robust JS filtering (independent of DOM sibling structure).
- Collapsible year sections (CSS only).
- BibTeX hidden by default with per-entry toggle.
- Back-to-top button.

Usage:
  python generate_publications_fixedfilters.py publications.bib publications.html
"""

import argparse
import html
import re
from pathlib import Path
from collections import defaultdict

# ------------------------------
# Configuration
# ------------------------------
CATS = [
    "HPC",
    "Quantum",
    "Architecture",
    "Programming Model",
    "Edge/IoT",
    "AI",
    "Applications",
]

# Distinct palette; clear separation (Quantum vs Applications)
COLORS = {
    "HPC": "#0EA5E9",               # sky blue
    "Quantum": "#7C3AED",           # deep violet
    "Architecture": "#F59E0B",      # amber
    "Programming Model": "#22C55E", # bright green
    "Edge/IoT": "#14B8A6",          # teal
    "AI": "#EF4444",                # bright red
    "Applications": "#DB2777",      # strong magenta
}
TINTS = {
    "HPC": "#E0F2FE",
    "Quantum": "#F3E8FF",
    "Architecture": "#FEF3C7",
    "Programming Model": "#DCFCE7",
    "Edge/IoT": "#CCFBF1",
    "AI": "#FEE2E2",
    "Applications": "#FCE7F3",
}

TOPIC_RULES = [
    ("Quantum", r"quantum|qubit|neutral\s+atom|hpcqc|mqss|qpi|qdmi|pulse\s+level|fidelity|superconducting"),
    ("Programming Model", r"\bmpi\b|message\s+passing|collective|mpit|mpi_t|pmix|sessions|openmp|ompd|ompt|malleability|runtime\s+system"),
    ("Edge/IoT", r"edge|dds|middleware|real\-time|sensor|stream|kubernetes|iot"),
    ("AI", r"machine\s+learning|neural|inference|benchmark.*ml|dataset\s+distillation|classification|deep\s+learning|artificial\s+intelligence"),
    ("Architecture", r"architecture|gpu|fpga|memory|cache|numa|vector\s+extension|cxl|network\s+topolog|hardware|hotplug|gate\s+drive|coherent\s+mesh"),
    ("Applications", r"synthetic\s+aperture\s+radar|sar|earth\s+observation|ocean|fusion|reactor|fluid|cfd|medical|imaging|lung|dielectric|workflows|visualization'96|graphics|vrml|crashworthiness|automotive"),
    ("HPC", r"high\s+performance\s+computing|supercomput|hpc\b|sc\d{2}|ipdps|euro\-?mpi|cluster\b|parallel\s+comput|exascale|performance\s+analysis|power\s+management|overprovision|dvfs|resilien|fault\s+tolerance"),
]
compiled_rules = [(name, re.compile(pat, re.IGNORECASE)) for name, pat in TOPIC_RULES]
# Priority order if multiple rules match:
PRIORITY = {cat: i for i, cat in enumerate(
    ["Quantum", "Programming Model", "Edge/IoT", "AI", "Architecture", "Applications", "HPC"]
)}

# ------------------------------
# Tolerant BibTeX parser (no external libs)
# ------------------------------
LATEX_REPLACEMENTS = [
    (r'\\"a', "ä"), (r'\\"o', "ö"), (r'\\"u', "ü"),
    (r'\\"A', "Ä"), (r'\\"O', "Ö"), (r'\\"U', "Ü"),
    (r"\\'a", "á"), (r"\\'e", "é"), (r"\\'i", "í"), (r"\\'o", "ó"), (r"\\'u", "ú"),
    (r"\\`a", "à"), (r"\\`e", "è"), (r"\\`i", "ì"), (r"\\`o", "ò"), (r"\\`u", "ù"),
    (r"\\~n", "ñ"), (r"\\^a", "â"), (r"\\^e", "ê"), (r"\\^i", "î"), (r"\\^o", "ô"), (r"\\^u", "û"),
    (r"\\ss", "ß"), (r"\\&", "&"), (r"\\_", "_"), (r"\\%", "%"), (r"\\$", "$"),
]

FIELD_PATTERNS = {
    "title": r"\btitle\s*=\s*(.+?)(?:,\s*\n|\n)",
    "author": r"\bauthor\s*=\s*(.+?)(?:,\s*\n|\n)",
    "year": r"\byear\s*=\s*(.+?)(?:,\s*\n|\n)",
    "journal": r"\bjournal\s*=\s*(.+?)(?:,\s*\n|\n)",
    "booktitle": r"\bbooktitle\s*=\s*(.+?)(?:,\s*\n|\n)",
    "institution": r"\binstitution\s*=\s*(.+?)(?:,\s*\n|\n)",
    "publisher": r"\bpublisher\s*=\s*(.+?)(?:,\s*\n|\n)",
    "organization": r"\borganization\s*=\s*(.+?)(?:,\s*\n|\n)",
    "volume": r"\bvolume\s*=\s*(.+?)(?:,\s*\n|\n)",
    "number": r"\bnumber\s*=\s*(.+?)(?:,\s*\n|\n)",
    "pages": r"\bpages\s*=\s*(.+?)(?:,\s*\n|\n)",
    "keywords": r"\bkeywords\s*=\s*(.+?)(?:,\s*\n|\n)",
    "doi": r"\bdoi\s*=\s*(.+?)(?:,\s*\n|\n)",
    "url": r"\burl\s*=\s*(.+?)(?:,\s*\n|\n)",
}

def unlatex(s: str) -> str:
    out = s
    for pat, rep in LATEX_REPLACEMENTS:
        out = re.sub(pat, rep, out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()

def _clean_field_value(v: str) -> str:
    v = v.strip()
    if v.startswith("{") and v.endswith("}"):
        v = v[1:-1]
    if v.startswith('"') and v.endswith('"'):
        v = v[1:-1]
    return unlatex(v)

def parse_bibtex_text(text: str):
    entries = []
    pos = 0
    while True:
        m = re.search(r'@[A-Za-z]+\s*\{', text[pos:])
        if not m:
            break
        start = pos + m.start()
        m2 = re.search(r'\n\s*@[A-Za-z]+\s*\{', text[start+1:])
        end = start + 1 + (m2.start() if m2 else len(text) - start - 1)
        segment = text[start:end].strip()
        pos = end

        mtype = re.match(r'@([A-Za-z]+)\s*\{', segment)
        etype = mtype.group(1).lower() if mtype else "misc"
        brace_idx = segment.find("{")
        comma_after_key = segment.find(",", brace_idx + 1)
        key = segment[brace_idx+1:comma_after_key].strip() if comma_after_key != -1 else ""

        fields = {"__type__": etype, "__key__": key, "__raw__": segment}
        for fname, pat in FIELD_PATTERNS.items():
            mm = re.search(pat, segment, re.IGNORECASE | re.DOTALL)
            if mm:
                fields[fname] = _clean_field_value(mm.group(1))

        y = fields.get("year", "")
        if y:
            mm = re.search(r'(19\d{2}|20\d{2})', y)
            fields["year"] = mm.group(1) if mm else "Unknown"
        else:
            fields["year"] = "Unknown"

        entries.append(fields)
    return entries

# ------------------------------
# Classification & filtering
# ------------------------------
def is_preprint(entry: dict) -> bool:
    s = " ".join([
        entry.get("journal", ""),
        entry.get("booktitle", ""),
        entry.get("publisher", ""),
        entry.get("organization", ""),
    ]).lower()
    return ("arxiv" in s) or ("preprint" in s)

def assign_category(entry: dict) -> str:
    text = " ".join([
        entry.get("title", ""),
        entry.get("journal", ""),
        entry.get("booktitle", ""),
        entry.get("institution", ""),
        entry.get("publisher", ""),
        entry.get("organization", ""),
        entry.get("keywords", ""),
    ])
    hits = [cat for cat, rx in compiled_rules if rx.search(text)]
    if hits:
        hits.sort(key=lambda c: PRIORITY[c])
        return hits[0]
    venue = (entry.get("booktitle", "") + " " + entry.get("journal", "")).lower()
    if re.search(r"(sc\d{2}|ipdps|euro\-?mpi|cluster|hpcs|hpdc|ics|isc)", venue):
        return "HPC"
    return "Applications"

# ------------------------------
# HTML generation helpers
# ------------------------------
def _css_base() -> str:
    # Sticky offsets: tune if your site’s header/filter heights differ
    return """
:root{--bg:#ffffff;--fg:#111827;--muted:#6b7280;--border:#e5e7eb;--header-h:64px;--filters-h:120px}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif;background:#fff;color:#111827}

header{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--border);z-index:1000}
header .wrap{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px}

.filters{position:sticky;top:var(--header-h);z-index:999;display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border);background:#fff}
.filter{display:inline-flex;align-items:center;gap:6px;margin:4px}
.filter input{position:absolute;left:-9999px;top:-9999px}
.filter label{display:inline-block;padding:8px 12px;border:2px solid var(--border);border-radius:999px;background:#fff;color:#111827;cursor:pointer;font-weight:600}
.filter input:checked + label{color:#fff}
.actions{display:inline-flex;gap:8px;margin-left:auto}
.actions button{padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:#fff;color:#111827;cursor:pointer}
.actions button:hover{background:#f9fafb}

main{display:grid;grid-template-columns:280px 1fr;gap:20px;padding:20px}
@media(max-width:900px){main{grid-template-columns:1fr}aside{order:2}}

aside{position:sticky;top:calc(var(--header-h) + var(--filters-h));align-self:start}
.aside-card{background:#fff;border:1px solid var(--border);border-radius:12px;padding:12px}
.aside-card h3{margin:8px 0;font-size:14px;color:#6b7280}
.year-search{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;margin-bottom:8px}
.years-list{max-height:calc(100vh - var(--header-h) - var(--filters-h) - 140px); overflow-y:auto; padding-right:6px}
.years-list a{display:flex;align-items:center;justify-content:space-between;padding:6px 8px;color:#111827;text-decoration:none;border-radius:6px}
.years-list a:hover{background:#f9fafb}
.years-list .badge{margin-left:10px}

.section{border:1px solid var(--border);border-radius:12px;background:#fff;margin-bottom:16px}
.section label.year-toggle{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;font-weight:600;font-size:18px;border-bottom:1px dashed var(--border);cursor:pointer}
.section .content{padding:6px 12px}
.section input[type=checkbox].year{display:none}
.section input.year:not(:checked) ~ .content{display:none}

.card{border:1px solid var(--border);border-radius:12px;padding:12px;margin:12px 0;box-shadow:0 1px 2px rgba(0,0,0,0.04);background:#fff}
.card .title{font-weight:600;font-size:16px}
.card .meta{font-size:13px;color:#6b7280;margin-top:6px}
.chips{margin-top:6px;display:flex;gap:8px;flex-wrap:wrap}
.chip{font-size:12px;background:#f3f4f6;border:1px solid var(--border);color:#374151;padding:4px 8px;border-radius:999px}

.card input.bib{display:none}
.card input.bib + label.biblabel{font-size:12px;color:#111827;text-decoration:underline;cursor:pointer}
.card input.bib:not(:checked) + label.biblabel + pre.bib{display:none}
.card input.bib:checked + label.biblabel + pre.bib{display:block}
pre.bib{background:#f9fafb;color:#1f2937;border-radius:8px;padding:10px;overflow:auto;border:1px solid var(--border)}

.badge{background:#f3f4f6;border:1px solid var(--border);padding:2px 6px;border-radius:6px;font-size:12px;margin-left:6px}
#toTop{position:fixed;bottom:20px;right:20px;background:#111827;color:#fff;border:none;border-radius:999px;padding:10px 14px;box-shadow:0 2px 6px rgba(0,0,0,0.2);}
#toTop:hover{opacity:.9}
.hidden{display:none !important}
"""

def _css_topic_buttons() -> str:
    css = []
    for cat, color in COLORS.items():
        css.append(f'.filter label[data-cat="{cat}"]' + '{' + f'border-color:{color}; color:{color}; background:#fff;' + '}')
        css.append(f'.filter input:checked + label[data-cat="{cat}"]' + '{' + f'background:{color}; border-color:{color}; color:#fff;' + '}')
    return "\n".join(css) + "\n"

def _css_topic_cards() -> str:
    css = []
    for cat, color in COLORS.items():
        tint = TINTS[cat]
        cls = re.sub(r"[^a-z0-9]", "-", cat.lower())
        css.append(f".cat-{cls} .chip.cat"+"{"+f"border-color:{color}; color:{color};"+"}")
        css.append(f".cat-{cls} .card"+"{"+f"border-left:6px solid {color}; background:{tint};"+"}")
    return "\n".join(css) + "\n"

def _bold_name(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'(Schulz,\s*Martin|Martin\s*Schulz)', r'<b>\1</b>', html.escape(text))

# ------------------------------
# Main generator
# ------------------------------
def generate_html(entries, outfile: Path):
    # Remove preprints and classify
    filtered = []
    for e in entries:
        if is_preprint(e):
            continue
        e["category"] = assign_category(e)
        filtered.append(e)

    # Group by year
    by_year = defaultdict(list)
    for e in filtered:
        by_year[e["year"]].append(e)

    sorted_years = sorted(by_year.keys(), key=lambda yy: (yy == "Unknown", -int(yy) if yy.isdigit() else 0))

    # Build CSS
    css = _css_base() + _css_topic_buttons() + _css_topic_cards()

    # Filters UI (color-coded buttons via data-cat attribute)
    filters_html = "\n".join(
        f'<span class="filter"><input type="checkbox" id="filter-{re.sub("[^a-z0-9]","-", c.lower())}" checked>'
        f'<label for="filter-{re.sub("[^a-z0-9]","-", c.lower())}" data-cat="{c}">{html.escape(c)}</label></span>'
        for c in CATS
    )

    # Sidebar: year links (with counts)
    year_links = "\n".join(
        f'<a href="#y-{html.escape(y)}" data-year="{html.escape(y)}">{html.escape(y)} <span class="badge">{len(by_year[y])}</span></a>'
        for y in sorted_years
    )

    # Build year sections (content column)
    sections_html = []
    entry_counter = 0
    for y in sorted_years:
        cards = []
        for e in sorted(by_year[y], key=lambda x: (x.get("title", "") or "").lower()):
            entry_counter += 1
            cat = e["category"]
            cls = re.sub("[^a-z0-9]", "-", cat.lower())

            title = html.escape(e.get("title", "Untitled"))
            authors = _bold_name(e.get("author", ""))

            venue = e.get("journal") or e.get("booktitle") or e.get("institution") or e.get("publisher") or e.get("organization") or ""
            meta_parts = []
            if venue:
                meta_parts.append(html.escape(venue))
            if e.get("volume"):
                meta_parts.append("Vol. " + html.escape(e["volume"]))
            if e.get("number"):
                meta_parts.append("No. " + html.escape(e["number"]))
            if e.get("pages"):
                meta_parts.append("pp. " + html.escape(e["pages"]))
            meta = " • ".join(meta_parts)

            etype = e["__type__"]
            raw_bib = html.escape(e.get("__raw__", ""))
            key = e.get("__key__", "") or f"k{entry_counter}"
            bib_id = f"bib-{y}-{entry_counter}"

            cards.append(
                f'<div class="cat-{cls}">'
                f'<article class="card" data-year="{html.escape(y)}" data-type="{html.escape(etype)}" data-category="{html.escape(cat)}">'
                f'  <div class="title">{title}</div>'
                f'  <div class="meta">{authors}{(" • " + meta) if meta else ""}</div>'
                f'  <div class="chips">'
                f'    <span class="chip cat">{html.escape(cat)}</span>'
                f'    <span class="chip">Key: {html.escape(key)}</span>'
                f'    <span class="chip">{html.escape(etype)}</span>'
                f'  </div>'
                f'  <input type="checkbox" id="{bib_id}" class="bib" />'
                f'  <label for="{bib_id}" class="biblabel">Show BibTeX</label>'
                f'  <pre class="bib">{raw_bib}</pre>'
                f'</article>'
                f'</div>'
            )
        sections_html.append(
            f'<section class="section" id="y-{html.escape(y)}">'
            f'  <input type="checkbox" id="cb-{html.escape(y)}" class="year" checked>'
            f'  <label for="cb-{html.escape(y)}" class="year-toggle">{html.escape(y)} <span class="badge">{len(cards)}</span></label>'
            f'  <div class="content">'
            f'    {"".join(cards)}'
            f'  </div>'
            f'</section>'
        )

    # Robust JS filtering + year list search
    js = """
(function(){
  const cats = ['HPC','Quantum','Architecture','Programming Model','Edge/IoT','AI','Applications'];
  const idFor = c => 'filter-' + c.toLowerCase().replace(/[^a-z0-9]/g,'-');

  function applyFilters(){
    const states = {};
    cats.forEach(c=>{
      const cb = document.getElementById(idFor(c));
      states[c] = cb ? cb.checked : true;
    });
    document.querySelectorAll('.card').forEach(card=>{
      const cat = card.getAttribute('data-category');
      const show = (cat && states[cat] !== false);
      card.classList.toggle('hidden', !show);
    });
  }

  cats.forEach(c=>{
    const cb = document.getElementById(idFor(c));
    if(cb){ cb.addEventListener('change', applyFilters); }
  });

  const allBtn = document.getElementById('btnAll');
  const noneBtn = document.getElementById('btnNone');
  if(allBtn) allBtn.addEventListener('click', ()=>{ cats.forEach(c=>{ const cb=document.getElementById(idFor(c)); if(cb){ cb.checked=true; } }); applyFilters(); });
  if(noneBtn) noneBtn.addEventListener('click', ()=>{ cats.forEach(c=>{ const cb=document.getElementById(idFor(c)); if(cb){ cb.checked=false; } }); applyFilters(); });

  applyFilters();

  // Year list search
  const ySearch = document.getElementById('yearSearch');
  const yLinks = Array.from(document.querySelectorAll('.years-list a'));
  function filterYears(){
    const q = (ySearch && ySearch.value || '').trim().toLowerCase();
    yLinks.forEach(a=>{
      const txt = a.getAttribute('data-year') || a.textContent || '';
      a.style.display = (!q || txt.toLowerCase().indexOf(q) !== -1) ? '' : 'none';
    });
  }
  if(ySearch){ ySearch.addEventListener('input', filterYears); }
})();
"""

    # Compose final HTML safely (no nested unclosed quotes)
    html_doc = (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8" />\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
        "  <title>Publications – Martin Schulz</title>\n"
        "  <style>\n"
        f"{_css_base()}\n"
        f"{_css_topic_buttons()}\n"
        f"{_css_topic_cards()}\n"
        "  </style>\n"
        "</head>\n"
        '<body id="top">\n'
        "<header>\n"
        '  <div class="wrap">\n'
        "    <strong>Topic filters</strong>\n"
        '    <span class="actions">\n'
        '      <button id="btnAll">All</button>\n'
        '      <button id="btnNone">None</button>\n'
        "    </span>\n"
        "  </div>\n"
        "</header>\n"
        '<div class="filters" aria-label="Topic filters">\n'
        f"{filters_html}\n"
        "</div>\n"
        "<main>\n"
        "  <aside>\n"
        '    <div class="aside-card">\n'
        "      <h3>Jump to year</h3>\n"
        '      <input id="yearSearch" class="year-search" type="search" placeholder="Filter years…" aria-label="Filter years" />\n'
        '      <div class="years-list">\n'
        f"{year_links}\n"
        "      </div>\n"
        "    </div>\n"
        "  </aside>\n"
        "  <div>\n"
        f'    {"".join(sections_html)}\n'
        "  </div>\n"
        "</main>\n"
        '<a href="#top" id="toTop" title="Back to top">Top</a>\n'
        '<div class="footer">Auto-generated from BibTeX.</div>\n'
        "<script>\n"
        f"{js}\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )

    outfile.write_text(html_doc, encoding="utf-8")
    print(f"Written: {outfile} (entries={len(filtered)}, years={len(sorted_years)})")


# ------------------------------
# CLI
# ------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generate publications HTML from a BibTeX file (fixed filters, left pane scroll/search, one-column content).")
    ap.add_argument("bib_file", type=Path, help="Input BibTeX file")
    ap.add_argument("out_html", type=Path, help="Output HTML file")
    args = ap.parse_args()

    text = args.bib_file.read_text(encoding="utf-8")
    entries = parse_bibtex_text(text)
    generate_html(entries, args.out_html)


if __name__ == "__main__":
    main()
