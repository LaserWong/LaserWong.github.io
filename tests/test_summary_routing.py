import contextlib
import io
import http.client
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import generate_arxiv_daily as daily


FIELDS = {
    "what_done": "\u4f5c\u8005\u7528\u5f20\u91cf\u7f51\u7edc\u8ba1\u7b97\u81ea\u65cb\u94fe\u57fa\u6001\u3002",
    "selling_point": "\u8ba1\u7b97\u63ed\u793a\u4e86\u6709\u9650\u5c3a\u5bf8\u4e0b\u7684\u4e34\u754c\u6807\u5ea6\u3002",
    "outlook": "\u8fd9\u4e3a\u6bd4\u8f83\u5176\u4ed6\u591a\u4f53\u6c42\u89e3\u65b9\u6cd5\u63d0\u4f9b\u4e86\u57fa\u51c6\u3002",
}
SUMMARY = "\n".join(f"{i}. {s}" for i, s in enumerate(FIELDS.values(), 1))
PAPER = {
    "id": "test.00001", "category": "cond-mat", "title": "Spin chain theory",
    "abstract": "We compute spin chain ground states with tensor networks.",
    "url": "https://arxiv.org/abs/test.00001",
}
USAGE = {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}


def response(fields=None, **overrides):
    result = {
        "status": "completed",
        "output": [{"type": "reasoning"}, {
            "type": "message", "content": [{
                "type": "output_text", "text": json.dumps(FIELDS if fields is None else fields),
            }],
        }],
        "usage": {"input_tokens": 20, "output_tokens": 30, "total_tokens": 50},
    }
    result.update(overrides)
    return result


def http_error(code, error_code="", retry_after=None):
    body = json.dumps({"error": {"code": error_code, "message": "PRIVATE_ERROR_TEXT"}}).encode()
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError(daily.OPENAI_ENDPOINT, code, "error", headers, io.BytesIO(body))


class ContextTestCase(unittest.TestCase):
    def enterContext(self, manager):
        result = manager.__enter__()
        self.addCleanup(manager.__exit__, None, None, None)
        return result


class OpenAITests(ContextTestCase):
    def setUp(self):
        self.post = self.enterContext(patch.object(daily, "post_json", return_value=response()))
        self.sleep = self.enterContext(patch.object(daily.time, "sleep"))
        self.output = self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def call(self, **kwargs):
        return daily.summarize_with_openai("title", "abstract", kwargs.pop("cache", {}), "test-key", **kwargs)

    def test_structured_payload_and_usage(self):
        summary, usage, status = self.call()
        self.assertEqual((summary, status), (SUMMARY, "ok"))
        self.assertEqual(usage, {**USAGE, "requests": 1})
        url, payload = self.post.call_args.args
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(payload["model"], "gpt-6.1-sol")
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertEqual(payload["max_output_tokens"], 3072)
        self.assertNotIn("temperature", payload)

    def test_success_cache(self):
        cache = {}
        self.call(cache=cache)
        summary, usage, status = self.call(cache=cache)
        self.assertEqual((summary, status), (SUMMARY, "cached"))
        self.assertEqual(usage["requests"], 0)
        self.assertEqual(self.post.call_count, 1)
        self.call(cache=cache, model="another-model")
        self.assertEqual(self.post.call_count, 2)

    def test_no_key_makes_no_request(self):
        summary, _, status = daily.summarize_with_openai("a", "b", {}, "")
        self.assertEqual((summary, status), (None, "no_key"))
        self.post.assert_not_called()

    def test_permanent_errors_do_not_retry_or_log_error_text(self):
        for code, error_code, expected in [
            (429, "insufficient_quota", "quota_exhausted"),
            (402, "", "quota_exhausted"),
            (401, "", "authentication_failed"),
            (403, "", "permission_denied"),
            (404, "model_not_found", "model_unavailable"),
            (400, "", "http_400"),
        ]:
            with self.subTest(code=code):
                self.post.reset_mock()
                self.post.side_effect = http_error(code, error_code)
                self.assertEqual(self.call()[2], expected)
                self.assertEqual(self.post.call_count, 1)
        self.sleep.assert_not_called()
        self.assertNotIn("PRIVATE_ERROR_TEXT", self.output.getvalue())
        self.assertNotIn("test-key", self.output.getvalue())

    def test_transient_rate_limit_retries_then_succeeds(self):
        self.post.side_effect = [http_error(429, "rate_limit_exceeded", "5"), response()]
        summary, usage, status = self.call()
        self.assertEqual((summary, status), (SUMMARY, "ok"))
        self.assertEqual(usage["requests"], 2)
        self.sleep.assert_called_once_with(5)

    def test_server_error_retries_are_bounded(self):
        self.post.side_effect = [http_error(503) for _ in range(3)]
        self.assertEqual(self.call()[2], "http_503")
        self.assertEqual(self.post.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_timeout_retries_then_falls_back(self):
        self.post.side_effect = TimeoutError("PRIVATE_ERROR_TEXT")
        self.assertEqual(self.call()[2], "request_failure")
        self.assertEqual(self.post.call_count, 3)
        self.assertNotIn("PRIVATE_ERROR_TEXT", self.output.getvalue())

    def test_invalid_format_repair_preserves_all_billed_usage(self):
        self.post.side_effect = [response(fields={"what_done": "wrong"}), response()]
        summary, usage, status = self.call()
        self.assertEqual((summary, status), (SUMMARY, "ok"))
        self.assertEqual(usage["total_tokens"], 100)

    def test_incomplete_content_is_never_published(self):
        self.post.return_value = response(status="incomplete")
        self.assertEqual(self.call()[::2], (None, "incomplete"))
        self.assertEqual(self.post.call_count, 1)

    def test_refusal_is_never_published(self):
        self.post.return_value = response(output=[{
            "type": "message", "content": [{"type": "refusal", "refusal": "cannot answer"}],
        }])
        self.assertEqual(self.call()[::2], (None, "refusal"))
        self.assertEqual(self.post.call_count, 1)

    def test_json_error_in_success_http_response(self):
        self.post.return_value = {"status": "failed", "error": {"code": "insufficient_quota"}}
        self.assertEqual(self.call()[2], "quota_exhausted")
        self.assertEqual(self.post.call_count, 1)

    def test_invalid_responses_are_rejected(self):
        for bad in [
            response(output=[]), response(fields={}),
            response(fields={**FIELDS, "outlook": 123}),
            response(fields={**FIELDS, "outlook": "English only."}),
            response(fields={**FIELDS, "outlook": "\u7814" * 400}),
        ]:
            with self.subTest(bad=bad):
                self.assertIsNone(daily.parse_openai_summary(bad)[0])

    def test_malformed_usage_is_bounded(self):
        self.post.return_value = response(usage="bad")
        self.assertEqual(self.call()[2], "request_failure")
        self.assertEqual(self.post.call_count, 3)

    def test_interrupted_connection_is_retried(self):
        self.post.side_effect = [http.client.IncompleteRead(b"partial"), response()]
        self.assertEqual(self.call()[0], SUMMARY)
        self.assertEqual(self.post.call_count, 2)


class RoutingTests(ContextTestCase):
    def setUp(self):
        self.gpt = self.enterContext(patch.object(daily, "summarize_with_openai", return_value=(SUMMARY, {**USAGE, "requests": 1}, "ok")))
        self.ds = self.enterContext(patch.object(daily, "summarize_with_deepseek", return_value=(SUMMARY, USAGE, "ok")))
        self.translate = self.enterContext(patch.object(daily, "translate_full_abstract", return_value=None))
        self.enterContext(patch.object(daily, "fetch_authors", return_value=[]))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def enrich(self, papers=None, **kwargs):
        options = {"enable_translation": True, "enable_deepseek_summary": True,
                   "deepseek_api_key": "deepseek-test", "enable_openai_summary": True,
                   "openai_api_key": "openai-test"}
        options.update(kwargs)
        return daily.enrich_papers(papers or [PAPER], **options)

    def test_gpt_success_does_not_call_deepseek(self):
        papers, usage = self.enrich()
        self.assertEqual(papers[0]["summary_source"], "openai")
        self.assertEqual(papers[0]["summary_model"], "gpt-6.1-sol")
        self.assertEqual(usage["openai_total_tokens"], 50)
        self.assertEqual(usage["total_tokens"], 0)
        self.ds.assert_not_called()
        self.translate.assert_not_called()

    def test_quota_error_disables_gpt_for_rest_of_run_only(self):
        self.gpt.return_value = (None, {**USAGE, "requests": 1}, "quota_exhausted")
        papers, usage = self.enrich([PAPER, {**PAPER, "id": "test.00002"}])
        self.assertEqual(self.gpt.call_count, 1)
        self.assertEqual(self.ds.call_count, 2)
        self.assertTrue(all(p["summary_source"] == "deepseek" for p in papers))
        self.assertTrue(all(p["openai_status"] == "quota_exhausted" for p in papers))
        self.assertEqual(usage["openai_disabled"], 1)
        self.assertEqual(usage["openai_fallbacks"], 2)
        self.enrich()
        self.assertEqual(self.gpt.call_count, 2)

    def test_transient_error_allows_next_paper_gpt(self):
        self.gpt.side_effect = [(None, USAGE, "rate_limited"), (SUMMARY, USAGE, "ok")]
        papers, _ = self.enrich([PAPER, {**PAPER, "id": "test.00002"}])
        self.assertEqual([p["summary_source"] for p in papers], ["deepseek", "openai"])
        self.assertEqual(self.ds.call_count, 1)

    def test_missing_key_uses_deepseek(self):
        papers, _ = self.enrich(openai_api_key="")
        self.assertEqual(papers[0]["summary_source"], "deepseek")
        self.gpt.assert_not_called()

    def test_deepseek_only_configuration_unchanged(self):
        papers, _ = self.enrich(enable_openai_summary=False)
        self.assertEqual(papers[0]["summary_source"], "deepseek")
        self.gpt.assert_not_called()

    def test_both_apis_down_preserves_labeled_fallback(self):
        self.gpt.return_value = (None, USAGE, "incomplete")
        self.ds.return_value = (None, USAGE, "request_failure")
        papers, usage = self.enrich()
        self.assertEqual(papers[0]["summary_source"], "translation-fallback")
        self.assertEqual(papers[0]["summary_model"], "")
        self.assertEqual(usage["fallbacks"], 1)

    def test_translation_mode_preserved(self):
        self.translate.return_value = "translated abstract"
        papers, _ = self.enrich(enable_openai_summary=False, enable_deepseek_summary=False)
        self.assertEqual(papers[0]["summary"], "translated abstract")
        self.assertEqual(papers[0]["summary_source"], "translation")
        self.gpt.assert_not_called()
        self.ds.assert_not_called()


class CredentialTests(ContextTestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {}, clear=True))

    def test_env_precedence(self):
        os.environ.update(OPENAI_API_KEY="primary-test", GPTAPI_KY="alias-test")
        self.assertEqual(daily.load_openai_api_key({"openai_api_key_file": "missing"}), "primary-test")
        del os.environ["OPENAI_API_KEY"]
        self.assertEqual(daily.load_openai_api_key({}), "alias-test")

    def test_file_key_bom_and_trailing_newline(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "key.txt"
            path.write_text("file-test\n", encoding="utf-8-sig")
            self.assertEqual(daily.load_openai_api_key({"openai_api_key_file": str(path)}), "file-test")

    def test_unreadable_key_uses_fallback_without_error_details(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("PRIVATE_PATH")):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(daily.load_openai_api_key({"openai_api_key_file": "missing"}), "")
        self.assertNotIn("PRIVATE_PATH", output.getvalue())


class GenerationTests(ContextTestCase):
    def test_generate_writes_gpt_metadata_without_touching_kim_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            kim = root / "arxiv_daily_cornell" / "unchanged.txt"
            kim.parent.mkdir()
            kim.write_text("unchanged", encoding="utf-8")
            self.enterContext(patch.object(daily, "ROOT", root))
            self.enterContext(patch.object(daily, "load_config", return_value={
                "categories": ["cond-mat"], "enable_openai_summary": True,
            }))
            self.enterContext(patch.object(daily, "load_openai_api_key", return_value="test-key"))
            self.enterContext(patch.object(daily, "fetch_text", return_value="html"))
            self.enterContext(patch.object(daily, "parse_new_submissions", return_value=[PAPER]))
            self.enterContext(patch.object(daily, "fetch_authors", return_value=[]))
            post = self.enterContext(patch.object(daily, "post_json", return_value=response()))
            with contextlib.redirect_stdout(io.StringIO()):
                target = daily.generate("2026-10-29")
            papers = json.loads(target.with_name("papers.json").read_text(encoding="utf-8-sig"))
            html = target.read_text(encoding="utf-8-sig")
            self.assertEqual(papers[0]["summary_source"], "openai")
            self.assertEqual(papers[0]["summary"], SUMMARY)
            self.assertIn('paper.summary_source === "openai"', html)
            self.assertIn("<details>", html)
            self.assertNotIn("test-key", html)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(kim.read_text(encoding="utf-8"), "unchanged")


if __name__ == "__main__":
    unittest.main()
