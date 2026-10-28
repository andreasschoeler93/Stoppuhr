import copy
import unittest
from unittest.mock import patch

import app as stopwatch
import node_info


class ClusterStatusTests(unittest.TestCase):
    def setUp(self):
        self.state = stopwatch._default_state()
        self.client = stopwatch.app.test_client()
        for name, fn in (
            ("load_state", lambda: copy.deepcopy(self.state)),
            ("save_state", lambda s: None),
        ):
            p = patch.object(stopwatch, name, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def _node(self, kind, vip):
        return {"hostname": kind, "kind": kind, "has_vip": vip, "reachable": True, "configured": True}

    def test_active_node_is_the_one_holding_the_vip(self):
        own = self._node("koffer", False)
        peer = self._node("bad", True)
        with patch.object(node_info, "collect", return_value=own), patch.object(
            node_info, "fetch_peer", return_value=peer
        ):
            data = self.client.get("/api/cluster-status").json
        self.assertTrue(data["two_pi"])
        self.assertEqual(data["active_kind"], "bad")

    def test_single_pi_mode_reports_no_two_pi(self):
        with patch.object(node_info, "collect", return_value=self._node("", True)), patch.object(
            node_info, "fetch_peer", return_value={"reachable": False, "configured": False}
        ):
            data = self.client.get("/api/cluster-status").json
        self.assertFalse(data["two_pi"])

    def test_unreachable_peer_is_reported(self):
        with patch.object(node_info, "collect", return_value=self._node("koffer", True)), patch.object(
            node_info, "fetch_peer", return_value={"reachable": False, "configured": True}
        ):
            data = self.client.get("/api/cluster-status").json
        self.assertFalse(data["peer"]["reachable"])
        self.assertEqual(data["active_kind"], "koffer")

    def test_tasters_are_counted_per_wifi(self):
        now = stopwatch.now_ms()
        self.state["tasters"] = [{"mac": "A"}, {"mac": "B"}]
        self.state["vitals"] = {"A": {"ts": now, "ssid": "Bad"}, "B": {"ts": now, "ssid": "Koffer"}}
        with patch.object(node_info, "collect", return_value=self._node("", True)), patch.object(
            node_info, "fetch_peer", return_value={"reachable": False, "configured": False}
        ):
            data = self.client.get("/api/cluster-status").json
        self.assertEqual(data["tasters_per_wifi"], {"Bad": 1, "Koffer": 1})


if __name__ == "__main__":
    unittest.main()
