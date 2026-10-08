"""Typeset a markdown report to PDF: markdown -> print-styled HTML -> headless Chrome.

Usage: uv run --no-project --with markdown python build_pdf.py <in.md> <out.pdf> [--title T] [--subtitle S]
"""

import argparse
import html
import re
import subprocess
from datetime import date
from pathlib import Path

import markdown

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm;
  @bottom-right { content: counter(page) " / " counter(pages); font: 8pt 'IBM Plex Mono', monospace; color: #6B7A78; }
  @bottom-left { content: "ygg-atlas · EMAPI data discovery · confidential"; font: 8pt 'IBM Plex Mono', monospace; color: #6B7A78; } }
@page :first { @bottom-left { content: none; } @bottom-right { content: none; } }
* { box-sizing: border-box; }
html { font-size: 10pt; }
body { font-family: 'IBM Plex Sans', 'Helvetica Neue', Arial, sans-serif; color: #15201F; line-height: 1.5; margin: 0; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: flex-end; padding-bottom: 30mm; page-break-after: always; border-left: 6px solid #0E7068; padding-left: 12mm; }
.cover .eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 9pt; letter-spacing: .08em; text-transform: uppercase; color: #56676A; }
.cover h1 { font-family: 'IBM Plex Sans Condensed', 'Arial Narrow', sans-serif; font-size: 34pt; line-height: 1.05; margin: 6mm 0 4mm; border: 0; }
.cover .sub { font-size: 13pt; color: #334240; max-width: 140mm; }
.cover .meta { margin-top: 10mm; font-family: 'IBM Plex Mono', monospace; font-size: 9pt; color: #56676A; }
h1, h2, h3, h4 { font-family: 'IBM Plex Sans Condensed', 'Arial Narrow', sans-serif; line-height: 1.2; page-break-after: avoid; break-after: avoid; }
h1 { font-size: 20pt; margin: 0 0 4mm; padding-bottom: 2mm; border-bottom: 2px solid #0E7068; page-break-before: always; }
h1:first-of-type { page-break-before: auto; }
h2 { font-size: 14pt; margin: 7mm 0 2mm; color: #0E4F49; }
h3 { font-size: 11.5pt; margin: 5mm 0 1.5mm; }
h4 { font-size: 10pt; margin: 4mm 0 1mm; color: #334240; }
p, li { orphans: 3; widows: 3; }
p { margin: 0 0 2.4mm; }
ul, ol { margin: 0 0 2.4mm; padding-left: 5mm; }
li { margin: 0.6mm 0; }
a { color: #0E7068; text-decoration: none; }
code { font-family: 'IBM Plex Mono', Menlo, monospace; font-size: 8.4pt; background: #EEF3F2; padding: 0 1mm; border-radius: 2px; }
pre { font-family: 'IBM Plex Mono', Menlo, monospace; font-size: 7.6pt; background: #F3F6F6; border: 1px solid #D3DCDB; border-radius: 3px; padding: 2.5mm; white-space: pre-wrap; word-break: break-word; page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { margin: 3mm 0; padding: 2mm 4mm; border-left: 3px solid #0E7068; background: #EEF6F5; color: #203230; }
table { border-collapse: collapse; width: 100%; max-width: 100%; table-layout: auto; margin: 2.5mm 0 4mm; font-size: 8.2pt; page-break-inside: auto; }
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th { background: #E5EEED; text-align: left; font-weight: 600; font-family: 'IBM Plex Sans Condensed', 'Arial Narrow', sans-serif; font-size: 8.4pt; }
th, td { border: 1px solid #D3DCDB; padding: 1.4mm 2mm; vertical-align: top; overflow-wrap: break-word; hyphens: manual; }
td code, th code { overflow-wrap: anywhere; word-break: break-all; }
tbody tr:nth-child(even) td { background: #FAFCFC; }
hr { border: 0; border-top: 1px solid #D3DCDB; margin: 5mm 0; }
.nw { white-space: nowrap; }
.lbl { font-family: 'IBM Plex Mono', monospace; font-size: 7.4pt; padding: 0 1.2mm; border-radius: 2px; white-space: nowrap; }
.lbl-v { background: #DDF0EE; color: #0B5D56; }
.lbl-s { background: #E9EAF7; color: #3A3F8F; }
.lbl-g { background: #F7EBD9; color: #8A500A; }
.toc { page-break-after: always; }
.toc h1 { page-break-before: auto; }
.toc ol { list-style: none; padding-left: 0; }
.toc li { padding: 1mm 0; border-bottom: 1px dotted #D3DCDB; }
.toc li.l3 { padding-left: 6mm; font-size: 9pt; color: #334240; border-bottom: 0; }
"""

LABELS = {
    "VALIDATED": "lbl lbl-v",
    "STRUCTURAL": "lbl lbl-s",
    "NEEDS-GRANT": "lbl lbl-g",
}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build(md_text: str, title: str, subtitle: str) -> str:
    body = markdown.markdown(
        md_text, extensions=["tables", "fenced_code", "sane_lists", "toc", "attr_list"],
        extension_configs={"toc": {"slugify": lambda v, s: slug(v)}},
    )
    # colour-code evidence labels wherever they appear as whole words
    for word, cls in LABELS.items():
        body = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-])", f'<span class="{cls}">{word}</span>', body)
    # keep ids like AF-31, H49, E2 on one line (outside tags only)
    body = re.sub(r"(?<![\w#-])([A-Z]{1,3}-\d{1,3})(?![\w-])(?![^<]*>)", r'<span class="nw">\1</span>', body)
    # table of contents from h1/h2
    heads = re.findall(r'<h([12]) id="([^"]+)">(.*?)</h\1>', body)
    toc_items = "".join(
        f'<li class="l{3 if lvl == "2" else 2}"><a href="#{hid}">{re.sub("<[^>]+>", "", txt)}</a></li>'
        for lvl, hid, txt in heads
    )
    cover = (
        '<section class="cover">'
        '<div class="eyebrow">ygg-atlas · data discovery report</div>'
        f"<h1>{html.escape(title)}</h1>"
        f'<div class="sub">{html.escape(subtitle)}</div>'
        f'<div class="meta">Prepared {date.today():%d %b %Y} · confidential · internal use</div>'
        "</section>"
    )
    toc = f'<section class="toc"><h1>Contents</h1><ol>{toc_items}</ol></section>'
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
        "&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:ital,wght@0,400;0,600;1,400&display=swap'>"
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f"{cover}{toc}<main>{body}</main></body></html>"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--title", default="EMAPI Data Discovery")
    ap.add_argument("--subtitle", default="")
    a = ap.parse_args()
    html_path = Path(a.out).resolve().with_suffix(".html")
    html_path.write_text(build(Path(a.src).read_text(), a.title, a.subtitle))
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
         "--virtual-time-budget=20000", f"--print-to-pdf={Path(a.out).resolve()}", html_path.as_uri()],
        check=True, capture_output=True, timeout=900,
    )
    print(f"wrote {a.out} ({Path(a.out).stat().st_size // 1024} KB) and {html_path}")


if __name__ == "__main__":
    main()
