import unittest

import finish


class FinishTests(unittest.TestCase):
    def test_finish_times(self):
        self.assertEqual(finish.finish_times(1000, [{"ts": 11000}, {"ts": 12500}]), [10000, 11500])

    def test_auto_match_by_proximity(self):
        lanes = {"1": 10000, "2": 11000}
        result = finish.match(lanes, [11050, 10020], {})
        self.assertEqual(result["1"], {"index": 1, "manual": False, "delta_ms": 20})
        self.assertEqual(result["2"], {"index": 0, "manual": False, "delta_ms": 50})

    def test_too_far_apart_is_not_matched(self):
        result = finish.match({"1": 10000}, [20000], {})
        self.assertEqual(result, {})
        self.assertEqual(finish.unassigned([20000], result), [0])

    def test_manual_wins_and_is_not_reused(self):
        result = finish.match({"1": 10000, "2": 10100}, [10050], {"2": 0})
        self.assertEqual(result["2"]["manual"], True)
        self.assertNotIn("1", result)

    def test_manual_without_own_time_has_no_delta(self):
        result = finish.match({}, [9000], {"3": 0})
        self.assertIsNone(result["3"]["delta_ms"])

    def test_invalid_manual_index_ignored(self):
        self.assertEqual(finish.match({}, [1], {"1": 5}), {})

    def test_parked_time_is_not_matched_automatically(self):
        result = finish.match({"1": 10000}, [10020], {}, [0])
        self.assertEqual(result, {})
        self.assertEqual(finish.unassigned([10020], result), [0])


if __name__ == "__main__":
    unittest.main()
