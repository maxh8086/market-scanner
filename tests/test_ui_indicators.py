import unittest
from ui.app.indicators import sma, ema, rsi

class TestIndicators(unittest.TestCase):
    def test_sma_known_values(self):
        self.assertEqual(sma([1,2,3,4,5],3), [None, None, 2.0, 3.0, 4.0])

    def test_sma_empty(self):
        self.assertEqual(sma([],3), [])

    def test_ema_known_values(self):
        self.assertEqual(ema([1,2,3,4,5],3), [None, None, 2.0, 3.0, 4.0])

    def test_ema_short_input(self):
        self.assertEqual(ema([1],3), [None])

    def test_rsi_all_gains(self):
        self.assertEqual(rsi([1,2,3,4,5,6],2), [None, None, 100.0, 100.0, 100.0, 100.0])

    def test_rsi_known_value(self):
        self.assertAlmostEqual(rsi([1,2,3,2,4,5,4,6,7,6,8,9,8,10,11],14)[14], 77.78, places=2)

    def test_rsi_length_matches_input(self):
        closes = [1,2,3,2,4,5,4,6,7,6,8,9,8,10,11]
        self.assertEqual(len(rsi(closes,14)), len(closes))

    def test_invalid_period_raises(self):
        with self.assertRaises(ValueError):
            sma([1,2],0)
        with self.assertRaises(ValueError):
            ema([1,2],0)
        with self.assertRaises(ValueError):
            rsi([1,2],0)

if __name__ == "__main__":
    unittest.main()