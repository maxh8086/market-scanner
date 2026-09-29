"""Tests for scanner.llm.

No network: the response parser and the cross-check are the parts with real
logic, and both are pure. The parser cases are the shapes small local models
actually emit -- markdown fences, prose either side, and a <think> block from a
reasoning-capable model.
"""

import unittest

from scanner import llm


class TestParseJSONResponse(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(llm.parse_json_response('{"a": 1}'), {"a": 1})

    def test_markdown_fence(self):
        self.assertEqual(
            llm.parse_json_response('```json\n{"a": 1}\n```'), {"a": 1})

    def test_bare_fence(self):
        self.assertEqual(llm.parse_json_response('```\n{"a": 1}\n```'), {"a": 1})

    def test_prose_on_either_side(self):
        text = 'Here is the extraction:\n{"a": 1}\nHope that helps!'
        self.assertEqual(llm.parse_json_response(text), {"a": 1})

    def test_think_block_is_stripped(self):
        text = '<think>The filing says 450 crore, so...</think>\n{"a": 1}'
        self.assertEqual(llm.parse_json_response(text), {"a": 1})

    def test_think_block_containing_braces(self):
        text = '<think>maybe {"a": 99}?</think>{"a": 1}'
        self.assertEqual(llm.parse_json_response(text), {"a": 1})

    def test_nested_object_survives(self):
        got = llm.parse_json_response('{"a": {"b": [1, 2]}}')
        self.assertEqual(got["a"]["b"], [1, 2])

    def test_empty_and_garbage(self):
        for bad in ("", None, "no json here", "{not: valid}"):
            self.assertIsNone(llm.parse_json_response(bad))

    def test_a_bare_array_is_not_accepted(self):
        """The prompts all ask for an object; an array means the model ignored
        the schema, and treating it as success would hide that."""
        self.assertIsNone(llm.parse_json_response("[1, 2, 3]"))


class TestConfig(unittest.TestCase):
    def test_ollama_endpoint(self):
        cfg = llm.LLMConfig(base_url="http://localhost:11434", api="ollama")
        self.assertEqual(cfg.endpoint, "http://localhost:11434/api/chat")

    def test_openai_endpoint(self):
        cfg = llm.LLMConfig(base_url="http://localhost:8080", api="openai")
        self.assertEqual(cfg.endpoint,
                         "http://localhost:8080/v1/chat/completions")

    def test_trailing_slash_does_not_double_up(self):
        cfg = llm.LLMConfig(base_url="http://localhost:11434/", api="ollama")
        self.assertEqual(cfg.endpoint, "http://localhost:11434/api/chat")

    def test_temperature_is_zero_for_extraction(self):
        self.assertEqual(llm.LLMConfig().temperature, 0.0)

    def test_ollama_payload_constrains_to_json(self):
        cfg = llm.LLMConfig(api="ollama")
        self.assertEqual(llm._payload(cfg, "p")["format"], "json")

    def test_openai_payload_constrains_to_json(self):
        cfg = llm.LLMConfig(api="openai")
        self.assertEqual(llm._payload(cfg, "p")["response_format"],
                         {"type": "json_object"})

    def test_content_extraction_per_api(self):
        ollama = llm.LLMConfig(api="ollama")
        self.assertEqual(
            llm._content(ollama, {"message": {"content": "x"}}), "x")
        openai = llm.LLMConfig(api="openai")
        self.assertEqual(
            llm._content(openai, {"choices": [{"message": {"content": "y"}}]}),
            "y")

    def test_content_extraction_survives_an_empty_body(self):
        self.assertEqual(llm._content(llm.LLMConfig(api="ollama"), {}), "")
        self.assertEqual(llm._content(llm.LLMConfig(api="openai"), {}), "")


class TestPrompts(unittest.TestCase):
    def test_every_kind_has_a_prompt(self):
        self.assertIn(llm.KIND_ORDER, llm.PROMPTS)
        self.assertIn(llm.KIND_CAPACITY, llm.PROMPTS)
        self.assertIn(llm.KIND_GUIDANCE, llm.PROMPTS)

    def test_prompt_has_exactly_one_substitution_slot(self):
        for kind, prompt in llm.PROMPTS.items():
            with self.subTest(kind=kind):
                self.assertEqual(prompt.count(llm.TEXT_SLOT), 1)

    def test_the_schema_is_already_substituted(self):
        """The schema goes in when the module loads, so only the filing text is
        left to fill. A leftover schema slot would mean the model is asked to
        return JSON matching a placeholder."""
        for kind, prompt in llm.PROMPTS.items():
            with self.subTest(kind=kind):
                self.assertNotIn("{schema}", prompt)
                self.assertIn('"notes"', prompt)

    def test_substitution_inserts_the_text_and_changes_nothing_else(self):
        for kind, prompt in llm.PROMPTS.items():
            with self.subTest(kind=kind):
                filled = prompt.replace(llm.TEXT_SLOT, "TEXT")
                self.assertIn("TEXT", filled)
                self.assertEqual(len(filled),
                                 len(prompt) - len(llm.TEXT_SLOT) + 4)

    def test_literal_braces_and_percents_survive_substitution(self):
        """Why substitution is str.replace rather than a formatter: the schemas
        are JSON and the guidance prompt quotes percentage growth. Both would
        need escaping under %-formatting or str.format, and forgetting that
        escape is a crash at extraction time, not at import."""
        prompt = llm.PROMPTS[llm.KIND_GUIDANCE]
        filled = prompt.replace(llm.TEXT_SLOT, "TEXT")
        self.assertIn("22% last year", filled)
        self.assertIn("18-20% growth", filled)
        self.assertIn("{", filled)

    def test_filing_text_containing_a_percent_sign_is_safe(self):
        """Real filings are full of percentages, and under %-formatting a stray
        one in the *text* was harmless but one in the prompt was fatal. Neither
        should be able to break extraction now."""
        prompt = llm.PROMPTS[llm.KIND_ORDER]
        filled = prompt.replace(llm.TEXT_SLOT, "margin was 12% and 50%s of it")
        self.assertIn("12% and 50%s of it", filled)

    def test_order_prompt_states_absolute_rupees(self):
        """The single most likely model error is answering in crore."""
        self.assertIn("ABSOLUTE RUPEES", llm.PROMPTS[llm.KIND_ORDER])

    def test_order_prompt_warns_against_the_known_misparse(self):
        prompt = llm.PROMPTS[llm.KIND_ORDER].lower()
        for trap in ("market size", "revenue", "paid-up capital"):
            self.assertIn(trap, prompt)

    def test_order_prompt_asks_for_the_counterparty(self):
        """Extracted now so a supplier/customer graph never needs a re-run."""
        self.assertIn("counterparty", llm.PROMPTS[llm.KIND_ORDER])

    def test_capacity_prompt_asks_for_both_sides(self):
        prompt = llm.PROMPTS[llm.KIND_CAPACITY]
        self.assertIn("existing_capacity", prompt)
        self.assertIn("proposed_capacity", prompt)

    def test_unknown_kind_is_an_error_not_an_exception(self):
        result = llm.extract(llm.LLMConfig(), "text", "nonsense_v9")
        self.assertIn("unknown extraction kind", result.error)

    def test_empty_text_short_circuits_before_any_request(self):
        result = llm.extract(llm.LLMConfig(base_url="http://127.0.0.1:1"),
                             "   ", llm.KIND_ORDER)
        self.assertEqual(result.error, "no text to extract from")


class TestCrossCheck(unittest.TestCase):
    def test_agreement_within_tolerance(self):
        self.assertEqual(llm.cross_check(4.5e9, 4.5e9), llm.AGREE)
        self.assertEqual(llm.cross_check(4.5e9, 4.53e9), llm.AGREE)  # 0.7%

    def test_disagreement_beyond_tolerance(self):
        self.assertEqual(llm.cross_check(4.5e9, 4.5e8), llm.DISAGREE)

    def test_the_crore_confusion_is_caught(self):
        """A model answering in crore instead of rupees is off by 1e7 -- the
        error this cross-check exists to catch."""
        self.assertEqual(llm.cross_check(4.5e9, 450.0), llm.DISAGREE)

    def test_one_sided_results(self):
        self.assertEqual(llm.cross_check(None, 4.5e9), llm.LLM_ONLY)
        self.assertEqual(llm.cross_check(4.5e9, None), llm.REGEX_ONLY)
        self.assertEqual(llm.cross_check(None, None), llm.NEITHER)

    def test_zero_regex_value_is_not_a_division_by_zero(self):
        self.assertEqual(llm.cross_check(0.0, 4.5e9), llm.DISAGREE)


class TestResult(unittest.TestCase):
    def test_ok_requires_data_and_no_error(self):
        self.assertTrue(llm.LLMResult(data={"a": 1}).ok)
        self.assertFalse(llm.LLMResult(data={}).ok)
        self.assertFalse(llm.LLMResult(data={"a": 1}, error="boom").ok)

    def test_prompt_version_is_recorded(self):
        self.assertEqual(llm.LLMResult().prompt_version, llm.PROMPT_VERSION)


class TestOCRPositioning(unittest.TestCase):
    def test_the_fallback_note_says_text_layer_first(self):
        """Documented in code because it is the decision most likely to be
        redone wrong later: OCR is a fallback, never the first pass."""
        note = llm.OCR_FALLBACK_NOTE.lower()
        self.assertIn("returns ''", llm.OCR_FALLBACK_NOTE)
        self.assertIn("never ahead of the text layer", note)


if __name__ == "__main__":
    unittest.main()
