import unittest
from unittest import mock

import main


class MainApiCacheMetadataTest(unittest.TestCase):
    def setUp(self):
        self.handler = main.Handler.__new__(main.Handler)
        self.sent = []

        def capture(handler_self, code, body, content_type="application/json; charset=utf-8"):
            del handler_self, content_type
            self.sent.append((code, body))

        self.send_patch = mock.patch.object(main.Handler, "_send", capture)
        self.send_patch.start()

    def tearDown(self):
        self.send_patch.stop()

    def assert_cache_metadata(self, body, fetched_at=123.5):
        self.assertEqual(body["fetchedAt"], fetched_at)
        self.assertEqual(body["cacheTtl"], main.CACHE_TTL)

    def test_videos_payload_includes_cache_metadata(self):
        with mock.patch.object(main.youtube_tool, "get_videos", return_value=([{"id": "v"}], 123.5)):
            self.handler._handle_videos({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["videos"], [{"id": "v"}])
        self.assert_cache_metadata(body)

    def test_videos_passes_country_and_falls_back_to_kr(self):
        with mock.patch.object(main.youtube_tool, "get_videos", return_value=([], 123.5)) as gv:
            self.handler._handle_videos({"country": ["us"]})
            self.assertEqual(gv.call_args.args[-1], "US")
            self.assertEqual(self.sent[-1][1]["country"], "US")

            self.handler._handle_videos({"country": ["XX"]})
            self.assertEqual(gv.call_args.args[-1], "KR")
            self.assertEqual(self.sent[-1][1]["country"], "KR")

    def test_trends_payload_includes_cache_metadata(self):
        items = [{"keyword": "t", "trafficValue": 20000}]
        with mock.patch.object(main.trends_tool, "get_trends", return_value=(items, 123.5, [], 3600)) as gt:
            self.handler._handle_trends({"country": ["jp"]})

        gt.assert_called_once_with("JP", False)
        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["trends"], items)
        self.assertEqual(body["country"], "JP")
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["errors"], [])
        self.assert_cache_metadata(body)

    def test_trends_error_payload_reports_negative_cache_ttl(self):
        errors = [{"country": "KR", "kind": "OSError"}]
        with mock.patch.object(main.trends_tool, "get_trends", return_value=([], 123.5, errors, 120)):
            self.handler._handle_trends({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["errors"], errors)
        self.assertEqual(body["cacheTtl"], 120)

    def test_reels_payload_includes_cache_metadata(self):
        with mock.patch.object(main.reels_tool, "get_reels", return_value=([{"id": "r"}], ["openai"], 123.5, [], 3600)):
            self.handler._handle_reels({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["reels"], [{"id": "r"}])
        self.assertEqual(body["accounts"], ["openai"])
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["errors"], [])
        self.assert_cache_metadata(body)

    def test_x_payload_includes_cache_metadata(self):
        with mock.patch.object(main.x_twitter_tool, "get_x_posts", return_value=([{"id": "x"}], ["OpenAI"], 123.5, [{"account": "runwayml", "kind": "http", "code": 429}], 3600)):
            self.handler._handle_x({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["posts"], [{"id": "x"}])
        self.assertEqual(body["accounts"], ["OpenAI"])
        self.assertEqual(body["status"], "partial")
        self.assertEqual(body["errors"], [{"account": "runwayml", "kind": "http", "code": 429}])
        self.assert_cache_metadata(body)

    def test_threads_payload_includes_cache_metadata(self):
        with mock.patch.object(main.threads_tool, "get_threads_posts", return_value=([], ["openai"], 123.5, [], 3600)):
            self.handler._handle_threads({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["posts"], [])
        self.assertEqual(body["accounts"], ["openai"])
        self.assertEqual(body["status"], "empty")
        self.assertEqual(body["errors"], [])
        self.assert_cache_metadata(body)

    def test_reels_error_payload_reports_negative_cache_ttl(self):
        errors = [{"account": "openai", "kind": "http", "code": 401}]
        with mock.patch.object(main.reels_tool, "get_reels", return_value=([], ["openai"], 123.5, errors, 120)):
            self.handler._handle_reels({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["errors"], errors)
        self.assertEqual(body["cacheTtl"], 120)

    def test_tiktok_payload_includes_cache_metadata(self):
        with mock.patch.object(main.tiktok_tool, "get_tiktok", return_value=([{"id": "tt"}], ["openai"], 123.5)):
            self.handler._handle_tiktok({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["posts"], [{"id": "tt"}])
        self.assertEqual(body["accounts"], ["openai"])
        self.assert_cache_metadata(body)

    def test_ai_payload_includes_cache_metadata(self):
        data = {"news": [{"title": "n"}], "models": {"latest": []}}
        with mock.patch.object(main.ai_news_tool, "get_ai_data", return_value=(data, 123.5)):
            self.handler._handle_ai({})

        code, body = self.sent[-1]
        self.assertEqual(code, 200)
        self.assertEqual(body["news"], [{"title": "n"}])
        self.assertEqual(body["models"], {"latest": []})
        self.assert_cache_metadata(body)

    def test_analysis_handler_passes_through_entry_ttl_and_validates_country(self):
        data = {"clusters": [], "briefing": "분석 대기", "generatedBy": "heuristic"}
        for cache_ttl, country, expected_country in ((300, "us", "US"), (1800, "xx", "KR")):
            with self.subTest(cache_ttl=cache_ttl, country=country):
                self.sent.clear()
                with mock.patch.object(
                    main.synthesis_tool,
                    "get_analysis",
                    return_value=(data, 123.5, cache_ttl),
                ) as get_analysis:
                    self.handler._handle_analysis({"country": [country], "force": ["1"]})

                get_analysis.assert_called_once_with(expected_country, True)
                code, body = self.sent[-1]
                self.assertEqual(code, 200)
                self.assertEqual(body["clusters"], [])
                self.assertEqual(body["country"], expected_country)
                self.assertEqual(body["fetchedAt"], 123.5)
                self.assertEqual(body["cacheTtl"], cache_ttl)


if __name__ == "__main__":
    unittest.main()
