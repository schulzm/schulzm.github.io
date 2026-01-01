
#!/usr/bin/env python3
"""
Generate a publications HTML page from a BibTeX file.

Features:
- Year-first grouping, collapsible year sections (CSS)
- Topic filters with visible selection state + All/None buttons
- Robust JS filtering (default) OR pure CSS filtering via --no-js-filters
- BibTeX hidden by default via per-entry checkbox
- Distinct color palette; Quantum vs Applications clearly separated
- Back-to-top anchor button

Usage:
  python generate_publications.py publications.bib publications.html
  python generate_publications.py publications.bib publications.html --no-js-filters
"""

import argparse
import html
import json
import re
from pathlib import Path
from collections import defaultdict

# ------------------------------
# Configuration: Categories, Colors
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

# Distinct palette; strong separation for Quantum vs Applications
COLORS = {
    "HPC": "#0EA5E9",              # sky blue
    "Quantum": "#7C3AED",          # deep violet
    "Architecture": "#F59E0B",     # amber
    "Programming Model": "#22C55E",# bright green
    "Edge/IoT": "#14B8A6",         # teal
    "AI": "#EF4444",               # bright red
    "Applications": "#DB2777",     # strong magenta (distinct from Quantum)
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

# Topic detection rules (title/venue/keywords)
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
# Priority: if multiple rules match, pick earlier in this list
PRIORITY = {cat: i for i, cat in enumerate(["Quantum", "Programming Model", "Edge/IoT", "AI", "Architecture", "Applications", "HPC"])}

# ------------------------------
# BibTeX Parsing (tolerant, no external libs)
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
    # Collapse whitespace
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
    # Split entries at lines starting with @TYPE{
    entries = []
    pos = 0
    while True:
        m = re.search(r'@[A-Za-z]+\s*\{', text[pos:])
        if not m:
            break
        start = pos + m.start()
        # Find next @ to compute end
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

        # Normalize year
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
    # Venue fallback: common HPC venues
    venue = (entry.get("booktitle", "") + " " + entry.get("journal", "")).lower()
    if re.search(r"(sc\d{2}|ipdps|euro\-?mpi|cluster|hpcs|hpdc|ics|isc)", venue):
        return "HPC"
    return "Applications"

# ------------------------------
# HTML Generation
# ------------------------------
def _css_base() -> str:
    return r"""
:root{--bg:#ffffff;--fg:#111827;--muted:#6b7280;--border:#e5e7eb}
*{box-sizing:border-box}
body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Helvetica,Arial,sans-serif;background:#fff;color:#111827}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--border);z-index:1000}
header .wrap{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:12px 16px}
.filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--border);background:#fff}
.filter{display:inline-flex;align-items:center;gap:6px;margin:4px}
.filter input{position:absolute;left:-9999px;top:-9999px}
.filter label{display:inline-block;padding:8px 12px;border:1px solid var(--border);border-radius:999px;background:#fff;color:#111827;cursor:pointer}
.filter input:checked + label{background:#111827;color:#fff;border-color:#111827}
.actions{display:inline-flex;gap:8px;margin-left:12px}
.actions button{padding:8px 12px;border:1px solid var(--border);border-radius:8px;background:#fff;color:#111827;cursor:pointer}
.actions button:hover{background:#f9fafb}
main{display:grid;grid-template-columns:260px 1fr;gap:20px;padding:20px}
@media(max-width:900px){main{grid-template-columns:1fr}aside{order:2}}
aside{position:sticky;top:136px;align-self:start}
.aside-card{background:#fff;border:1px solid var(--border);border-radius:12px;padding:12px}
.aside-card h3{margin:8px 0;font-size:14px;color:#6b7280}
.aside-card a{display:block;padding:6px 8px;color:#111827;text-decoration:none;border-radius:6px}
.aside-card a:hover{background:#f9fafb}
.section{margin-bottom:16px;border:1px solid var(--border);border-radius:12px;background:#fff}
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

def _css_topic_styles() -> str:
    css = []
    for cat, color in COLORS.items():
        cls = re.sub(r"[^a-z0-9]", "-", cat.lower())
        tint = TINTS[cat]
        css.append(f".cat-{cls} .chip.cat{{border-color:{color}; color:{color}}}")
        css.append(f".cat-{cls} .card{{border-left:6px solid {color}; background:{tint};}}")
    return "\n".join(css) + "\n"

def _build_sidebar_links(by_year) -> str:
    links = []
    for y in sorted(by_year.keys(), key=lambda yy: (yy == "Unknown", -int(yy) if yy.isdigit() else 0)):
        links.append(f'<a href="#y-{html.escape(y)}">{html.escape(y)}<span class="badge">{len(by_year[y])}</span></a>')
    return "\n".join(links)

def _bold_name(text: str) -> str:
    if not text:
        return ""
    # Highlight Martin Schulz in author list, if present
    return re.sub(r'(Schulz,\s*Martin|Martin\s*Schulz)', r'<b>\1</b>', html.escape(text))

def generate_html(entries, outfile: Path, use_js_filters: bool = True):
    # Remove preprints & classify
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

    # Build CSS
    css = _css_base() + _css_topic_styles()

    # Filter UI
    filter_inputs_labels = "\n".join(
        f'<span class="filter"><input type="checkbox" id="filter-{re.sub("[^a-z0-9]","-", c.lower())}" checked>'
        f'<label for="filter-{re.sub("[^a-z0-9]","-", c.lower())}">{html.escape(c)}</label></span>'
        for c in CATS
    )

    # Sidebar
    sidebar_links = _build_sidebar_links(by_year)

    # Build section content
    sections_html = []
    entry_counter = 0
    sorted_years = sorted(by_year.keys(), key=lambda yy: (yy == "Unknown", -int(yy) if yy.isdigit() else 0))

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

            cards.append(f"""
        <div class="cat-{cls}">
        <article class="card" data-year="{html.escape(y)}" data-type="{html.escape(etype)}" data-category="{html.escape(cat)}">
            <div class="title">{title}</div>
            <div class="meta">{authors}{(' • ' + meta) if meta else ''}</div>
            <div class="chips">
                <span class="chip cat">{html.escape(cat)}</span>
                {'<span class="chip">Key: ' + html.escape(key) + '</span>' if key else ''}
                <span class="chip">{html.escape(etype)}</span>
            </div>
            <input type="checkbox" id="{bib_id}" class="bib" />
            <label for="{bib_id}" class="biblabel">Show BibTeX</label>
            <pre class="bib">{raw_bib}</pre>
        </article>
        </div>
        """)
        sections_html.append(f"""
    <section class="section" id="y-{html.escape(y)}">
        <input type="checkbox" id="cb-{html.escape(y)}" class="year" checked>
        <label for="cb-{html.escape(y)}" class="year-toggle">{html.escape(y)} <span class="badge">{len(cards)}</span></label>
        <div class="content">
            {''.join(cards)}
        </div>
    </section>
    """)

    # JS filtering (robust mode) or pure CSS filtering
    js = ""
    if use_js_filters:
        js = r"""
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
  // Hook up changes
  cats.forEach(c=>{
    const cb = document.getElementById(idFor(c));
    if(cb){ cb.addEventListener('change', applyFilters); }
  });
  // All / None
  const allBtn = document.getElementById('btnAll');
  const noneBtn = document.getElementById('btnNone');
  if(allBtn) allBtn.addEventListener('click', ()=>{ cats.forEach(c=>{ const cb=document.getElementById(idFor(c)); if(cb){ cb.checked=true; } }); applyFilters(); });
  if(noneBtn) noneBtn.addEventListener('click', ()=>{ cats.forEach(c=>{ const cb=document.getElementById(idFor(c)); if(cb){ cb.checked=false; } }); applyFilters(); });
  // Initial
  applyFilters();
})();
"""
    else:
        # Pure CSS sibling filters: inputs must be top-level siblings of <main>
        css_filters = []
        for cat in CATS:
            cls = re.sub("[^a-z0-9]", "-", cat.lower())
            css_filters.append(f"#filter-{cls}:not(:checked) ~ main .card[data-category='{cat}']{{display:none}}")
        css += "\n" + "\n".join(css_filters) + "\n"

    # Build final HTML
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Publications – Martin Schulz</title>
<style>
{css}
</style>
</head>
<body id="top">
<header>
  <div class="wrap">
    <strong>Topic filters</strong>
    <span class="actions">
      <button id="btnAll">All</button>
      <button id="btnNone">None</button>
    </span>
  </div>
</header>
<div class="filters" aria-label="Topic filters">
  {filter_inputs_labels}
</div>
<main>
  <aside>
    <div class="aside-card">
      <h3>Jump to year</h3>
      {_build_sidebar_links(by_year)}
    </div>
  </aside>
  <div>
    {''.join(sections_html)}
  </div>
</main>
<a href="#top" id="toTop" title="Back to top">Top</a>
<div class="footer">Auto-generated from BibTeX. Entries shown (preprints removed): {len(filtered)}. Years: {len(sorted_years)}.</div>
<script>
{js}
</script>
</body>
</html>
"""
    outfile.write_text(html_doc, encoding="utf-8")
    print(json.dumps({"entries_shown": len(filtered), "years": len(sorted_years), "out": str(outfile)}))


# ------------------------------
# CLI
# ------------------------------
def main():
    ap = argparse.ArgumentParser(description="Generate publications HTML from a BibTeX file.")
    ap.add_argument("bib_file", type=Path, help="Input BibTeX file")
    ap.add_argument("out_html", type=Path, help="Output HTML file")
    ap.add_argument("--no-js-filters", action="store_true", help="Use pure CSS sibling filters (no JavaScript)")
    args = ap.parse_args()

    text = args.bib_file.read_text(encoding="utf-8")
    entries = parse_bibtex_text(text)
    generate_html(entries, args.out_html, use_js_filters=not args.no_js_filters)


if __name__ == "__main__":
    main()

