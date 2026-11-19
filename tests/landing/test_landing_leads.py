"""Landing page form service (landing/lead_service.py): synthetic, offline tests for HTTP, consent,
concurrency, persistence and failure recovery. Moved from the landing page release in 7.9.7."""
import contextlib
import hashlib
import http.client
import io
import json
import os
import runpy
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import urlencode

import lead_service as app


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = app.LeadStore(self.root)

    def test_email_validation(self):
        self.assertEqual(app.normalize_email("  TEST+launch@Example.ORG "), "test+launch@example.org")
        self.assertEqual(app.normalize_email("a@b\u00fccher.example"), "a@xn--bcher-kva.example")
        bad = ["a", "", "a@", "@example.org", "x" * 65 + "@example.org", ".a@example.org",
               "a.@example.org", "a..b@example.org", "x y@example.org", "a@-example.org", "a@example",
               "a\r\nb@example.org", "a@" + ".".join(["x" * 63] * 5), "a@\ud800.example"]
        for value in bad:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                app.normalize_email(value)

    def test_persistence_consent_and_duplicate_retries(self):
        self.store.add("a@example.test", "en")
        original = self.store.records()[0][1]
        self.assertEqual(original["email"], "a@example.test")
        self.assertEqual(original["consent_text"], app.CONSENT["en"])
        self.assertFalse(original["address_verified"])
        self.store.add("a@example.test", "de")
        restarted = app.LeadStore(self.root)
        self.assertEqual(restarted.records()[0][1], original)

    def test_concurrent_repeated_posts_are_unique(self):
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda n: self.store.add(f"person{n % 4}@example.test", "de"), range(48)))
        self.assertEqual(len(self.store.records()), 4)
        self.assertFalse(list(self.root.glob(".pending-*")))

    def test_atomic_failure_does_not_leave_half_a_record(self):
        with patch.object(app.os, "replace", side_effect=OSError("synthetic disk failure")):
            with self.assertRaises(OSError):
                self.store.add("a@example.test", "de")
        self.assertEqual(list(self.root.iterdir()), [])
        self.store.add("a@example.test", "de")
        self.assertEqual(len(self.store.records()), 1)

    def test_prune_and_individual_deletion(self):
        self.store.add("a@example.test", "de")
        now = datetime.now(UTC)
        self.assertEqual(self.store.prune(365, now), 0)
        path, record = self.store.records()[0]
        record["created_at"] = (now - timedelta(days=366)).isoformat()
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(self.store.prune(365, now), 1)
        self.store.add("b@example.test", "en")
        self.store.remove("b@example.test")
        self.store.remove("b@example.test")
        self.assertEqual(self.store.records(), [])

    def test_bad_filename_and_symlink_are_rejected(self):
        self.store.add("a@example.test", "de")
        path = self.store.records()[0][0]
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            self.store.records()
        path.rename(self.root / "invalid.json")
        with self.assertRaises(ValueError):
            self.store.records()

    def test_cli_operations_and_entry_point(self):
        self.store.add("a@example.test", "de")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            app.main(["export", "--data-dir", str(self.root)])
        self.assertEqual(json.loads(output.getvalue())["email"], "a@example.test")
        with contextlib.redirect_stdout(io.StringIO()):
            app.main(["prune", "--data-dir", str(self.root)])
            app.main(["delete", "--data-dir", str(self.root), "--email", "A@example.test"])
        self.assertEqual(self.store.records(), [])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.main(["delete", "--data-dir", str(self.root)])
        with patch.object(app, "LeadServer") as server:
            app.main(["serve", "--data-dir", str(self.root), "--port", "9876", "--allow-origin", "https://example.test"])
            self.assertEqual(server.call_args.args[0], ("127.0.0.1", 9876))
            server.return_value.__enter__.return_value.serve_forever.assert_called_once()
        with patch("sys.argv", ["lead_service", "export", "--data-dir", str(self.root)]):
            runpy.run_module("lead_service", run_name="__main__")


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.store = app.LeadStore(Path(cls.temp.name))
        cls.server = app.LeadServer(("127.0.0.1", 0), cls.store, {"https://inboxstride.de", "https://www.inboxstride.de"})
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)
        cls.temp.cleanup()

    def request(self, body=None, *, path="/api/interest", method="POST", headers=None):
        defaults = {"Origin": "https://inboxstride.de", "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded"}
        defaults.update(headers or {})
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        connection.request(method, path, body, defaults)
        result = connection.getresponse()
        response = result.status, dict(result.headers), result.read()
        connection.close()
        return response

    def test_valid_form_and_no_javascript_fallback(self):
        status, headers, body = self.request(urlencode({"email": "http@example.test", "consent": "yes", "lang": "en"}))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["message"], app.MESSAGES["en"]["success"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        for language, target in [("de", "/danke/"), ("en", "/en/thanks/")]:
            status, headers, body = self.request(urlencode({"email": "fallback@example.test", "consent": "yes", "lang": language}),
                                                 headers={"Accept": "text/html"})
            self.assertEqual((status, headers["Location"], body), (303, target, b""))

    def test_duplicate_has_identical_result(self):
        body = urlencode({"email": "duplicate@example.test", "consent": "yes"})
        first = self.request(body)
        second = self.request(body)
        self.assertEqual((first[0], first[2]), (second[0], second[2]))

    def test_spam_trap_never_saves(self):
        count = len(self.store.records())
        self.assertEqual(self.request(urlencode({"website": "spam.test", "email": "bot@example.test"}))[0], 200)
        self.assertEqual(len(self.store.records()), count)

    def test_validation_and_consent(self):
        for values in [{}, {"email": "a@example.test"}, {"email": "bad", "consent": "yes"},
                       {"email": "a@example.test", "consent": "no"}]:
            status, _headers, body = self.request(urlencode(values) or "lang=en")
            self.assertEqual(status, 400)
            self.assertFalse(json.loads(body)["ok"])
        status, headers, body = self.request("email=bad&lang=en", headers={"Accept": "text/html"})
        self.assertEqual(status, 400)
        self.assertIn(b'/en/#interest', body)
        self.assertIn("text/html", headers["Content-Type"])

    def test_wrong_origin_type_and_routes(self):
        for origin in ["https://evil.test", "null", ""]:
            self.assertEqual(self.request("email=a", headers={"Origin": origin})[0], 403)
        self.assertEqual(self.request("{}", headers={"Content-Type": "application/json"})[0], 415)
        self.assertEqual(self.request("x=y", path="/other")[0], 404)
        self.assertEqual(self.request(path="/other", method="GET")[0], 404)
        self.assertEqual(self.request(path="/health", method="GET", headers={"Accept": "text/html"})[0], 200)

    def test_malformed_or_large_body(self):
        for body in [b"email=\xff", b"email=x&email=y", b"&".join([b"x=y"] * 9)]:
            self.assertEqual(self.request(body)[0], 400)
        self.assertEqual(self.request("x" * 4097)[0], 413)
        self.assertEqual(self.request("")[0], 413)

    def test_storage_failure_is_generic(self):
        with patch.object(self.store, "add", side_effect=OSError("private synthetic detail")):
            status, _headers, body = self.request("email=a%40example.test&consent=yes&lang=en")
        self.assertEqual(status, 503)
        self.assertNotIn(b"private", body)

    def test_daily_cleanup_and_recoverable_storage_failure(self):
        future = datetime.now(UTC) + timedelta(days=2)
        self.server.next_cleanup = future
        with patch.object(self.store, "prune") as prune:
            self.server.service_actions()
            prune.assert_not_called()
        self.server.next_cleanup = datetime.now(UTC) - timedelta(seconds=1)
        with patch.object(self.store, "prune", side_effect=OSError("synthetic")), contextlib.redirect_stdout(io.StringIO()) as output:
            self.server.service_actions()
        self.assertEqual(output.getvalue().strip(), "cleanup_failed")
        self.assertGreater(self.server.next_cleanup, datetime.now(UTC))

    def test_broken_or_incomplete_stream(self):
        for length, stream in [("bad", io.BytesIO()), ("10", io.BytesIO(b"x")),
                                ("10", Mock(read=Mock(side_effect=TimeoutError())))]:
            handler = object.__new__(app.LeadHandler)
            handler.path = "/api/interest"
            handler.headers = {"Origin": "https://inboxstride.de", "Content-Type": "application/x-www-form-urlencoded",
                               "Content-Length": length}
            handler.server = SimpleNamespace(origins={"https://inboxstride.de"})
            handler.rfile = stream
            handler.respond = Mock()
            handler.do_POST()
            handler.respond.assert_called_once_with(400, "invalid")
