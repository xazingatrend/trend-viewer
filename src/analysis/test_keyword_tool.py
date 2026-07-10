import unittest

from analysis import keyword_tool


class KeywordToolTests(unittest.TestCase):
    def test_normalize_applies_nfkc_casefold_and_punctuation_collapse(self):
        self.assertEqual(keyword_tool.normalize("  ＡＩ，  News!!\t速報  "), "ai news 速報")

    def test_tokens_remove_generic_stopwords_across_scripts(self):
        self.assertEqual(
            keyword_tool.tokens("오늘 OpenAI 공식 発表 Gemini 速報"),
            ["openai", "gemini", "速報"],
        )

    def test_three_syllable_hangul_entity_matches_particle_suffix(self):
        self.assertTrue(keyword_tool.matches("손흥민", "손흥민이 해트트릭"))

    def test_two_syllable_hangul_prefix_does_not_match_longer_word(self):
        self.assertFalse(keyword_tool.matches("카페", "카페인 효과"))
        self.assertTrue(keyword_tool.matches("카페", "서울 카페 추천"))

    def test_ascii_tokens_require_boundaries(self):
        self.assertFalse(keyword_tool.matches("ai", "a comfortable chair"))
        self.assertTrue(keyword_tool.matches("ai", "AI tools are useful"))

    def test_phrase_rule_requires_all_significant_tokens(self):
        self.assertTrue(keyword_tool.matches("openai benchmark", "Benchmark results from OpenAI"))
        self.assertFalse(keyword_tool.matches("openai benchmark", "OpenAI product launch"))

    def test_compact_substring_handles_nfkc_phrase(self):
        self.assertTrue(keyword_tool.matches("ＧＰＴ ５", "GPT-5 모델 공개"))

    def test_empty_and_stopword_only_anchors_do_not_match(self):
        self.assertFalse(keyword_tool.matches("", "anything"))
        self.assertFalse(keyword_tool.matches("오늘", "오늘"))


if __name__ == "__main__":
    unittest.main()


class StopwordQualityTest(unittest.TestCase):
    def test_common_function_words_are_stopwords(self):
        for word in ("in", "to", "you", "is", "it", "on", "we", "are"):
            self.assertNotIn(word, keyword_tool.tokens("in to you is it on we are"))

    def test_content_words_survive(self):
        self.assertIn("openai", keyword_tool.tokens("OpenAI in the news"))
        self.assertIn("손흥민", keyword_tool.tokens("손흥민 골 소식"))
