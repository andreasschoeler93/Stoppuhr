import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import app as stopwatch
import firmware_store


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


class FirmwareUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with open(os.path.join(self.tmp.name, "v0.11.0.bin"), "wb") as f:
            f.write(b"\xe9" + b"x" * 99)
        self.state = stopwatch._default_state()
        self.state["tasters"] = [{"mac": "A", "name": "A", "letter": "A"}, {"mac": "B", "name": "B", "letter": "B"}]
        now = stopwatch.now_ms()
        self.state["vitals"] = {"A": {"ts": now, "fw": "v0.10.6"}, "B": {"ts": now - 600_000, "fw": "v0.10.6"}}
        self.redis = FakeRedis()
        self.client = stopwatch.app.test_client()
        patches = [
            patch.object(stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state)),
            patch.object(stopwatch, "redis_store", self.redis),
            patch.object(firmware_store, "CACHE_DIR", self.tmp.name),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _deploy(self, **extra):
        return self.client.post("/api/firmware/deploy", json={"tag": "v0.11.0", **extra})

    def test_only_online_tasters_get_the_offer(self):
        self.assertTrue(self._deploy().json["ok"])
        self.assertEqual(json.loads(self.redis.get(stopwatch.OTA_KEY))["macs"], ["A"])
        offer = self.client.get("/api/display?mac=A").json
        self.assertEqual(offer["ota_version"], "v0.11.0")
        self.assertEqual(offer["ota_size"], 100)
        self.assertEqual(len(offer["ota_md5"]), 32)
        self.assertNotIn("ota_version", self.client.get("/api/display?mac=B").json)

    def test_download_only_for_offered_taster(self):
        self._deploy()
        resp = self.client.get("/api/firmware/download?mac=A")
        self.addCleanup(resp.close)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get("/api/firmware/download?mac=B").status_code, 404)

    def test_locked_after_competition_start_without_confirmation(self):
        self.state["triggers_per_run"] = {"1": {"starter": {"ts": 1}}}
        resp = self._deploy()
        self.assertEqual(resp.status_code, 409)
        self.assertIsNone(self.redis.get(stopwatch.OTA_KEY))
        self.assertEqual(self._deploy(confirm="falsch").status_code, 409)
        self.assertEqual(self._deploy(confirm="UPDATE").status_code, 200)

    def test_no_offer_while_run_is_running(self):
        self._deploy()
        self.state["triggers_per_run"] = {"1": {"starter": {"ts": 1}}}
        self.state["current_run"] = 1
        self.assertNotIn("ota_version", self.client.get("/api/display?mac=A").json)

    def test_no_offer_after_failure_or_when_already_updated(self):
        self._deploy()
        self.client.post("/api/ota-status", json={"mac": "A", "ok": False, "msg": "http"})
        self.assertNotIn("ota_version", self.client.get("/api/display?mac=A").json)
        self._deploy()
        self.state["vitals"]["A"]["fw"] = "v0.11.0"
        self.assertNotIn("ota_version", self.client.get("/api/display?mac=A").json)

    def test_invalid_tag_is_rejected(self):
        resp = self.client.post("/api/firmware/deploy", json={"tag": "../../etc/passwd"})
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
