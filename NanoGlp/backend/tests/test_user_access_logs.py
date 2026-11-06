import atexit
import os, sys, tempfile, unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from sqlalchemy import create_engine, inspect, text
from starlette.requests import Request

TMP = tempfile.TemporaryDirectory(prefix="nanoglp_access_")
os.environ["DATABASE_URL"] = f"sqlite:///{TMP.name}/test.db"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, SessionLocal, engine

atexit.register(engine.dispose)
from app.seed import reset_schema, seed_personnel, DEFAULT_PASSWORD
from app.models.user import User
from app.models.user_access_log import UserAccessLog
from app.models.audit_log import AuditLog
from app.models.role_permission import RolePermission
from app.api.v1.endpoints.auth import reset_login_rate_limiter
from app.utils.security import create_access_token
from app.utils.client_ip import client_ip
from app.config import settings


class UserAccessTests(unittest.TestCase):
    def setUp(self):
        reset_schema()
        reset_login_rate_limiter()
        self.addCleanup(reset_login_rate_limiter)
        self.db = SessionLocal()
        self.addCleanup(self.db.close)
        self.people = {u.username: u for u in seed_personnel(self.db)}
        self.client = TestClient(app, client=("198.51.100.10", 12345))
        self.addCleanup(self.client.close)

    def headers(self, u):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(u.id)})}

    def login(self, name="ezgi", password=DEFAULT_PASSWORD, headers=None):
        return self.client.post(
            "/api/v1/auth/login",
            json={"identifier": name, "password": password},
            headers=headers or {},
        )

    def rows(self):
        with SessionLocal() as db:
            return [
                {c.name: getattr(r, c.name) for c in UserAccessLog.__table__.columns}
                for r in db.query(UserAccessLog).order_by(UserAccessLog.id)
            ]

    def test_login_failed_logout_snapshots_and_no_secrets(self):
        u = self.people["ezgi"]
        u.email = "director@example.com"
        self.db.commit()
        r = self.login("director@example.com")
        self.assertEqual(r.status_code, 200)
        token = r.json()["access_token"]
        self.assertEqual(self.login(password="WRONG-SECRET").status_code, 401)
        self.assertEqual(
            self.login("unknown@example.com", "WRONG-SECRET").status_code, 401
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/auth/logout", headers={"Authorization": "Bearer " + token}
            ).status_code,
            200,
        )
        rows = self.rows()
        self.assertEqual(
            [r["event_type"] for r in rows],
            ["LOGIN", "LOGIN_FAILED", "LOGIN_FAILED", "LOGOUT"],
        )
        unknown = rows[2]
        self.assertIsNone(unknown["user_id"])
        self.assertIsNone(unknown["username"])
        self.assertIsNone(unknown["email"])
        self.assertEqual(unknown["attempted_identifier"], "unknown@example.com")
        self.assertNotIn("WRONG-SECRET", str(rows))
        self.assertNotIn(token, str(rows))
        old = rows[0]["full_name"]
        u.full_name = "Changed"
        self.db.commit()
        self.assertEqual(self.rows()[0]["full_name"], old)
        self.assertEqual(self.db.query(AuditLog).filter_by(action="LOGIN").count(), 1)
        self.assertEqual(self.client.post("/api/v1/auth/logout").status_code, 401)
        # Logout logs intention; it deliberately does not revoke existing JWTs.
        self.assertEqual(
            self.client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer " + token}
            ).status_code,
            200,
        )

    def test_failed_records_survive_401_and_429_and_spoof_cannot_evade_limit(self):
        for i in range(5):
            self.assertEqual(
                self.login(
                    password="bad", headers={"X-Forwarded-For": f"203.0.113.{i}"}
                ).status_code,
                401,
            )
        r = self.login()
        self.assertEqual(r.status_code, 429)
        self.assertIn("Retry-After", r.headers)
        rows = self.rows()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r["event_type"] == "LOGIN_FAILED" for r in rows))
        self.assertTrue(all(r["ip_address"] == "198.51.100.10" for r in rows))
        self.assertGreaterEqual(
            self.db.query(AuditLog)
            .filter_by(action="LOGIN_RATE_LIMIT_LOCKOUT")
            .count(),
            1,
        )

    def test_inactive_identity_and_malformed_locked_request(self):
        u = self.people["ezgi"]
        u.is_active = False
        self.db.commit()
        self.assertEqual(self.login().status_code, 401)
        row = self.rows()[-1]
        self.assertEqual(row["user_id"], u.id)
        self.assertEqual(row["full_name"], u.full_name)
        for _ in range(4):
            self.assertEqual(self.login().status_code, 401)
        self.assertEqual(
            self.client.post("/api/v1/auth/login", json=["invalid"]).status_code, 429
        )
        self.assertEqual(len(self.rows()), 6)
        self.assertIsNone(self.rows()[-1]["attempted_identifier"])

    def test_strict_roles_even_when_users_menu_granted(self):
        self.db.add(
            RolePermission(
                role_code="CUSTOM_TEST",
                role_label="Custom",
                allowed_menus=["users"],
                is_read_only=False,
                is_system=False,
            )
        )
        for role in (
            "SYSADMIN",
            "ADMIN",
            "TFM",
            "QA",
            "STUDY_DIRECTOR",
            "EXECUTIVE",
            "CUSTOM_TEST",
        ):
            u = User(username="access_" + role.lower(), full_name="Any name", role=role)
            self.db.add(u)
            self.db.flush()
        self.db.commit()
        for u in self.db.query(User).filter(User.username.like("access_%")):
            expected = 200 if u.role.value in ("SYSADMIN", "ADMIN") else 403
            self.assertEqual(
                self.client.get(
                    "/api/v1/access-logs", headers=self.headers(u)
                ).status_code,
                expected,
                u.role,
            )
        self.assertEqual(self.client.get("/api/v1/access-logs").status_code, 401)

    def test_istanbul_date_filter_pagination_and_explicit_utc(self):
        u = self.people["admin"]
        for stamp in (
            "2026-11-05T20:59:59",
            "2026-11-05T21:00:00",
            "2026-11-06T20:59:59",
            "2026-11-06T21:00:00",
        ):
            self.db.add(
                UserAccessLog(
                    user_id=u.id,
                    username=u.username,
                    full_name=u.full_name,
                    event_type="LOGIN",
                    created_at=datetime.fromisoformat(stamp),
                )
            )
        self.db.commit()
        params = {
            "date_from": "2026-11-06",
            "date_to": "2026-11-06",
            "event_type": "LOGIN",
            "user_id": u.id,
            "user": "admin",
            "page_size": 1,
        }
        r = self.client.get(
            "/api/v1/access-logs", params=params, headers=self.headers(u)
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["items"][0]["created_at"], "2026-11-06T20:59:59+00:00")
        params["page"] = 2
        r = self.client.get(
            "/api/v1/access-logs", params=params, headers=self.headers(u)
        )
        self.assertEqual(
            r.json()["items"][0]["created_at"], "2026-11-05T21:00:00+00:00"
        )
        self.assertEqual(
            self.client.get(
                "/api/v1/access-logs",
                params={"date_from": "2026-11-07", "date_to": "2026-11-06"},
                headers=self.headers(u),
            ).status_code,
            422,
        )

    def test_proxy_priority_validation_ipv4_ipv6_and_chain_boundary(self):
        def req(peer, headers):
            return Request(
                {
                    "type": "http",
                    "client": (peer, 1),
                    "headers": [
                        (k.lower().encode(), v.encode()) for k, v in headers.items()
                    ],
                }
            )

        with patch.object(
            settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8,2001:db8:1::/48"
        ):
            cases = [
                ("198.51.100.1", {"CF-Connecting-IP": "1.1.1.1"}, "198.51.100.1"),
                (
                    "10.1.1.1",
                    {"CF-Connecting-IP": "2001:db8:2::7", "X-Real-IP": "1.1.1.1"},
                    "2001:db8:2::7",
                ),
                (
                    "10.1.1.1",
                    {"CF-Connecting-IP": "invalid", "X-Real-IP": "203.0.113.2"},
                    "203.0.113.2",
                ),
                (
                    "10.1.1.1",
                    {"X-Forwarded-For": "6.6.6.6, 198.51.100.2, 10.2.2.2"},
                    "198.51.100.2",
                ),
                (
                    "2001:db8:1::1",
                    {"X-Forwarded-For": "2001:db8:2::2, 2001:db8:1::2"},
                    "2001:db8:2::2",
                ),
                ("10.1.1.1", {"X-Forwarded-For": "invalid, 1.1.1.1"}, "10.1.1.1"),
                (
                    "10.1.1.1",
                    {"CF-Connecting-IP": "127.0.0.1:80", "X-Real-IP": "bad"},
                    "10.1.1.1",
                ),
            ]
            for peer, headers, expected in cases:
                self.assertEqual(client_ip(req(peer, headers)), expected)
        with patch.object(settings, "TRUSTED_PROXY_CIDRS", ""):
            self.assertEqual(
                client_ip(req("127.0.0.1", {"X-Forwarded-For": "1.1.1.1"})), "127.0.0.1"
            )
        with patch.object(settings, "TRUSTED_PROXY_CIDRS", "10.0.0.0/8"):
            c = TestClient(app, client=("10.1.1.1", 1234))
            self.assertEqual(
                c.post(
                    "/api/v1/auth/login",
                    json={"username": "ezgi", "password": DEFAULT_PASSWORD},
                    headers={"CF-Connecting-IP": "2001:db8:2::7"},
                ).status_code,
                200,
            )
            c.close()
            self.assertEqual(self.rows()[-1]["ip_address"], "2001:db8:2::7")

    def test_new_log_table_startup_repeat_and_user_deletion_preserve_snapshot(self):
        old = create_engine(f"sqlite:///{TMP.name}/legacy.db")
        with old.begin() as c:
            c.execute(
                text(
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, full_name TEXT)"
                )
            )
            c.execute(text("INSERT INTO users VALUES (1,'legacy','Original')"))
        Base.metadata.create_all(old)
        Base.metadata.create_all(old)
        self.assertIn("user_access_logs", inspect(old).get_table_names())
        with old.connect() as c:
            self.assertEqual(
                c.execute(text("SELECT * FROM users")).one(), (1, "legacy", "Original")
            )
        old.dispose()
        u = User(username="temporary_access", full_name="Snapshot", role="TECHNICIAN")
        self.db.add(u)
        self.db.commit()
        self.db.add(
            UserAccessLog(
                user_id=u.id,
                username=u.username,
                full_name=u.full_name,
                event_type="LOGIN",
            )
        )
        self.db.commit()
        r = self.client.delete(
            f"/api/v1/users/{u.id}", headers=self.headers(self.people["admin"])
        )
        self.assertEqual(r.status_code, 200, r.text)
        row = self.rows()[-1]
        self.assertIsNone(row["user_id"])
        self.assertEqual(row["full_name"], "Snapshot")


if __name__ == "__main__":
    unittest.main()
