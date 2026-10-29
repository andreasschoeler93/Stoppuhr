import unittest

import vitals_history


class FakeRedis:
    def __init__(self):
        self.lists = {}

    def pipeline(self):
        return self

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def ltrim(self, key, start, end):
        self.lists[key] = self.lists[key][start:] if start < 0 else self.lists[key]

    def execute(self):
        return []

    def lrange(self, key, start, end):
        return list(self.lists.get(key, []))


class VitalsHistoryTest(unittest.TestCase):
    def test_add_and_filter(self):
        r = FakeRedis()
        vitals_history.add(r, "AA", 1000, {"battery": 80, "vbat": 3.9, "temp": 21.5, "humidity": 40, "rssi": -60})
        vitals_history.add(r, "AA", 2000, {"battery": None, "temp": "x"})
        self.assertEqual(len(vitals_history.history(r, "AA")), 2)
        pts = vitals_history.history(r, "AA", since_ms=1500)
        self.assertEqual(pts, [[2000, None, None, None, None, None]])
        self.assertEqual(vitals_history.history(r, "BB"), [])

    def test_limit(self):
        r = FakeRedis()
        for i in range(vitals_history.MAX_POINTS + 5):
            vitals_history.add(r, "AA", i, {"battery": 1})
        self.assertEqual(len(r.lists[vitals_history.KEY_PREFIX + "AA"]), vitals_history.MAX_POINTS)

    def test_errors_ignored(self):
        vitals_history.add(object(), "AA", 1, {})
        self.assertEqual(vitals_history.history(object(), "AA"), [])


if __name__ == "__main__":
    unittest.main()
