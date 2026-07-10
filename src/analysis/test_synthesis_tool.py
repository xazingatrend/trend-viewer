import json
import os
import unittest
from unittest import mock

from analysis import aggregate_tool, llm_client_tool, synthesis_tool
from shared import cache_tool


class SynthesisToolTest(unittest.TestCase):
    def setUp(self):
        cache_tool._cache.clear()
        self.env_patch = mock.patch.dict(
            os.environ,
            {"TREND_ANALYSIS_MODEL": "test/luna"},
        )
        self.aggregate_patch = mock.patch.object(
            aggregate_tool,
            "analyze_heuristic",
            return_value=self._heuristic(),
        )
        self.complete_patch = mock.patch.object(
            llm_client_tool,
            "complete",
            return_value=self._valid_json(),
        )
        self.enabled_patch = mock.patch.object(
            llm_client_tool,
            "is_enabled",
            return_value=True,
        )
        self.env_patch.start()
        self.aggregate = self.aggregate_patch.start()
        self.complete = self.complete_patch.start()
        self.is_enabled = self.enabled_patch.start()

    def tearDown(self):
        self.enabled_patch.stop()
        self.complete_patch.stop()
        self.aggregate_patch.stop()
        self.env_patch.stop()
        cache_tool._cache.clear()

    def _heuristic(self, topics=None, briefing=None):
        if topics is None:
            topics = [
                {
                    "keyword": "루나",
                    "title": "루나 모델 공개",
                    "platforms": ["trends", "youtube"],
                    "score": 42.5,
                    "velocity": "rising",
                    "items": [
                        {
                            "platform": "youtube",
                            "title": "루나 모델 데모",
                            "url": "https://example.com/luna",
                            "metric": 1200,
                            "ts": 1,
                        },
                        {
                            "platform": "trends",
                            "title": "루나 검색량",
                            "url": "https://example.com/trends",
                            "metric": 800,
                            "ts": 2,
                        },
                    ],
                }
            ]
        if briefing is None:
            briefing = ["상승세 토픽: 루나 모델 공개", "교차 플랫폼 토픽: 루나 모델 공개"]
        return {
            "topics": topics,
            "velocityBaseline": {"available": True, "elapsedSeconds": 3600},
            "briefing": briefing,
            "errors": [],
            "generatedBy": "heuristic",
        }

    def _payload(self, **overrides):
        payload = {
            "clusters": [
                {
                    "title": "루나 공개 반응",
                    "keywords": ["루나", "AI"],
                    "why": "검색과 영상 반응이 함께 상승했습니다.",
                    "platforms": ["trends", "youtube"],
                    "evidence": ["E1"],
                    "momentum": "rising",
                }
            ],
            "briefing": "루나 공개 반응이 빠르게 확산 중입니다.",
        }
        payload.update(overrides)
        return payload

    def _valid_json(self, **overrides):
        return json.dumps(self._payload(**overrides), ensure_ascii=False)

    def test_prose_wrapped_json_is_accepted(self):
        self.complete.return_value = "분석 결과입니다.\n" + self._valid_json() + "\n끝"

        data, _, ttl = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "test/luna")
        self.assertEqual(data["clusters"][0]["evidence"][0]["url"], "https://example.com/luna")
        self.assertTrue(data["llm"]["ok"])
        self.assertEqual(ttl, 1800)

    def test_braces_inside_strings_and_earlier_object_are_handled(self):
        payload = self._payload()
        payload["clusters"][0]["title"] = "루나 {베타} 공개"
        self.complete.return_value = "metadata {} then " + json.dumps(payload, ensure_ascii=False)

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["clusters"][0]["title"], "루나 {베타} 공개")

    def test_invalid_json_falls_back(self):
        self.complete.return_value = "not json"

        data, _, ttl = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "heuristic")
        self.assertEqual(data["llm"], {"ok": False, "reason": "error"})
        self.assertEqual(data["clusters"][0]["title"], "루나 모델 공개")
        self.assertEqual(ttl, 300)

    def test_deadline_truncated_json_falls_back(self):
        self.complete.return_value = '{"clusters":[{"title":"unfinished"'

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "heuristic")

    def test_schema_invalid_cluster_collection_falls_back(self):
        self.complete.return_value = self._valid_json(clusters={"title": "wrong"})

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "heuristic")

    def test_schema_invalid_required_fields_are_dropped(self):
        clusters = [
            {**self._payload()["clusters"][0], "title": ""},
            {**self._payload()["clusters"][0], "title": 123},
            {key: value for key, value in self._payload()["clusters"][0].items() if key != "why"},
        ]
        self.complete.return_value = self._valid_json(clusters=clusters)

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "heuristic")

    def test_schema_invalid_keywords_drop_cluster_and_missing_keywords_derive(self):
        invalid = {**self._payload()["clusters"][0], "keywords": "루나"}
        derived = {**self._payload()["clusters"][0], "title": "파생 키워드"}
        del derived["keywords"]
        self.complete.return_value = self._valid_json(clusters=[invalid, derived])

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(len(data["clusters"]), 1)
        self.assertEqual(data["clusters"][0]["keywords"], ["파생 키워드"])

    def test_schema_invalid_platforms_or_evidence_drop_clusters(self):
        base = self._payload()["clusters"][0]
        clusters = [
            {**base, "platforms": "youtube"},
            {**base, "evidence": "E1"},
        ]
        self.complete.return_value = self._valid_json(clusters=clusters)

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "heuristic")

    def test_unknown_platforms_and_evidence_ids_are_dropped(self):
        heuristic = self._heuristic()
        heuristic["topics"][0]["items"][1]["url"] = "javascript:alert(1)"
        self.aggregate.return_value = heuristic
        cluster = {
            **self._payload()["clusters"][0],
            "platforms": ["youtube", "unknown", 7],
            "evidence": [
                "E999",
                "https://model-injected.example/evil",
                {"title": "fake", "url": "https://evil.example"},
                "E2",
                "E1",
            ],
        }
        self.complete.return_value = self._valid_json(clusters=[cluster])

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        cleaned = data["clusters"][0]
        self.assertEqual(cleaned["platforms"], ["youtube"])
        self.assertEqual(
            cleaned["evidence"],
            [{"title": "루나 모델 데모", "url": "https://example.com/luna"}],
        )

    def test_invalid_momentum_is_coerced_to_steady(self):
        cluster = {**self._payload()["clusters"][0], "momentum": "exploding"}
        self.complete.return_value = self._valid_json(clusters=[cluster])

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["clusters"][0]["momentum"], "steady")

    def test_schema_caps_and_unknown_fields_are_cleaned(self):
        clusters = []
        for number in range(8):
            clusters.append(
                {
                    **self._payload()["clusters"][0],
                    "title": "T" + str(number),
                    "keywords": ["k" + str(index) for index in range(7)],
                    "extra": "drop me",
                }
            )
        self.complete.return_value = self._valid_json(clusters=clusters, extra="drop me")

        data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(len(data["clusters"]), 6)
        self.assertEqual(len(data["clusters"][0]["keywords"]), 5)
        self.assertNotIn("extra", data)
        self.assertNotIn("extra", data["clusters"][0])

    def test_briefing_list_is_joined_and_non_string_becomes_empty(self):
        self.complete.return_value = self._valid_json(briefing=["첫째", "둘째", 3])
        data, _, _ = synthesis_tool.get_analysis("KR", False)
        self.assertEqual(data["briefing"], "첫째 둘째")

        cache_tool._cache.clear()
        self.complete.return_value = self._valid_json(briefing={"bad": True})
        data, _, _ = synthesis_tool.get_analysis("KR", False)
        self.assertEqual(data["briefing"], "")

    def test_surrogates_and_c0_controls_are_sanitized_in_fallback(self):
        heuristic = self._heuristic()
        heuristic["topics"][0]["title"] = "루나\ud800\x00 모델\x07 공개"
        heuristic["topics"][0]["keyword"] = "루나\udfff\x01"
        heuristic["topics"][0]["items"][0]["title"] = "근거\ud800\x02 제목"
        heuristic["errors"] = [{"detail": "오류\ud800\x03 내용"}]
        heuristic["velocityBaseline"]["note"] = "기준\udfff\x04 값"
        self.aggregate.return_value = heuristic
        self.is_enabled.return_value = False

        data, _, _ = synthesis_tool.get_analysis("KR", False)
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")

        self.assertTrue(encoded)
        self.assertEqual(data["clusters"][0]["title"], "루나 모델 공개")
        self.assertEqual(data["clusters"][0]["evidence"][0]["title"], "근거 제목")
        self.assertNotRegex(json.dumps(data, ensure_ascii=False), r"[\ud800-\udfff\x00-\x09\x0b-\x1f]")

    def test_fallback_briefing_joins_and_zero_topic_uses_fixed_line(self):
        self.is_enabled.return_value = False
        self.aggregate.return_value = self._heuristic(briefing=["첫째", "둘째"])

        data, _, _ = synthesis_tool.get_analysis("KR", False)
        self.assertEqual(data["briefing"], "첫째 둘째")

        cache_tool._cache.clear()
        self.aggregate.return_value = self._heuristic(topics=[], briefing=[])
        data, _, _ = synthesis_tool.get_analysis("KR", False)
        self.assertEqual(data["clusters"], [])
        self.assertEqual(data["briefing"], "분석할 토픽이 아직 충분하지 않습니다.")

    def test_disabled_llm_never_calls_complete(self):
        self.is_enabled.return_value = False

        data, _, ttl = synthesis_tool.get_analysis("KR", False)

        self.complete.assert_not_called()
        self.assertEqual(data["llm"], {"ok": False, "reason": "disabled"})
        self.assertEqual(ttl, 300)

    def test_complete_exception_is_guarded_by_fallback(self):
        self.complete.side_effect = RuntimeError("proxy failed")

        data, _, ttl = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "heuristic")
        self.assertEqual(data["llm"], {"ok": False, "reason": "error"})
        self.assertEqual(ttl, 300)

    def test_complete_uses_exact_interactive_timeout_and_deadline(self):
        synthesis_tool.get_analysis("KR", False)

        self.complete.assert_called_once_with(
            mock.ANY,
            system=mock.ANY,
            timeout=10,
            deadline=45,
        )
        prompt = self.complete.call_args.args[0]
        system = self.complete.call_args.kwargs["system"]
        self.assertIn("UNTRUSTED DATA", prompt)
        self.assertIn("evidence IDs only", prompt)
        self.assertIn("untrusted content", system)
        self.assertIn("output JSON only", system)

    def test_prompt_bounds_topics_items_and_sanitizes_titles(self):
        topics = []
        for topic_number in range(16):
            topics.append(
                {
                    "title": ("제목\ud800\x00 " + str(topic_number)) * 30,
                    "keyword": "키워드",
                    "velocity": "flat",
                    "platforms": ["youtube"],
                    "items": [
                        {
                            "platform": "youtube",
                            "title": ("근거\ud800\x01 " + str(item_number)) * 30,
                            "url": "https://example.com/" + str(item_number),
                            "metric": item_number,
                        }
                        for item_number in range(5)
                    ],
                }
            )

        _, prompt, evidence_map = synthesis_tool.build_prompt(topics, "KR")

        self.assertEqual(len(evidence_map), 14 * 3)
        self.assertNotRegex(prompt, r"[\ud800-\udfff\x00-\x09\x0b-\x1f]")
        self.assertTrue(all(len(item["title"]) <= 120 for item in evidence_map.values()))

    def test_extract_json_caps_input_at_two_hundred_thousand_chars(self):
        text = "x" * 200_000 + self._valid_json()

        self.assertIsNone(synthesis_tool.extract_json(text))

    def test_ttl_callable_uses_1800_for_success_and_300_for_fallback(self):
        success, _, success_ttl = synthesis_tool.get_analysis("KR", False)
        self.assertTrue(success["llm"]["ok"])
        self.assertEqual(success_ttl, 1800)

        self.is_enabled.return_value = False
        fallback, _, fallback_ttl = synthesis_tool.get_analysis("US", False)
        self.assertFalse(fallback["llm"]["ok"])
        self.assertEqual(fallback_ttl, 300)

    def test_cache_hit_does_not_recompute(self):
        first, first_fetched_at, first_ttl = synthesis_tool.get_analysis("KR", False)
        second, second_fetched_at, second_ttl = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(second, first)
        self.assertEqual(second_fetched_at, first_fetched_at)
        self.assertEqual((first_ttl, second_ttl), (1800, 1800))
        self.aggregate.assert_called_once_with("KR", False)
        self.complete.assert_called_once()

    def test_force_replaces_cached_failure(self):
        self.complete.side_effect = ["invalid", self._valid_json()]

        failed, failed_at, failed_ttl = synthesis_tool.get_analysis("KR", False)
        succeeded, succeeded_at, succeeded_ttl = synthesis_tool.get_analysis("KR", True)

        self.assertEqual(failed["generatedBy"], "heuristic")
        self.assertEqual(failed_ttl, 300)
        self.assertEqual(succeeded["generatedBy"], "test/luna")
        self.assertEqual(succeeded_ttl, 1800)
        self.assertGreater(succeeded_at, failed_at)
        self.assertEqual(
            self.aggregate.call_args_list,
            [mock.call("KR", False), mock.call("KR", True)],
        )

    def test_generated_by_uses_actual_model_and_omits_heuristic_topics(self):
        with mock.patch.dict(os.environ, {"TREND_ANALYSIS_MODEL": "cursor/custom-model"}):
            data, _, _ = synthesis_tool.get_analysis("KR", False)

        self.assertEqual(data["generatedBy"], "cursor/custom-model")
        self.assertEqual(data["llm"]["model"], "cursor/custom-model")
        self.assertNotIn("heuristicTopics", data)


if __name__ == "__main__":
    unittest.main()
