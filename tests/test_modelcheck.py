import unittest

from scanner import modelcheck as mc


def row(**kw):
    base = {"symbol": "X", "stance": "MIXED", "conclusion": "A clean conclusion.",
            "positives": "['a']", "concerns": "['b']", "speculative_phrases": "[]",
            "unverified_numbers": "[]"}
    base.update(kw)
    return base


def rows(n, **kw):
    return [row(symbol=f"S{i}", **kw) for i in range(n)]


class TestMeasure(unittest.TestCase):
    def test_clean_run_passes(self):
        m = mc.measure(rows(40), 40, 100)
        self.assertEqual((m.completed, m.failed), (40, 0))
        self.assertEqual(mc.verdict(m), (True, []))

    def test_each_defect_counted(self):
        data = [row(speculative_phrases="['upside']"), row(unverified_numbers="['12.5']"),
                row(conclusion="Cut off in the mid"), row(positives="[]", concerns="[]"),
                row()]
        m = mc.measure(data, 5, 1)
        self.assertEqual((m.speculative, m.unverified, m.truncated, m.empty), (1, 1, 1, 1))

    def test_missing_side_for_stance_is_empty(self):
        m = mc.measure([row(stance="CONSTRUCTIVE", positives="[]"),
                        row(stance="CAUTIOUS", concerns="[]"),
                        row(stance="CAUTIOUS", positives="[]"),
                        row(stance="MIXED", positives="[]")], 4, 1)
        self.assertEqual(m.empty, 2)

    def test_missing_stocks_are_failures(self):
        m = mc.measure(rows(30), 40, 1)
        self.assertEqual(m.failed, 10)
        self.assertFalse(mc.verdict(m)[0])

    def test_blank_conclusion_is_not_completed(self):
        m = mc.measure([row(conclusion="")], 1, 1)
        self.assertEqual((m.completed, m.failed), (0, 1))

    def test_empty_run_fails(self):
        m = mc.measure([], 40, 1)
        self.assertEqual(mc.verdict(m), (False, ["no conclusions produced"]))


class TestThresholds(unittest.TestCase):
    def test_ceiling_is_inclusive(self):
        data = rows(36) + rows(4, speculative_phrases="['upside']")   # 10%
        self.assertTrue(mc.verdict(mc.measure(data, 40, 1))[0])

    def test_over_ceiling_fails(self):
        data = rows(35) + rows(5, speculative_phrases="['upside']")   # 12.5%
        ok, reasons = mc.verdict(mc.measure(data, 40, 1))
        self.assertFalse(ok)
        self.assertIn("speculative 12.5% > 10.0%", reasons)

    def test_phi_mxfp4_reference_fails(self):
        m = mc.Metrics(requested=290, completed=290, speculative=129, empty=83,
                       truncated=4, unverified=25)
        ok, reasons = mc.verdict(m)
        self.assertFalse(ok)
        self.assertEqual(len(reasons), 2)   # speculative and empty

    def test_qwen3_4b_reference_passes(self):
        m = mc.Metrics(requested=290, completed=290, speculative=5, empty=8,
                       truncated=0, unverified=10)
        self.assertTrue(mc.verdict(m)[0])


class TestRank(unittest.TestCase):
    def test_passing_then_fewest_failures_then_fastest(self):
        good_fast = mc.measure(rows(40), 40, 50)
        good_slow = mc.measure(rows(40), 40, 90)
        bad = mc.measure(rows(20), 40, 10)
        order = [k for k, _ in mc.rank([("bad", bad), ("slow", good_slow), ("fast", good_fast)])]
        self.assertEqual(order, ["fast", "slow", "bad"])


class TestRegistry(unittest.TestCase):
    def test_keys_unique(self):
        keys = [c.key for c in mc.CANDIDATES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_budget_matches_utilisation(self):
        self.assertAlmostEqual(mc.GPU_UTILIZATION * 8, mc.VRAM_BUDGET_GIB, delta=0.1)

    def test_env_uses_fp8_kv_and_budget(self):
        for c in mc.CANDIDATES:
            env = c.env()
            self.assertEqual(env["KV_CACHE_DTYPE"], "fp8")
            self.assertEqual(env["GPU_MEMORY_UTILIZATION"], "0.56")
            self.assertEqual(env["SERVED_NAME"], c.key)

    def test_kv_override(self):
        self.assertEqual(mc.CANDIDATES[0].env(kv_cache_dtype="")["KV_CACHE_DTYPE"], "")

    def test_no_credentials_in_env(self):
        for c in mc.CANDIDATES:
            for k in c.env():
                self.assertFalse(any(w in k for w in ("API_KEY", "SECRET", "ACCESS_TOKEN", "HF_TOKEN")), k)


if __name__ == "__main__":
    unittest.main()
