import copy
import unittest
from unittest.mock import patch

import app as stopwatch
import pi_update


class PiUpdateTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.client = stopwatch.app.test_client()
        patches = [
            patch.object(stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state)),
            patch.object(pi_update, "available", return_value=True),
            patch.object(pi_update, "switch_to", return_value="abc1234"),
            patch.object(stopwatch.threading, "Timer"),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def _deploy(self, **extra):
        return self.client.post("/api/pi-update/deploy", json={"tag": "v0.7.0", **extra})

    def test_deploy_switches_and_schedules_restart(self):
        resp = self._deploy()
        self.assertTrue(resp.json["ok"])
        self.mocks[2].assert_called_once_with("v0.7.0")
        self.mocks[3].return_value.start.assert_called_once()

    def test_invalid_tag_is_rejected(self):
        resp = self.client.post("/api/pi-update/deploy", json={"tag": "main; rm -rf /"})
        self.assertEqual(resp.status_code, 400)
        self.mocks[2].assert_not_called()

    def test_blocked_while_run_is_running(self):
        self.state["triggers_per_run"] = {"1": {"starter": {"ts": 1}}}
        self.state["current_run"] = 1
        self.assertEqual(self._deploy(confirm="UPDATE").status_code, 409)
        self.mocks[2].assert_not_called()

    def test_locked_after_competition_start_without_confirmation(self):
        self.state["triggers_per_run"] = {"1": {"starter": {"ts": 1}}}
        self.state["run_finished_ts"] = 5
        self.assertEqual(self._deploy().status_code, 409)
        self.assertEqual(self._deploy(confirm="UPDATE").status_code, 200)

    def test_failed_switch_returns_error_and_no_restart(self):
        self.mocks[2].side_effect = RuntimeError("dirty")
        resp = self._deploy()
        self.assertEqual(resp.status_code, 500)
        self.mocks[3].return_value.start.assert_not_called()

    def test_tag_parser(self):
        self.assertEqual(pi_update.parse_tag("v0.7.1"), (0, 7, 1))
        self.assertIsNone(pi_update.parse_tag("v0.7.1-pi"))
        self.assertIsNone(pi_update.parse_tag("--upload-pack=x"))


if __name__ == "__main__":
    unittest.main()
