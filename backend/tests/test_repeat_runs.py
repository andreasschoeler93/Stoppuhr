import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class RepeatRunTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.client = stopwatch.app.test_client()
        self.load_state = patch.object(
            stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state)
        )
        self.save_state = patch.object(
            stopwatch,
            "save_state",
            side_effect=lambda state: self.state.update(copy.deepcopy(state)),
        )
        self.load_state.start()
        self.save_state.start()
        self.addCleanup(self.load_state.stop)
        self.addCleanup(self.save_state.stop)

    def test_selecting_a_used_run_prepares_next_attempt_without_deleting_times(self):
        original = {
            "starter": {"ts": 1000, "mac": "start"},
            "1": {"ts": 2500, "mac": "lane"},
        }
        self.state["triggers_per_run"] = {"5": copy.deepcopy(original)}

        with patch.object(stopwatch, "_stop_lockout_ms", return_value=5000):
            response = self.client.post("/api/current-run", json={"run": 5})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["current_key"], "5/2")
        self.assertEqual(self.state["triggers_per_run"]["5"], original)
        self.assertEqual(self.state["current_attempt"], 2)
        self.assertGreater(self.state["start_locked_until_ms"], 0)

    def test_long_press_aborts_running_attempt_and_is_idempotent(self):
        self.state["current_run"] = 5
        self.state["startcards_per_run"] = {"5": [{"Bahn": "1"}]}
        self.state["triggers_per_run"] = {
            "5": {
                "starter": {"ts": 1000, "mac": "start"},
                "1": {"ts": 2500, "mac": "lane"},
            }
        }
        self.state["assignments"]["mapping"] = {"starter": "AA:BB"}
        payload = {"mac": "AA:BB", "request_id": "press-1"}

        with patch.object(stopwatch, "_stop_lockout_ms", return_value=5000):
            first = self.client.post("/api/abort-run", json=payload)
            second = self.client.post("/api/abort-run", json=payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json["current_key"], "5/2")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json["current_key"], "5/2")
        self.assertEqual(
            self.state["start_locked_until_ms"], first.json["start_locked_until_ms"]
        )
        self.assertIn("5", self.state["triggers_per_run"])
        self.assertIn("5", self.state["aborted_attempts"])

    def test_start_is_rejected_until_abort_lockout_expires(self):
        self.state["current_run"] = 5
        self.state["current_attempt"] = 2
        self.state["start_locked_until_ms"] = 20_000
        self.state["settings"]["stop_lockout_s"] = "0"

        with patch.object(stopwatch, "now_ms", return_value=10_000):
            locked = self.client.post("/api/triggers", json={"test_lane": "starter"})
        self.assertEqual(locked.status_code, 423)
        self.assertEqual(locked.json["lockout_remaining_s"], 10)

        with patch.object(stopwatch, "now_ms", return_value=20_000):
            allowed = self.client.post("/api/triggers", json={"test_lane": "starter"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json["press"]["run_key"], "5/2")

    def test_triggers_are_written_to_the_prepared_attempt(self):
        self.state["current_run"] = 5
        self.state["current_attempt"] = 2
        self.state["settings"]["stop_lockout_s"] = "0"
        self.state["startcards_per_run"] = {"5": [{"Bahn": "1"}]}
        self.state["triggers_per_run"] = {
            "5": {
                "starter": {"ts": 1000, "mac": "start"},
                "1": {"ts": 2500, "mac": "lane"},
            }
        }

        with patch.object(stopwatch, "_write_heats_xml"):
            start = self.client.post("/api/triggers", json={"test_lane": "starter"})
            stop = self.client.post("/api/triggers", json={"test_lane": "1"})

        self.assertEqual(start.status_code, 200)
        self.assertEqual(start.json["press"]["run_key"], "5/2")
        self.assertEqual(stop.status_code, 200)
        self.assertIn("5/2", self.state["triggers_per_run"])
        self.assertEqual(self.state["triggers_per_run"]["5"]["1"]["ts"], 2500)

    def test_xml_keeps_the_original_and_exports_repeat_as_separate_heat(self):
        self.state["startcards_per_run"] = {"5": [{"Bahn": "1", "Wettkampf": "3"}]}
        self.state["triggers_per_run"] = {
            "5": {
                "starter": {"ts": 1000, "mac": "start"},
                "1": {"ts": 2500, "mac": "lane"},
            },
            "5/2": {
                "starter": {"ts": 5000, "mac": "start"},
                "1": {"ts": 6200, "mac": "lane"},
            },
            "5/3": {
                "starter": {"ts": 7000, "mac": "start"},
                "1": {"ts": 7500, "mac": "lane"},
            },
        }
        self.state["aborted_attempts"] = ["5/3"]
        self.state["current_run"] = 5
        self.state["current_attempt"] = 2

        heats = stopwatch._heats_for_xml(self.state)

        self.assertEqual(
            heats,
            [
                (5, 1, {1: 1500}),
                (5, 2, {1: 1200}),
            ],
        )
        self.assertIn("5/3", self.state["triggers_per_run"])


if __name__ == "__main__":
    unittest.main()
