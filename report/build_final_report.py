"""Builds report/final_report.pdf from report/FINAL_REPORT.md (Markdown -> styled HTML -> PDF with headless Chrome).

FINAL_REPORT.md is the source and also reads directly on GitHub; images point into results/.
Run:  python3 report/build_final_report.py   (needs python-markdown and google-chrome / chromium)
"""
import shutil
import subprocess
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
SRC, HTML, PDF = HERE / "FINAL_REPORT.md", HERE / "final_report.html", HERE / "final_report.pdf"

CSS = """
@page { size: A4; margin: 18mm 17mm 18mm 17mm; }
body { font-family: Calibri, Carlito, 'Liberation Sans', Arial, sans-serif; font-size: 10.3pt; line-height: 1.42; color: #2b3440; }
h1 { font-family: Georgia, 'DejaVu Serif', serif; color: #14213d; font-size: 23pt; line-height: 1.15; margin: 0 0 6pt; }
h1 + p strong { font-size: 12.5pt; color: #2f5d7c; }
h2 { font-family: Georgia, 'DejaVu Serif', serif; color: #14213d; font-size: 15pt; margin: 18pt 0 6pt;
     border-bottom: 1.5px solid #14213d; padding-bottom: 3pt; break-after: avoid; }
h3 { color: #b4472e; font-size: 11.5pt; margin: 12pt 0 4pt; break-after: avoid; }
p { margin: 3pt 0 6pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.2pt; break-inside: avoid; }
th { text-align: left; color: #14213d; border-top: 1.5px solid #14213d; border-bottom: 1.5px solid #14213d; padding: 3pt 5pt; }
td { border-bottom: 1px solid #dde2e8; padding: 2.5pt 5pt; vertical-align: top; }
tr:nth-child(even) td { background: #f6f8fa; }
img { display: block; max-width: 100%; max-height: 105mm; margin: 6pt auto 10pt; break-inside: avoid; }
hr { border: none; border-top: 1px solid #c9d0d9; margin: 14pt 0; }
code, pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 8.4pt; }
pre { background: #f4f6f9; padding: 6pt 8pt; border-left: 3px solid #2f5d7c; white-space: pre-wrap; }
li { margin-bottom: 2pt; }
a { color: #2f5d7c; }
h2:first-of-type { break-before: avoid; }
"""


def _blank_before_lists(text):
    """GitHub starts a list right after a paragraph line; Python-Markdown needs a blank line first."""
    import re
    item = re.compile(r"^(\s*)([-*]|\d+\.) ")
    out, fence = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence
        if not fence and item.match(line) and out and out[-1].strip() and not item.match(out[-1]) and not out[-1].startswith("  "):
            out.append("")
        out.append(line)
    return "\n".join(out)


def main():
    body = markdown.markdown(_blank_before_lists(SRC.read_text(encoding="utf-8")), extensions=["tables", "fenced_code", "sane_lists"])
    HTML.write_text(f'<!doctype html><html><head><meta charset="utf-8"><title>Final Report</title><style>{CSS}</style></head>'
                    f"<body>{body}</body></html>", encoding="utf-8")
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)), None)
    if chrome is None:
        raise SystemExit("needs google-chrome or chromium for the PDF; the HTML is at " + str(HTML))
    subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--allow-file-access-from-files",
                    f"--print-to-pdf={PDF}", HTML.as_uri()], check=True, capture_output=True)
    print("wrote", PDF)


if __name__ == "__main__":
    main()
