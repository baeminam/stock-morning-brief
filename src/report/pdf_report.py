"""
PDF report generation via headless Chrome/Edge (--print-to-pdf).
No extra dependencies: ubuntu-latest GitHub runners ship Chrome,
and Windows ships Edge. Returns False gracefully when no browser is found.
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CANDIDATES = [
    # Linux (GitHub Actions ubuntu-latest)
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    # Windows
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def _find_browser() -> str | None:
    for cand in CANDIDATES:
        if Path(cand).is_file():
            return cand
        resolved = shutil.which(cand)
        if resolved:
            return resolved
    return None


def build_pdf(html_path: str | Path, pdf_path: str | Path | None = None, timeout: int = 120) -> Path | None:
    """Render an HTML file to PDF with a headless browser. Returns pdf path or None."""
    html_path = Path(html_path).resolve()
    pdf_path = (Path(pdf_path) if pdf_path else html_path.with_suffix(".pdf")).resolve()

    browser = _find_browser()
    if not browser:
        logger.warning("No Chrome/Edge found; skipping PDF generation")
        return None

    try:
        subprocess.run(
            [
                browser,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                html_path.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            logger.info("PDF report saved: %s (%d bytes)", pdf_path, pdf_path.stat().st_size)
            return pdf_path
        logger.warning("PDF generation produced no output")
        return None
    except Exception as e:
        logger.warning("PDF generation failed: %s", e)
        return None
