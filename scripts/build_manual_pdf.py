"""Build docs/USER_MANUAL.pdf from docs/USER_MANUAL.md.

Renders the Markdown manual to HTML and prints it to PDF with a headless
Microsoft Edge (or Google Chrome), so tables, screenshots and symbols come
out exactly as in the browser. Re-run after editing the manual:

    pip install markdown-it-py
    python scripts/build_manual_pdf.py
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = PROJECT_ROOT / "docs"
SOURCE = DOCS_DIR / "USER_MANUAL.md"
OUTPUT = DOCS_DIR / "USER_MANUAL.pdf"

# Chrome first: a headless Edge launched while the user's own Edge is
# already running can hand off to it and exit without writing the PDF.
_BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

_CSS = """
@page {
  size: Letter;
  margin: 18mm 16mm 20mm 16mm;
  @bottom-center { content: "Electromagnet & VNA Control -- User Manual   |   " counter(page) " / " counter(pages);
                   font: 8.5pt "Segoe UI", Arial, sans-serif; color: #6b7280; }
}
* { box-sizing: border-box; }
body { font: 10.5pt/1.5 "Segoe UI", Arial, sans-serif; color: #1b1f23; margin: 0; }
h1 { font-size: 23pt; margin: 0 0 .4em; padding-bottom: .25em; border-bottom: 3px solid #1a4d8f; color: #12335e; }
h2 { font-size: 15.5pt; margin: 1.7em 0 .5em; padding-bottom: .15em; border-bottom: 1px solid #c8ccd0; color: #12335e; }
h3 { font-size: 12.5pt; margin: 1.4em 0 .4em; color: #1a4d8f; }
h4 { font-size: 11pt; margin: 1.1em 0 .3em; }
h1, h2, h3, h4 { break-after: avoid; }
p { margin: .5em 0; }
a { color: #1a4d8f; text-decoration: none; }
hr { border: 0; border-top: 1px solid #d0d7de; margin: 1.2em 0; }
code { font: 9pt Consolas, "Courier New", monospace; background: #eff1f4; padding: 0 3px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 4px; padding: 8px 10px;
      white-space: pre-wrap; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 8.5pt; line-height: 1.35; }
blockquote { margin: .8em 0; padding: .3em 1em; border-left: 4px solid #1a4d8f; background: #f3f7fc; }
blockquote p { margin: .35em 0; }
ul, ol { margin: .4em 0; padding-left: 1.6em; }
li { margin: .15em 0; }
table { border-collapse: collapse; width: 100%; margin: .7em 0; font-size: 9.3pt; }
th, td { border: 1px solid #c8ccd0; padding: 4px 7px; vertical-align: top; text-align: left; }
th { background: #eaf0f8; }
tr { break-inside: avoid; }
img { max-width: 100%; display: block; margin: .7em auto; border: 1px solid #d0d7de; }
p:has(> img) { break-inside: avoid; }
"""


def _find_browsers() -> list[str]:
    found = [c for c in _BROWSER_CANDIDATES if Path(c).exists()]
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        path = shutil.which(name)
        if path and path not in found:
            found.append(path)
    if not found:
        raise SystemExit("No Google Chrome or Microsoft Edge found to render the PDF.")
    return found


def _github_slug(text: str, seen: dict[str, int]) -> str:
    """Same heading ids GitHub generates, so the manual's in-page links work
    both on GitHub and in the PDF."""
    slug = re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def _render_html(markdown_text: str) -> str:
    try:
        from markdown_it import MarkdownIt
    except ImportError:
        raise SystemExit("Missing dependency: pip install markdown-it-py")

    md = MarkdownIt("commonmark").enable("table")
    tokens = md.parse(markdown_text)

    seen: dict[str, int] = {}
    for i, tok in enumerate(tokens):
        if tok.type == "heading_open":
            inline = tokens[i + 1]
            text = "".join(
                c.content for c in (inline.children or []) if c.type in ("text", "code_inline")
            )
            tok.attrSet("id", _github_slug(text, seen))

    body = md.renderer.render(tokens, md.options, {})
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Electromagnet &amp; VNA Control -- User Manual</title>"
        f"<base href='{DOCS_DIR.as_uri()}/'>"
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


def main() -> int:
    page = _render_html(SOURCE.read_text(encoding="utf-8"))

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        html_path = Path(tmp) / "manual.html"
        html_path.write_text(page, encoding="utf-8")
        for browser in _find_browsers():
            OUTPUT.unlink(missing_ok=True)
            cmd = [
                browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
                f"--user-data-dir={Path(tmp) / Path(browser).stem}",
                f"--print-to-pdf={OUTPUT}", html_path.as_uri(),
            ]
            subprocess.run(cmd, timeout=180, capture_output=True)
            if OUTPUT.exists() and OUTPUT.stat().st_size > 0:
                print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB) using {Path(browser).name}")
                return 0

    print("No browser produced the PDF", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
