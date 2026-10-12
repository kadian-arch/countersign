import re
import time
import unittest

from fastapi.testclient import TestClient

from countersign import alerts
from countersign.web import create_app
from tests.test_web import backend

TOM = {"sender": "tom.kowalczyk@example.com", "tool": "refund_payment", "order_no": "10474", "amount": "129.00",
       "message": "The kettle arrived broken, could I have the full 129.00 back?"}
DANA = {"sender": "dana.whitfield@example.com", "tool": "refund_payment", "order_no": "10471", "amount": "9.50",
        "message": "The filters came crushed, could I have the 9.50 back?"}
MARCUS = {"sender": "marcus.reyes@example.com", "tool": "refund_payment", "order_no": "10472", "amount": "69.00",
          "message": "The grinder is faulty, could I have the 69.00 back?"}
OWNER_TOKEN = {"X-Owner-Token": "secret"}


class Outbox:
    def __init__(self):
        self.alerts, self.error = [], None

    def public(self):
        return {"address": "shop@mail.example", "ok": True, "checked": 1, "error": None}

    def reply(self, incoming, text):
        pass

    def send_alert(self, to, subject, text):
        self.alerts.append((to, subject, text))


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.mail = Outbox()
        self.app = create_app("live", owner_token="secret", llm=None, live_backend=backend, seeder=lambda ws: None, mailer=self.mail)
        self.client = TestClient(self.app)
        self.c = self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def wait_for(self, n):
        for _ in range(200):
            if len(self.mail.alerts) >= n:
                break
            time.sleep(0.02)
        time.sleep(0.1)   # long enough for an extra, wrong email to show up
        return self.mail.alerts

    def link(self, text):
        return re.search(r"http://127\.0\.0\.1:8000(/review/\d+\?sig=\S+)", text).group(1)

    def test_a_held_request_emails_the_owner_once_with_the_facts(self):
        self.assertEqual(self.c.post("/api/submit", json=TOM).json()["status"], "held")
        sent = self.wait_for(1)
        self.assertEqual(len(sent), 1)
        to, subject, text = sent[0]
        self.assertEqual(to, "owner@millstreetcoffee.example")
        self.assertEqual(subject, "Approval needed: Refund $129.00 on order #10474")
        self.assertIn("tom.kowalczyk@example.com", text)
        self.assertIn("Nothing has been sent to PayPal", text)
        self.assertIn("/review/", text)
        self.app.state.hub.live.alert_owner()
        self.assertEqual(len(self.wait_for(1)), 1)   # the same request is not announced twice

    def test_each_new_hold_gets_its_own_email_and_allowed_requests_get_none(self):
        self.assertEqual(self.c.post("/api/submit", json=DANA).json()["status"], "executed")
        self.c.post("/api/submit", json=TOM)
        self.c.post("/api/submit", json={**MARCUS, "amount": "69.00"})
        subjects = [s for _, s, _ in self.wait_for(1)]
        self.assertEqual(subjects.count("Approval needed: Refund $129.00 on order #10474"), 1)
        self.assertNotIn("Approval needed: Refund $9.50 on order #10471", subjects)

    def test_the_owner_can_switch_alerts_off(self):
        out = self.c.put("/api/settings", json={"alerts": False}, headers=OWNER_TOKEN)
        self.assertEqual(out.status_code, 200, out.text)
        self.c.post("/api/submit", json=TOM)
        self.assertEqual(self.wait_for(0), [])
        self.assertFalse(self.c.get("/api/state").json()["mailbox"]["alerts"])

    def test_the_link_shows_the_request_and_does_not_act_until_a_button_is_pressed(self):
        self.c.post("/api/submit", json=TOM)
        path = self.link(self.wait_for(1)[0][2])
        page = self.c.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Refund $129.00 on order #10474", page.text)
        self.assertIn("Approve", page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertEqual(len(self.c.get("/api/state").json()["pending"]), 1)   # opening the link changed nothing

    def test_approving_from_the_email_runs_the_refund_through_the_guard(self):
        self.c.post("/api/submit", json=TOM)
        path = self.link(self.wait_for(1)[0][2])
        sig = path.split("sig=")[1]
        done = self.c.post(path.split("?")[0], content=f"sig={sig}&decision=approve", headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertIn("Approved", done.text)
        state = self.c.get("/api/state").json()
        self.assertEqual((state["pending"], state["money"]["moved"]), ([], "129.00"))
        again = self.c.get(path)
        self.assertIn("Already decided", again.text)

    def test_refusing_from_the_email_sends_nothing(self):
        self.c.post("/api/submit", json=TOM)
        path = self.link(self.wait_for(1)[0][2])
        sig = path.split("sig=")[1]
        done = self.c.post(path.split("?")[0], content=f"sig={sig}&decision=reject", headers={"content-type": "application/x-www-form-urlencoded"})
        self.assertIn("Refused", done.text)
        self.assertEqual(self.c.get("/api/state").json()["money"]["moved"], "0")

    def test_a_link_for_one_request_cannot_decide_another_and_a_bad_one_is_refused(self):
        self.c.post("/api/submit", json=TOM)
        self.c.post("/api/submit", json={**MARCUS, "sender": "marcus.reyes@example.com", "amount": "69.00", "order_no": "10472"})
        first = self.link(self.wait_for(1)[0][2])
        sig = first.split("sig=")[1]
        pending = [p["id"] for p in self.c.get("/api/state").json()["pending"]]
        other = next(i for i in pending if f"/review/{i}?" not in first) if len(pending) > 1 else pending[0] + 1
        form = {"content-type": "application/x-www-form-urlencoded"}
        self.assertEqual(self.c.post(f"/review/{other}", content=f"sig={sig}&decision=approve", headers=form).status_code, 403)
        self.assertEqual(self.c.get(first.split("sig=")[0] + "sig=1.abc").status_code, 403)
        self.assertEqual(self.c.get(first.split("?")[0]).status_code, 403)
        self.assertEqual(self.c.get("/review/999?sig=" + sig).status_code, 403)


class LinkTests(unittest.TestCase):
    def test_signatures_are_for_one_action_and_expire(self):
        sig = alerts.sign("secret", 7, now=1000)
        self.assertTrue(alerts.valid("secret", 7, sig, now=1000 + 60))
        self.assertFalse(alerts.valid("secret", 8, sig, now=1000 + 60))
        self.assertFalse(alerts.valid("other", 7, sig, now=1000 + 60))
        self.assertFalse(alerts.valid("secret", 7, sig, now=1000 + alerts.TTL + 1))
        self.assertFalse(alerts.valid("secret", 7, "", now=1000))
        self.assertFalse(alerts.valid("secret", 7, "garbage", now=1000))
        self.assertFalse(alerts.valid("secret", 7, None, now=1000))

    def test_everything_a_stranger_wrote_is_escaped_on_the_page(self):
        row = {"tool": "send_payout", "amount": "5.00", "sender": '<script>alert(1)</script>"@x.example',
               "args": {"receiver": "<img src=x onerror=alert(2)>", "invoice_id": "1"},
               "reasons": [{"code": "x", "message": "<b>bold</b> reason"}]}

        class Store:
            def order_by_capture(self, c):
                return None
        page = alerts.review_page(row, Store(), "Shop <i>", 3, "1.abc'><script>")
        for raw in ("<script>alert(1)", "<img src=x", "<b>bold</b>", "Shop <i>", "'><script>"):
            self.assertNotIn(raw, page)

    def test_no_more_than_a_few_alert_emails_an_hour(self):
        from countersign.web import Hub
        hub = Hub("sim", "secret", None)
        self.assertEqual([hub.allow_alert() for _ in range(alerts.MAX_PER_HOUR + 2)], [True] * alerts.MAX_PER_HOUR + [False] * 2)


if __name__ == "__main__":
    unittest.main()
