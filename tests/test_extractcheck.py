import unittest
from unittest import mock

from scanner import extractcheck as ec
from scanner import llm


class TestToRupees(unittest.TestCase):
    def test_crore_lakh_and_plain_rupees(self):
        self.assertEqual(llm.to_rupees(7.99, "crore"), 79900000.0)
        self.assertEqual(llm.to_rupees(12.5, "Lakh"), 1250000.0)
        self.assertEqual(llm.to_rupees(215748840, "rupees"), 215748840.0)

    def test_missing_or_unknown_unit_is_none(self):
        self.assertIsNone(llm.to_rupees(5, None))
        self.assertIsNone(llm.to_rupees(5, "furlongs"))
        self.assertIsNone(llm.to_rupees(None, "crore"))
        self.assertIsNone(llm.to_rupees("n/a", "crore"))


class TestAddRupees(unittest.TestCase):
    def test_order_in_inr(self):
        d = llm.add_rupees(llm.KIND_ORDER, {"order_amount": 450, "order_unit": "crore",
                                            "currency": "INR"})
        self.assertEqual(d["order_value_inr"], 4500000000.0)

    def test_foreign_order_takes_the_stated_inr_equivalent_only(self):
        d = llm.add_rupees(llm.KIND_ORDER, {
            "order_amount": 7.6, "order_unit": "million", "currency": "USD",
            "inr_amount": 67.16, "inr_unit": "crore"})
        self.assertEqual(d["order_value_inr"], 671600000.0)
        d = llm.add_rupees(llm.KIND_ORDER, {"order_amount": 7.6, "order_unit": "million",
                                            "currency": "USD"})
        self.assertIsNone(d["order_value_inr"])

    def test_capex_and_target(self):
        cap = llm.add_rupees(llm.KIND_CAPACITY, {"capex_amount": 300, "capex_unit": "crore"})
        self.assertEqual(cap["capex_inr"], 3000000000.0)
        gd = llm.add_rupees(llm.KIND_GUIDANCE, {"target_amount": 1200, "target_unit": "crore"})
        self.assertEqual(gd["target_inr"], 12000000000.0)

    def test_other_kind_left_alone(self):
        d = llm.add_rupees(llm.KIND_CAPACITY, {"order_amount": 1, "order_unit": "crore"})
        self.assertNotIn("order_value_inr", d)


class TestSchemasAndPayload(unittest.TestCase):
    def test_every_prompt_kind_has_a_strict_schema(self):
        for kind in llm.PROMPTS:
            schema = llm.SCHEMAS[kind]
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_schema_fields_are_named_in_the_prompt(self):
        for kind, prompt in llm.PROMPTS.items():
            for field in llm.SCHEMAS[kind]["properties"]:
                self.assertIn(field, prompt, f"{kind}.{field}")

    def test_openai_payload_enforces_the_schema(self):
        cfg = llm.LLMConfig(api="openai", model="m")
        body = llm._payload(cfg, "p", llm.KIND_ORDER)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertEqual(body["max_tokens"], llm.OPENAI_MAX_TOKENS)

    def test_context_overflow_retries_with_half_the_text(self):
        cfg = llm.LLMConfig(api="openai", model="m")
        seen = []

        def post(url, json, timeout):
            seen.append(len(json["messages"][0]["content"]))
            r = mock.Mock()
            if len(seen) == 1:
                r.status_code, r.text = 400, "maximum context length exceeded"
            else:
                r.status_code, r.text = 200, ""
                r.raise_for_status = lambda: None
                r.json = lambda: {"choices": [{"message": {"content": '{"a": 1}'}}]}
            return r

        with mock.patch("requests.post", post):
            res = llm.extract(cfg, "x" * 20000, llm.KIND_GUIDANCE)
        self.assertTrue(res.ok)
        self.assertLess(seen[1], seen[0])


class TestExtractCheck(unittest.TestCase):
    def test_compare(self):
        self.assertEqual(ec.compare(1000.0, 1010.0), "agree")
        self.assertEqual(ec.compare(1000.0, 10000.0), "disagree")
        self.assertEqual(ec.compare(1000.0, None), "missed")

    def test_verdict(self):
        ok = ec.Metrics(requested=40, agree=38, disagree=2, seconds=100)
        self.assertTrue(ec.verdict(ok)[0])
        bad = ec.Metrics(requested=40, agree=20, disagree=20, seconds=100)
        self.assertIn("agreement", ec.verdict(bad)[1][0])
        self.assertFalse(ec.verdict(ec.Metrics(requested=40, agree=40, failed=1))[0])
        self.assertFalse(ec.verdict(ec.Metrics())[0])
        self.assertFalse(ec.verdict(ec.Metrics(requested=40, agree=40, seconds=500))[0])


if __name__ == "__main__":
    unittest.main()
