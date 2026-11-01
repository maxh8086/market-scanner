"""Per-stock conclusions: the fact sheet, and the guards that do not trust the model."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import pandas as pd

from scanner import conclude, docstore, llm

ROW = {"symbol": "ABC", "company": "ABC Ltd", "industry": "Capital Goods",
       "ltp": 2899.0, "ath_high": 2900.0, "distance_pct": 0.0345, "bucket": "NEW_ATH_TODAY",
       "trend": "UPTREND", "roce": 21.4, "pe": 30.2, "order_value_cr": 157.0,
       "order_significance": "MATERIAL", "pledged_pct": float("nan"), "bonus_issue": ""}


class TestPacket(unittest.TestCase):
    def test_only_real_values_and_dotted_keys(self):
        p = conclude.build_packet(ROW)
        self.assertEqual(p["price.ltp"], 2899.0)
        self.assertEqual(p["fundamentals.roce"], 21.4)
        self.assertNotIn("fundamentals.pledged_pct", p)       # NaN is not a fact
        self.assertNotIn("corporate.bonus_issue", p)          # blank string is not a fact

    def test_filings_newest_first_and_capped(self):
        filings = [{"an_date": f"2026-0{i}-01", "kind": "orderbook", "regex_rupees": 1e8}
                   for i in range(1, 9)]
        p = conclude.build_packet(ROW, filings)
        self.assertEqual(p["filing1.date"], "2026-08-01")
        self.assertEqual(p["filing1.value_cr"], 10.0)
        self.assertNotIn(f"filing{conclude.MAX_FILINGS + 1}.date", p)

    def test_hash_changes_with_facts_and_is_stable_otherwise(self):
        a = conclude.build_packet(ROW)
        self.assertEqual(conclude.packet_hash(a), conclude.packet_hash(dict(a)))
        b = dict(a, **{"price.ltp": 2800.0})
        self.assertNotEqual(conclude.packet_hash(a), conclude.packet_hash(b))


class TestGuards(unittest.TestCase):
    def setUp(self):
        self.packet = conclude.build_packet(ROW)

    def good(self, **over):
        d = {"stance": "constructive", "conclusion": "At its high with ROCE of 21.4%.",
             "positives": [{"point": "New high", "evidence": ["price.bucket"]}],
             "concerns": [], "data_gaps": ["No forecast"]}
        d.update(over)
        return d

    def test_valid_answer_passes(self):
        r = conclude.validate("ABC", self.good(), self.packet)
        self.assertTrue(r.ok)
        self.assertEqual(r.stance, "CONSTRUCTIVE")
        self.assertEqual(r.ungrounded, 0)
        self.assertEqual(r.unverified_numbers, [])

    def test_stance_comes_from_the_scorecard_not_the_model(self):
        r = conclude.validate("ABC", self.good(stance="CAUTIOUS"), self.packet)
        self.assertTrue(r.ok)
        self.assertEqual(r.stance, "CONSTRUCTIVE")
        self.assertGreater(r.score, 0)
        self.assertTrue(r.rules)

    def test_negative_value_quoted_as_below_is_not_flagged(self):
        packet = dict(self.packet, **{"fundamentals.pe_vs_industry_pct": -26.88})
        r = conclude.validate("ABC", self.good(conclusion="PE is 26.88% below the industry."),
                              packet)
        self.assertEqual(r.unverified_numbers, [])

    def test_digits_in_the_ticker_are_not_flagged(self):
        r = conclude.validate("360ONE", self.good(conclusion="360ONE trades at ROCE 21.4%."),
                              self.packet)
        self.assertEqual(r.unverified_numbers, [])

    def test_computed_ratio_is_still_flagged(self):
        r = conclude.validate("ABC", self.good(conclusion="Mcap to sales ratio is 77.8."),
                              dict(self.packet))
        self.assertEqual(r.unverified_numbers, ["77.8"])

    def test_data_gaps_are_computed_from_the_sheet_not_the_model(self):
        r = conclude.validate("ABC", self.good(data_gaps=["price.ltp"]), self.packet)
        self.assertNotIn("price.ltp", " ".join(r.data_gaps))       # the model's list is ignored
        self.assertIn("fundamentals.roe not available", r.data_gaps)   # ROW has no ROE
        self.assertNotIn("fundamentals.roce not available", r.data_gaps)
        self.assertIn("no recent filings stored", r.data_gaps)

    def test_speculative_wording_is_listed(self):
        r = conclude.validate("ABC", self.good(
            conclusion="Trading 20% below its high, a sign of undervaluation and upside."),
            self.packet)
        self.assertEqual(r.speculative, ["undervalu", "upside"])
        self.assertEqual(conclude.speculative_phrases(["ROCE is 21.4%."]), [])

    def test_point_citing_a_missing_key_is_dropped_and_counted(self):
        d = self.good(positives=[
            {"point": "Great margins", "evidence": ["fundamentals.opm"]},      # not in packet
            {"point": "Trend up", "evidence": ["price.trend", "made.up"]}])
        r = conclude.validate("ABC", d, self.packet)
        self.assertEqual([p["point"] for p in r.positives], ["Trend up"])
        self.assertEqual(r.positives[0]["evidence"], ["price.trend"])
        self.assertEqual(r.ungrounded, 1)

    def test_point_with_no_evidence_is_dropped(self):
        r = conclude.validate("ABC", self.good(concerns=[{"point": "Risky", "evidence": []}]),
                              self.packet)
        self.assertEqual(r.concerns, [])
        self.assertEqual(r.ungrounded, 1)

    def test_invented_number_is_flagged(self):
        r = conclude.validate("ABC", self.good(conclusion="ROCE 21.4% and revenue up 87%."),
                              self.packet)
        self.assertEqual(r.unverified_numbers, ["87"])

    def test_rounding_and_thousands_separators_are_not_flagged(self):
        r = conclude.validate("ABC", self.good(
            conclusion="LTP Rs 2,899 near a high of 2900, P/E about 30 with ROCE 21%."),
            self.packet)
        self.assertEqual(r.unverified_numbers, [])

    def test_indicator_window_lengths_are_not_flagged(self):
        r = conclude.validate("ABC", self.good(
            conclusion="Above the 200-day average and near its 52-week high, ROCE 21.4%."),
            self.packet)
        self.assertEqual(r.unverified_numbers, [])

    def test_empty_conclusion_is_an_error(self):
        self.assertFalse(conclude.validate("ABC", self.good(conclusion=" "), self.packet).ok)


class TestScorecard(unittest.TestCase):
    STRONG = {"price.trend": "UPTREND", "price.distance_pct": 3.0,
              "fundamentals.yoy_growth_pct": 45.0, "fundamentals.roce": 25.0,
              "fundamentals.debt_to_equity": 0.1, "fundamentals.pe": 30.0,
              "forecast.rev_ttm_growth_pct": 30.0}
    WEAK = {"price.trend": "BELOW_BOTH", "price.distance_pct": 24.0,
            "fundamentals.yoy_growth_pct": -5.0, "fundamentals.roce": 6.0,
            "fundamentals.pe": 30.0, "forecast.rev_ttm_growth_pct": -3.0}

    def test_strong_and_weak_sheets(self):
        self.assertEqual(conclude.scorecard(self.STRONG)[0], "CONSTRUCTIVE")
        self.assertEqual(conclude.scorecard(self.WEAK)[0], "CAUTIOUS")

    def test_each_pillar_is_capped_so_no_family_dominates(self):
        stance, score, _ = conclude.scorecard({"price.trend": "UPTREND", "price.distance_pct": 1.0})
        self.assertEqual(score, 2)                 # +2 trend and +1 distance clip to +2
        self.assertEqual(stance, "MIXED")          # and one pillar alone is not enough data

    def test_missing_data_is_neutral_never_a_penalty(self):
        _, score, _ = conclude.scorecard({"price.ltp": 100.0})
        self.assertEqual(score, 0)

    def test_thin_sheet_is_mixed_not_a_guess(self):
        stance, _, rules = conclude.scorecard({"price.trend": "BELOW_BOTH"})
        self.assertEqual(stance, "MIXED")
        self.assertTrue(any("no lean" in r for r in rules))

    def test_unplanned_capacity_is_a_gap_not_a_penalty(self):
        a = conclude.scorecard(self.STRONG)[1]
        b = conclude.scorecard(dict(self.STRONG, **{"corporate.order_capacity_plan": "UNPLANNED"}))[1]
        self.assertEqual(a, b)

    def test_cheap_only_counts_when_growing(self):
        base = dict(self.WEAK, **{"fundamentals.pe_vs_industry_pct": -50.0})
        self.assertNotIn("cheaper than industry", " ".join(conclude.scorecard(base)[2]))
        grow = dict(base, **{"fundamentals.yoy_growth_pct": 25.0})
        self.assertIn("cheaper than industry", " ".join(conclude.scorecard(grow)[2]))

    def test_rules_name_the_fact_sheet_keys_they_used(self):
        _, _, rules = conclude.scorecard(self.STRONG)
        self.assertTrue(any("fundamentals.roce" in r for r in rules))


class _Resp:
    def __init__(self, content):
        self._c = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._c}}]}


class TestCall(unittest.TestCase):
    cfg = llm.LLMConfig(base_url="http://vllm:8000", model="phi-4-mini", api="openai")

    def test_request_shape_and_result(self):
        answer = json.dumps({"stance": "MIXED", "conclusion": "Fine.",
                             "positives": [], "concerns": [], "data_gaps": []})
        with mock.patch("requests.post", return_value=_Resp(answer)) as post:
            r = conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "2026-09-28")
        self.assertTrue(r.ok)
        url = post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        self.assertEqual(url, "http://vllm:8000/v1/chat/completions")
        self.assertEqual(body["model"], "phi-4-mini")
        self.assertEqual(body["temperature"], 0.0)
        self.assertEqual(body["response_format"]["type"], "json_schema")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn("price.ltp", body["messages"][1]["content"])

    def test_schema_limits_evidence_to_real_keys_and_caps_lengths(self):
        answer = json.dumps({"stance": "MIXED", "conclusion": "Fine.",
                             "positives": [], "concerns": [], "data_gaps": []})
        packet = conclude.build_packet(ROW)
        with mock.patch("requests.post", return_value=_Resp(answer)) as post:
            conclude.conclude(self.cfg, "ABC", ROW, packet, "2026-09-28")
        schema = post.call_args.kwargs["json"]["response_format"]["json_schema"]["schema"]
        ev = schema["properties"]["positives"]["items"]["properties"]["evidence"]
        self.assertEqual(ev["items"]["enum"], sorted(packet))
        self.assertEqual(ev["maxItems"], 4)
        self.assertEqual(schema["properties"]["concerns"]["maxItems"], 4)

    def _answer(self, text):
        return json.dumps({"conclusion": text, "positives": [], "concerns": []})

    def test_speculative_answer_is_retried_once_and_the_clean_one_kept(self):
        bad = self._answer("Trading below its high suggests undervaluation.")
        good = self._answer("The stock trades 12% below its high.")
        with mock.patch("requests.post", side_effect=[_Resp(bad), _Resp(good)]) as post:
            r = conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "d")
        self.assertEqual(post.call_count, 2)
        self.assertIn("rejected", post.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertIn("undervalu", post.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(r.conclusion, "The stock trades 12% below its high.")
        self.assertEqual(r.speculative, [])

    def test_truncated_conclusion_is_retried(self):
        cut = self._answer("The stock trades 12% below its")
        good = self._answer("The stock trades 12% below its high.")
        with mock.patch("requests.post", side_effect=[_Resp(cut), _Resp(good)]) as post:
            r = conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "d")
        self.assertEqual(post.call_count, 2)
        self.assertTrue(r.conclusion.endswith("high."))

    def test_clean_answer_is_not_retried(self):
        with mock.patch("requests.post", return_value=_Resp(self._answer("Fine."))) as post:
            conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "d")
        self.assertEqual(post.call_count, 1)

    def test_retry_that_is_no_better_keeps_the_first_answer(self):
        bad = self._answer("Suggests undervaluation.")
        worse = self._answer("Suggests undervaluation and upside")
        with mock.patch("requests.post", side_effect=[_Resp(bad), _Resp(worse)]):
            r = conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "d")
        self.assertEqual(r.conclusion, "Suggests undervaluation.")

    def test_non_json_reply_is_an_error_not_a_crash(self):
        with mock.patch("requests.post", return_value=_Resp("I cannot help")):
            r = conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "d")
        self.assertFalse(r.ok)

    def test_transport_error_is_an_error_not_a_crash(self):
        with mock.patch("requests.post", side_effect=ConnectionError("down")):
            r = conclude.conclude(self.cfg, "ABC", ROW, conclude.build_packet(ROW), "d")
        self.assertIn("ConnectionError", r.error)

    def test_empty_packet_makes_no_request(self):
        with mock.patch("requests.post") as post:
            r = conclude.conclude(self.cfg, "ABC", {}, {}, "d")
        post.assert_not_called()
        self.assertFalse(r.ok)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.dir = tempfile.mkdtemp()
        os.chdir(self.dir)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.addCleanup(os.chdir, self.cwd)
        os.makedirs("output")
        os.makedirs("data")
        pd.DataFrame([ROW, dict(ROW, symbol="XYZ", company="XYZ Ltd")]).to_csv(
            "output/ath_enriched_2026-09-28.csv", index=False)

    def _run(self, *argv, answer=None):
        import conclude as cli
        answer = answer or json.dumps({
            "stance": "CONSTRUCTIVE", "conclusion": "At a high.",
            "positives": [{"point": "New high", "evidence": ["price.bucket"]}],
            "concerns": [], "data_gaps": []})
        with mock.patch("requests.post", return_value=_Resp(answer)) as post, \
                mock.patch("scanner.llm.health", return_value=(True, "ok")):
            code = cli.main(list(argv))
        return code, post.call_count

    def test_writes_csv_and_second_run_reuses_stored_conclusions(self):
        code, calls = self._run("--workers", "1")
        self.assertEqual((code, calls), (0, 2))
        out = pd.read_csv("output/ath_conclusions_2026-09-28.csv")
        self.assertEqual(sorted(out["symbol"]), ["ABC", "XYZ"])
        code, calls = self._run("--workers", "1")
        self.assertEqual((code, calls), (0, 0))               # nothing changed: no model calls
        code, calls = self._run("--workers", "1", "--force")
        self.assertEqual(calls, 2)

    def test_failures_exit_2_and_do_not_reach_the_csv(self):
        code, _ = self._run("--workers", "1", answer="not json")
        self.assertEqual(code, 2)
        out = pd.read_csv("output/ath_conclusions_2026-09-28.csv")
        self.assertEqual(len(out), 0)

    def test_unreachable_server_exits_1(self):
        import conclude as cli
        with mock.patch("scanner.llm.health", return_value=(False, "refused")):
            self.assertEqual(cli.main([]), 1)


if __name__ == "__main__":
    unittest.main()
