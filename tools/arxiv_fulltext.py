"""Bounded arXiv HTML/PDF text extraction, with explicit abstract fallback."""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import threading
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

ID_PATTERN = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\Z")
DEFAULT_MAX_CHARS = 240_000
DEFAULT_MAX_BYTES = 25 * 1024 * 1024


class FullTextError(ValueError):
    pass


def validate_text(text: str, max_chars: int) -> str:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < 1000 or len(re.findall(r"[A-Za-z]{2,}", text)) < 100:
        raise FullTextError("insufficient_text")
    if len(text) > max_chars:
        raise FullTextError("text_too_long")
    if text.count("\ufffd") > len(text) * 0.01:
        raise FullTextError("unreadable_text")
    return text


def extract_html(data: bytes, max_chars: int = DEFAULT_MAX_CHARS) -> str:
    soup = BeautifulSoup(data, "html.parser")
    article = soup.select_one("article.ltx_document, .ltx_document")
    if article is None or article.select_one(".ltx_section, .ltx_appendix") is None:
        raise FullTextError("not_fulltext_html")
    for tag in article.select("script, style, nav, .ltx_page_navbar, .ltx_page_footer"):
        tag.decompose()
    # Preserve LaTeX rather than concatenating every MathML presentation variant.
    for math in article.find_all("math"):
        if math.get("alttext"):
            math.replace_with(" $" + math["alttext"] + "$ ")
    for img in article.find_all("img"):
        if img.get("alt"):
            img.replace_with(" " + img["alt"] + " ")
    return validate_text(article.get_text("\n", strip=True), max_chars)


def extract_pdf(data: bytes, max_chars: int = DEFAULT_MAX_CHARS, max_pages: int = 120) -> tuple[str, int]:
    from pypdf import PdfReader

    if not data.lstrip().startswith(b"%PDF-"):
        raise FullTextError("not_pdf")
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise FullTextError("encrypted_pdf")
    count = len(reader.pages)
    if not count or count > max_pages:
        raise FullTextError("pdf_page_limit")
    parts = []
    total = 0
    for number, page in enumerate(reader.pages, 1):
        stream = page.get_contents()
        if stream and len(stream.get_data()) > 20 * 1024 * 1024:
            raise FullTextError("pdf_page_too_large")
        text = (page.extract_text() or "").strip()
        if len(text) < 40:
            raise FullTextError("pdf_missing_text_page")
        part = f"[Page {number}/{count}]\n{text}"
        parts.append(part)
        total += len(part) + 2
        if total > max_chars:
            raise FullTextError("text_too_long")
    return validate_text("\n\n".join(parts), max_chars), count


def extract_pdf_bounded(data: bytes, max_chars: int, timeout: int = 60) -> tuple[str, int]:
    # A malformed PDF must not hang the daily job or exhaust the parent's memory.
    with tempfile.TemporaryDirectory(prefix="arxiv-pdf-") as folder:
        path = Path(folder) / "paper.pdf"
        path.write_bytes(data)
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--pdf", str(path), "--max-chars", str(max_chars)],
                capture_output=True, text=True, encoding="utf-8", timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired:
            raise FullTextError("pdf_extraction_timeout") from None
        if result.returncode:
            raise FullTextError("pdf_extraction_failed")
        value = json.loads(result.stdout)
        if value.get("error"):
            raise FullTextError(value["error"])
        return value["text"], value["pages"]


class FullTextLoader:
    def __init__(self, cache_dir: Path, *, max_chars: int = DEFAULT_MAX_CHARS,
                 timeout: int = 45, min_interval: float = 3.0,
                 log: Callable[[str], None] = print):
        self.cache_dir = cache_dir
        self.max_chars = max_chars
        self.timeout = timeout
        self.min_interval = max(3.0, min_interval)
        self.log = log
        self.last_request = 0.0
        self.blocked = False
        self.memory: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def download(self, url: str) -> tuple[bytes, str]:
        for attempt in range(2):
            delay = self.min_interval - (time.monotonic() - self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            req = urllib.request.Request(url, headers={
                "User-Agent": "ArxivDailySelection/2.0 (+https://laserwong.github.io)",
                "Accept": "text/html,application/pdf",
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    data = response.read(DEFAULT_MAX_BYTES + 1)
                    if len(data) > DEFAULT_MAX_BYTES:
                        raise FullTextError("download_too_large")
                    return data, response.geturl()
            except urllib.error.HTTPError as exc:
                if exc.code in {403, 429}:
                    self.blocked = True
                    raise FullTextError(f"access_limited_{exc.code}") from None
                if exc.code not in {408, 500, 502, 503, 504} or attempt:
                    raise FullTextError(f"http_{exc.code}") from None
            except (OSError, TimeoutError):
                if attempt:
                    raise FullTextError("network_failure") from None
        raise FullTextError("network_failure")

    def get(self, paper_id: str) -> dict[str, Any]:
        with self.lock:
            return self._get(paper_id)

    def _get(self, paper_id: str) -> dict[str, Any]:
        if not ID_PATTERN.fullmatch(paper_id):
            return {"text": "", "status": "invalid_id", "source": "abstract", "url": "", "pages": 0}
        if paper_id in self.memory:
            return self.memory[paper_id]
        cache_path = self.cache_dir / (paper_id.replace("/", "_") + ".json")
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (isinstance(cached, dict) and cached.get("status") == "ok"
                    and cached.get("paper_id") == paper_id and cached.get("source") in {"html", "pdf"}
                    and isinstance(cached.get("url"), str) and isinstance(cached.get("pages"), int)):
                validate_text(cached["text"], self.max_chars)
                self.memory[paper_id] = cached
                return cached
        except (OSError, ValueError, KeyError, TypeError):
            pass
        reasons = []
        for source in ("html", "pdf"):
            if self.blocked:
                reasons.append("access_limited")
                break
            url = f"https://arxiv.org/{source}/{paper_id}"
            try:
                data, resolved_url = self.download(url)
                if source == "html":
                    text, pages = extract_html(data, self.max_chars), 0
                else:
                    text, pages = extract_pdf_bounded(data, self.max_chars)
                result = {"paper_id": paper_id, "text": text, "status": "ok",
                          "source": source, "url": resolved_url, "pages": pages}
                self.memory[paper_id] = result
                try:
                    self.cache_dir.mkdir(parents=True, exist_ok=True)
                    temp = cache_path.with_suffix(".tmp")
                    temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                    temp.replace(cache_path)
                except OSError:
                    self.log("      [fulltext] Cache write unavailable; continuing without disk cache")
                return result
            except FullTextError as exc:
                reasons.append(f"{source}:{exc}")
                if str(exc) in {"text_too_long", "download_too_large"}:
                    break
            except Exception as exc:
                # Parser failures affect this paper only; never log downloaded content.
                reasons.append(f"{source}:{type(exc).__name__}")
        result = {"text": "", "status": ";".join(reasons) or "unavailable",
                  "source": "abstract", "url": "", "pages": 0}
        self.memory[paper_id] = result
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    args = parser.parse_args()
    try:
        text, pages = extract_pdf(Path(args.pdf).read_bytes(), args.max_chars)
        print(json.dumps({"text": text, "pages": pages}, ensure_ascii=True))
    except FullTextError as exc:
        print(json.dumps({"error": str(exc)}))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
