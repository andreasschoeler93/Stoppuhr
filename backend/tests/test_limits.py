import unittest

import limits


class LimitsTests(unittest.TestCase):
    def test_defaults_when_nothing_stored(self):
        self.assertEqual(limits.merged(None), limits.defaults())
        self.assertEqual(limits.merged("kaputt"), limits.defaults())

    def test_stored_values_override_defaults(self):
        stored = {"taster": {"battery": {"values": [40, 20]}}}
        merged = limits.merged(stored)
        self.assertEqual(merged["taster"]["battery"]["values"], [40.0, 20.0])
        self.assertEqual(merged["taster"]["temp"], limits.defaults()["taster"]["temp"])

    def test_invalid_stored_values_are_ignored(self):
        stored = {"taster": {"battery": {"values": [10, 20]}, "temp": {"values": ["x", 1]}}}
        self.assertEqual(limits.merged(stored), limits.defaults())

    def test_validate_accepts_partial_input_and_commas(self):
        result, error = limits.validate({"taster": {"vbat": {"values": ["3,6", "3,4"]}}})
        self.assertIsNone(error)
        self.assertEqual(result["taster"]["vbat"]["values"], [3.6, 3.4])

    def test_validate_checks_order_per_direction(self):
        _, error = limits.validate({"taster": {"battery": {"values": [10, 20]}}})  # low: rot muss <= gelb sein
        self.assertIn("kleiner", error)
        _, error = limits.validate({"pi": {"cpu_temp": {"values": [80, 70]}}})  # high: rot muss >= gelb sein
        self.assertIn("größer", error)

    def test_validate_rejects_garbage(self):
        self.assertIsNotNone(limits.validate(None)[1])
        self.assertIsNotNone(limits.validate({"taster": {"temp": {"values": [1]}}})[1])
        self.assertIsNotNone(limits.validate({"taster": {"temp": {"values": [1, float("nan")]}}})[1])
        self.assertIsNotNone(limits.validate({"taster": {"temp": {"values": [True, 99]}}})[1])


if __name__ == "__main__":
    unittest.main()
