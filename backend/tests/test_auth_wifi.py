import copy
import unittest
from unittest.mock import patch

import app as stopwatch
import wifi_config


class FakeRedis:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True


class AuthTests(unittest.TestCase):
    def setUp(self):
        stopwatch.app.config["AUTH_DISABLED"] = False
        self.addCleanup(stopwatch.app.config.pop, "AUTH_DISABLED", None)
        stopwatch.app.secret_key = None
        self.addCleanup(setattr, stopwatch.app, "secret_key", None)
        stopwatch._login_fails.clear()
        self.redis = FakeRedis()
        self.state = stopwatch._default_state()
        patches = [
            patch.object(stopwatch, "redis_store", self.redis),
            patch.object(stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state)),
            patch.object(stopwatch, "save_state"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = stopwatch.app.test_client()

    def _setup(self, user="chef", password="geheim1"):
        return self.client.post("/api/auth/setup", json={"user": user, "password": password})

    def test_without_account_ui_redirects_to_login(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/login"))
        self.assertIn("Zugang festlegen", self.client.get("/login").get_data(as_text=True))

    def test_api_requires_login(self):
        self.assertEqual(self.client.get("/api/settings").status_code, 401)

    def test_taster_endpoints_stay_open(self):
        self.assertEqual(self.client.get("/api/version").status_code, 200)
        self.assertEqual(self.client.get("/api/display?mac=AA").status_code, 200)

    def test_setup_once_then_login(self):
        self.assertTrue(self._setup().json["ok"])
        self.assertEqual(self.client.get("/api/settings").status_code, 200)
        self.assertEqual(self._setup("zweiter", "geheim2").status_code, 409)
        other = stopwatch.app.test_client()
        self.assertEqual(other.get("/api/settings").status_code, 401)
        self.assertEqual(other.post("/api/auth/login", json={"user": "chef", "password": "falsch"}).status_code, 401)
        self.assertEqual(other.post("/api/auth/login", json={"user": "chef", "password": "geheim1"}).status_code, 200)
        self.assertEqual(other.get("/api/settings").status_code, 200)

    def test_setup_rejects_short_password(self):
        self.assertEqual(self._setup(password="abc").status_code, 400)

    def test_lockout_after_failures(self):
        self._setup()
        other = stopwatch.app.test_client()
        for _ in range(stopwatch.LOGIN_MAX_FAILS):
            other.post("/api/auth/login", json={"user": "chef", "password": "x"})
        resp = other.post("/api/auth/login", json={"user": "chef", "password": "geheim1"})
        self.assertEqual(resp.status_code, 429)

    def test_change_password_invalidates_other_sessions(self):
        self._setup()
        other = stopwatch.app.test_client()
        other.post("/api/auth/login", json={"user": "chef", "password": "geheim1"})
        resp = self.client.post("/api/auth/change", json={"current": "geheim1", "user": "chef", "password": "neu12345"})
        self.assertTrue(resp.json["ok"])
        self.assertEqual(self.client.get("/api/settings").status_code, 200)
        self.assertEqual(other.get("/api/settings").status_code, 401)

    def test_change_needs_current_password(self):
        self._setup()
        resp = self.client.post("/api/auth/change", json={"current": "falsch", "user": "chef", "password": "neu12345"})
        self.assertEqual(resp.status_code, 403)

    def test_logout(self):
        self._setup()
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/settings").status_code, 401)


class WifiConfigTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        self.state = stopwatch._default_state()
        self.state["tasters"] = [{"mac": "AA", "name": "T1"}, {"mac": "BB", "name": "T2"}]
        stopwatch.app.config["AUTH_DISABLED"] = True
        patches = [
            patch.object(stopwatch, "save_state"),
            patch.object(stopwatch, "redis_store", self.redis),
            patch.object(stopwatch, "load_state", side_effect=lambda: copy.deepcopy(self.state)),
            patch.object(stopwatch.node_info, "cluster_status", return_value={"self": {"reachable": True, "hostname": "pi"}}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.client = stopwatch.app.test_client()

    def _save(self, **over):
        body = {"ssid1": "Koffer", "psk1": "kofferpass", "ssid2": "Bad", "psk2": "badpass123", **over}
        return self.client.post("/api/wifi-config", json=body)

    def test_save_validates(self):
        self.assertEqual(self._save(psk1="kurz").status_code, 400)
        self.assertEqual(self._save(ssid2='a"b').status_code, 400)
        self.assertEqual(self._save(ssid2="Koffer").status_code, 400)
        self.assertEqual(self._save().status_code, 200)

    def test_empty_password_keeps_old_and_no_change_is_rejected(self):
        self._save()
        self.assertEqual(self._save(psk1="", psk2="").status_code, 400)
        resp = self._save(ssid1="Neu", psk1="")
        self.assertEqual(resp.status_code, 200)
        cfg = wifi_config.load(self.redis)
        self.assertEqual(cfg["wifi1"], {"ssid": "Neu", "psk": "kofferpass"})

    def test_display_offers_until_acknowledged(self):
        self._save()
        version = wifi_config.load(self.redis)["version"]
        out = self.client.get("/api/display?mac=AA").json
        self.assertEqual(out["wifi_ssid1"], "Koffer")
        self.assertEqual(out["wifi_ver"], version)
        self.assertNotIn("wifi_ver", self.client.get("/api/display?mac=UNBEKANNT").json)
        self.state["vitals"]["AA"] = {"ts": stopwatch.now_ms(), "wv": version}
        self.assertNotIn("wifi_ver", self.client.get("/api/display?mac=AA").json)

    def test_pi_waits_for_online_tasters(self):
        self._save()
        cfg = wifi_config.load(self.redis)
        now = stopwatch.now_ms()
        self.assertFalse(wifi_config.ready_for_pi(cfg, self.state, now))  # keiner online
        self.state["vitals"] = {"AA": {"ts": now, "wv": cfg["version"]}, "BB": {"ts": now, "wv": None}}
        self.assertFalse(wifi_config.ready_for_pi(cfg, self.state, now))
        self.state["vitals"]["BB"]["wv"] = cfg["version"]
        self.assertTrue(wifi_config.ready_for_pi(cfg, self.state, now))
        # offline Taster blockieren nicht
        self.state["vitals"]["BB"] = {"ts": now - 120_000, "wv": None}
        self.assertTrue(wifi_config.ready_for_pi(cfg, self.state, now))

    def test_force(self):
        self._save()
        cfg = wifi_config.load(self.redis)
        self.assertFalse(wifi_config.ready_for_pi(cfg, self.state, stopwatch.now_ms()))
        self.assertTrue(self.client.post("/api/wifi-config/force").json["ok"])
        self.assertTrue(wifi_config.ready_for_pi(wifi_config.load(self.redis), self.state, stopwatch.now_ms()))


if __name__ == "__main__":
    unittest.main()
