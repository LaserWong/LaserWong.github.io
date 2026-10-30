import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import arxiv_fulltext as ft
import generate_arxiv_daily as daily

BODY = ("The numerical simulation establishes a finite size scaling result for the quantum spin model. " * 25)
HTML = ('<html><nav>outside navigation</nav><article class="ltx_document">'
        '<section class="ltx_section"><h2>Introduction</h2><p>' + BODY + '</p>'
        '<math alttext="E=mc^2"><mi>duplicate-math</mi></math>'
        '<script>untrusted script content</script></section>'
        '<section class="ltx_appendix"><h2>Appendix</h2><p>TAIL_RESULT</p></section>'
        '</article></html>').encode()


def pdf_bytes(texts):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 10 Tf 10 700 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class ExtractionTests(unittest.TestCase):
    def test_html_reads_appendix_and_math_without_navigation(self):
        text = ft.extract_html(HTML)
        self.assertIn("TAIL_RESULT", text)
        self.assertIn("$E=mc^2$", text)
        self.assertNotIn("outside navigation", text)
        self.assertNotIn("untrusted script content", text)
        self.assertNotIn("duplicate-math", text)

    def test_html_requires_article_sections_and_substantial_text(self):
        for data in [b"<html>error page</html>", ('<article class="ltx_document">'+BODY+'</article>').encode(), b'<article class="ltx_document"><section class="ltx_section">short</section></article>']:
            with self.subTest(data=data[:40]), self.assertRaises(ft.FullTextError):
                ft.extract_html(data)

    def test_oversize_html_rejected_without_silent_truncation(self):
        with self.assertRaisesRegex(ft.FullTextError, "text_too_long"):
            ft.extract_html(HTML, 1000)

    def test_pdf_includes_every_page(self):
        text, pages = ft.extract_pdf(pdf_bytes([BODY, BODY + " TAIL_RESULT"]))
        self.assertEqual(pages, 2)
        self.assertIn("[Page 2/2]", text)
        self.assertTrue(text.endswith("TAIL_RESULT"))

    def test_pdf_worker_extracts_complete_text(self):
        text, pages = ft.extract_pdf_bounded(pdf_bytes([BODY]), ft.DEFAULT_MAX_CHARS)
        self.assertEqual(pages, 1)
        self.assertIn("finite size scaling", text)

    def test_scanned_or_missing_page_triggers_abstract_fallback(self):
        with self.assertRaisesRegex(ft.FullTextError, "pdf_missing_text_page"):
            ft.extract_pdf(pdf_bytes([BODY, " "]))

    def test_pdf_page_and_character_limits(self):
        data = pdf_bytes([BODY, BODY])
        with self.assertRaisesRegex(ft.FullTextError, "pdf_page_limit"):
            ft.extract_pdf(data, max_pages=1)
        with self.assertRaisesRegex(ft.FullTextError, "text_too_long"):
            ft.extract_pdf(data, max_chars=1000)


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.loader = ft.FullTextLoader(Path(self.folder.name))

    def test_html_first_and_disk_cache(self):
        with patch.object(self.loader, "download", return_value=(HTML, "https://arxiv.org/html/2610.10000v1")) as download:
            first = self.loader.get("2610.10000")
            self.assertEqual(first["source"], "html")
            self.assertEqual(download.call_count, 1)
            self.assertEqual(self.loader.get("2610.10000"), first)
        other = ft.FullTextLoader(Path(self.folder.name))
        with patch.object(other, "download", side_effect=AssertionError("network should not run")):
            self.assertEqual(other.get("2610.10000"), first)

    def test_html_missing_uses_pdf(self):
        with patch.object(self.loader, "download", side_effect=[ft.FullTextError("http_404"), (b"pdf", "https://arxiv.org/pdf/2610.10000")]) as download:
            with patch.object(ft, "extract_pdf_bounded", return_value=(BODY, 2)):
                result = self.loader.get("2610.10000")
        self.assertEqual(result["source"], "pdf")
        self.assertEqual(download.call_count, 2)

    def test_all_sources_fail_returns_explicit_abstract_metadata(self):
        with patch.object(self.loader, "download", side_effect=ft.FullTextError("network_failure")):
            result = self.loader.get("2610.10000")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["source"], "abstract")
        self.assertIn("pdf:network_failure", result["status"])
        self.assertEqual(list(Path(self.folder.name).glob("*.json")), [])

    def test_invalid_ids_cannot_escape_cache_directory(self):
        with patch.object(self.loader, "download") as download:
            self.assertEqual(self.loader.get("../../secret")["status"], "invalid_id")
        download.assert_not_called()

    def test_403_stops_further_downloads_for_this_run(self):
        error = urllib.error.HTTPError("https://arxiv.org/html/2610.10000", 403, "denied", {}, io.BytesIO())
        with patch.object(ft.urllib.request, "urlopen", side_effect=error) as request:
            self.loader.get("2610.10000")
            self.loader.get("2610.10001")
        self.assertEqual(request.call_count, 1)

    def test_download_byte_limit(self):
        response = Mock()
        response.read.return_value = b"x" * 101
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(ft, "DEFAULT_MAX_BYTES", 100), patch.object(ft.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(ft.FullTextError, "download_too_large"):
                self.loader.download("https://arxiv.org/html/2610.10000")

    def test_corrupt_disk_cache_is_refetched(self):
        for cached in ("broken", "[]", '{"paper_id":"2610.10000","text":"bad"}'):
            self.loader.memory.clear()
            (Path(self.folder.name) / "2610.10000.json").write_text(cached, encoding="utf-8")
            with patch.object(self.loader, "download", return_value=(HTML, "https://arxiv.org/html/2610.10000")) as download:
                self.assertEqual(self.loader.get("2610.10000")["status"], "ok")
            self.assertEqual(download.call_count, 1)

    def test_parallel_callers_still_download_serially(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        import time
        active = 0
        peak = 0
        lock = threading.Lock()
        def download(url):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return HTML, url
        with patch.object(self.loader, "download", side_effect=download):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(self.loader.get, [f"2610.{10000+i}" for i in range(8)]))
        self.assertEqual(peak, 1)
        self.assertTrue(all(item["status"] == "ok" for item in results))


class DeepSeekEvidenceTests(unittest.TestCase):
    def test_fulltext_reaches_fallback_api(self):
        value = {"choices": [{"finish_reason": "stop", "message": {"content": "1. \u4f5c\u8005\u5b8c\u6210\u8ba1\u7b97\u3002\n2. \u7ed3\u679c\u63ed\u793a\u6807\u5ea6\u3002\n3. \u53ef\u7528\u4e8e\u57fa\u51c6\u6bd4\u8f83\u3002"}}], "usage": {}}
        with patch.object(daily, "post_json", return_value=value) as post:
            summary, _, _ = daily.summarize_with_deepseek("title", "abstract", {}, "key", "deepseek-reasoner", 8192, 180, full_text=BODY + " TAIL_RESULT")
        self.assertIsNotNone(summary)
        prompt = post.call_args.args[1]["messages"][1]["content"]
        self.assertIn("entire supplied physics paper", prompt)
        self.assertTrue(prompt.endswith("TAIL_RESULT"))


if __name__ == "__main__":
    unittest.main()
