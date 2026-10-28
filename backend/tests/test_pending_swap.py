import copy
import unittest
from unittest.mock import patch

import app as stopwatch


class PendingSwapTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.state["assignments"]["mapping"] = {"1": "A"}
        self.state["startcards_per_run"] = {"1": [{"Bahn": "1", "Name": "X", "Disziplin": "D"}]}
        self.state["current_run"] = 1
        self.client = stopwatch.app.test_client()
        for name, fn in (
            ("load_state", lambda: copy.deepcopy(self.state)),
            ("save_state", lambda s: self.state.update(copy.deepcopy(s))),
            ("_load_ota", lambda: None),
        ):
            p = patch.object(stopwatch, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def _assign(self, **extra):
        return self.client.post("/api/assign", json={"mac": "B", "lane": 1, **extra})

    def test_occupied_lane_only_marks_standby(self):
        resp = self._assign()
        self.assertTrue(resp.json["pending"])
        self.assertEqual(self.state["assignments"]["mapping"], {"1": "A"})
        self.assertEqual(self.state["assignments"]["pending"], {"1": "B"})
        display = self.client.get("/api/display?mac=B").json
        self.assertEqual(display["role"], "none")
        self.assertEqual(display["pending_lane"], "1")

    def test_free_lane_is_assigned_immediately(self):
        resp = self.client.post("/api/assign", json={"mac": "B", "lane": 2})
        self.assertNotIn("pending", resp.json)
        self.assertEqual(self.state["assignments"]["mapping"]["2"], "B")

    def test_first_press_swaps_roles_when_no_run_is_running(self):
        self._assign()
        resp = self.client.post("/api/triggers", json={"mac": "B", "ts": 1})
        self.assertTrue(resp.json["swapped"])
        self.assertEqual(self.state["assignments"]["mapping"], {"1": "B"})
        self.assertEqual(self.state["assignments"]["pending"], {})
        self.assertEqual(self.state["triggers_per_run"], {})
        self.assertEqual(self.client.get("/api/display?mac=A").json["role"], "none")
        self.assertEqual(self.client.get("/api/display?mac=B").json["role"], "lane")

    def test_press_during_running_run_keeps_standby(self):
        self.state["assignments"]["mapping"]["starter"] = "S"
        self.state["triggers_per_run"] = {"1": {"starter": {"ts": 10, "mac": "S"}}}
        self._assign()
        resp = self.client.post("/api/triggers", json={"mac": "B", "ts": 20})
        self.assertTrue(resp.json["ignored"])
        self.assertEqual(self.state["assignments"]["mapping"]["1"], "A")
        self.assertEqual(self.state["assignments"]["pending"], {"1": "B"})

    def test_immediate_flag_swaps_directly(self):
        self._assign(immediate=True)
        self.assertEqual(self.state["assignments"]["mapping"], {"1": "B"})

    def test_cancel_pending_removes_standby(self):
        self._assign()
        resp = self.client.post("/api/cancel-pending", json={"lane": 1})
        self.assertTrue(resp.json["removed"])
        self.assertEqual(self.state["assignments"]["pending"], {})
        self.assertEqual(self.state["assignments"]["mapping"], {"1": "A"})

    def test_unassign_removes_standby(self):
        self._assign()
        self.client.post("/api/unassign", json={"lane": 1})
        self.assertEqual(self.state["assignments"]["pending"], {})

    def test_mapping_lists_pending_lane_for_taster(self):
        self.state["tasters"] = [{"mac": "A"}, {"mac": "B"}]
        self.state["startcards"]["max_lane"] = 2
        self._assign()
        data = self.client.get("/api/mapping").json
        self.assertEqual(data["unmapped_taster"][0]["pending_lane"], "1")


if __name__ == "__main__":
    unittest.main()
