import time
import unittest
from unittest.mock import patch

import app as stopwatch
import ladekoffer


class FakeRedis:
    def __init__(self, fail=False):
        self.data = {}
        self.fail = fail

    def set(self, key, value):
        if self.fail:
            raise RuntimeError("READONLY")
        self.data[key] = value

    def get(self, key):
        if self.fail:
            raise RuntimeError("down")
        return self.data.get(key)


def slot(n, present=True, charging=False, full=True, fault=False, vbat=4.15):
    return {"n": n, "present": present, "charging": charging, "full": full, "fault": fault, "vbat": vbat}


def payload(**over):
    p = {"mac": "AA:BB", "fw": "v0.1.0", "uptime_s": 10, "rssi": -50, "temp": 24.5, "humidity": 40,
         "aht_ok": True, "temp_alarm": False, "i2c_ok": True, "light": "green", "fault": False,
         "muted": False, "slots": [slot(n) for n in range(1, 11)]}
    p.update(over)
    return p


class SanitizeTests(unittest.TestCase):
    def test_rejects_garbage(self):
        self.assertIsNone(ladekoffer.sanitize(None))
        self.assertIsNone(ladekoffer.sanitize({"slots": "x"}))
        self.assertIsNone(ladekoffer.sanitize([]))

    def test_limits_and_types(self):
        s = ladekoffer.sanitize(payload(light="disco", temp="heiss", mac="x" * 100,
                                        slots=[slot(11), slot(0), slot(3, vbat=float("nan")), "x"]))
        self.assertEqual(s["light"], "off")
        self.assertIsNone(s["temp"])
        self.assertEqual(len(s["mac"]), 32)
        self.assertEqual([x["n"] for x in s["slots"]], [3])
        self.assertIsNone(s["slots"][0]["vbat"])


class EvaluateTests(unittest.TestCase):
    NOW = 1_000_000

    def _status(self, **over):
        s = ladekoffer.sanitize(payload(**over))
        s["ts"] = self.NOW
        return s

    def test_unknown(self):
        self.assertFalse(ladekoffer.evaluate(None, self.NOW)["known"])

    def test_ready(self):
        e = ladekoffer.evaluate(self._status(), self.NOW + 1000)
        self.assertEqual(e["state"], "bereit")
        self.assertEqual(e["messages"], [{"level": "ok", "text": "Alle 10 Taster sind geladen."}])

    def test_charging_and_missing(self):
        slots = [slot(n) for n in range(1, 11)]
        slots[1] = slot(2, charging=True, full=False, vbat=3.8)
        slots[4] = slot(5, present=False, full=False, vbat=0.0)
        e = ladekoffer.evaluate(self._status(slots=slots), self.NOW)
        self.assertEqual(e["state"], "laedt")
        self.assertEqual(e["counts"], {"present": 9, "charging": 1, "full": 8, "missing": [5]})
        texts = [m["text"] for m in e["messages"]]
        self.assertIn("Nicht im Koffer: Platz 5.", texts)
        self.assertIn("1 Taster laden noch: Platz 2.", texts)

    def test_temperature_alarm_is_error(self):
        e = ladekoffer.evaluate(self._status(temp_alarm=True, fault=True, temp=61.2, light="red"), self.NOW)
        self.assertEqual(e["state"], "fehler")
        self.assertEqual(e["messages"][0], {"level": "error", "text": "Übertemperatur im Ladekoffer (61,2 °C)."})

    def test_slot_fault_and_sensor(self):
        slots = [slot(n) for n in range(1, 11)]
        slots[6] = slot(7, fault=True, vbat=4.4)
        e = ladekoffer.evaluate(self._status(slots=slots, aht_ok=False, fault=True), self.NOW)
        self.assertEqual(e["state"], "fehler")
        texts = [m["text"] for m in e["messages"]]
        self.assertIn("Platz 7: Akkuspannung zu hoch (4,40 V).", texts)
        self.assertTrue(any("AHT20" in t for t in texts))

    def test_offline(self):
        e = ladekoffer.evaluate(self._status(), self.NOW + ladekoffer.OFFLINE_AFTER_MS + 120_000)
        self.assertFalse(e["online"])
        self.assertEqual(e["state"], "offline")
        self.assertEqual(e["messages"][0]["level"], "warn")


class EndpointTests(unittest.TestCase):
    def setUp(self):
        ladekoffer.reset_memory()
        self.addCleanup(ladekoffer.reset_memory)
        self.redis = FakeRedis()
        p = patch.object(stopwatch, "redis_store", self.redis)
        p.start()
        self.addCleanup(p.stop)
        stopwatch.app.config["AUTH_DISABLED"] = False
        self.client = stopwatch.app.test_client()

    def test_post_is_open_without_login_and_get_is_not(self):
        r = self.client.post("/api/charger", json=payload())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/charger").status_code, 401)

    def test_roundtrip(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.assertFalse(self.client.get("/api/charger").get_json()["known"])
        self.client.post("/api/charger", json=payload())
        body = self.client.get("/api/charger").get_json()
        self.assertTrue(body["known"] and body["online"])
        self.assertEqual(body["state"], "bereit")
        self.assertLess(abs(body["status"]["ts"] - int(time.time() * 1000)), 5000)

    def test_invalid_payload(self):
        self.assertEqual(self.client.post("/api/charger", json={"x": 1}).status_code, 400)

    def test_redis_down_still_works(self):
        stopwatch.app.config["AUTH_DISABLED"] = True
        self.redis.fail = True
        self.assertEqual(self.client.post("/api/charger", json=payload()).status_code, 200)
        self.assertTrue(self.client.get("/api/charger").get_json()["known"])


if __name__ == "__main__":
    unittest.main()
