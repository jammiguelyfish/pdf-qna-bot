import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

User = get_user_model()


def post(client, path, data):
    return client.post(path, json.dumps(data), content_type="application/json")


class AuthTests(TestCase):
    def test_register_logs_the_new_user_in(self):
        c = Client()
        r = post(c, "/api/auth/register/", {"username": "carol", "password": "a-long-passphrase-9"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(c.get("/api/auth/me/").json()["username"], "carol")

    def test_register_rejects_weak_passwords_and_taken_names(self):
        c = Client()
        self.assertEqual(post(c, "/api/auth/register/", {"username": "dave", "password": "12345678"}).status_code, 400)
        self.assertEqual(post(c, "/api/auth/register/", {"username": "ab", "password": "a-long-passphrase-9"}).status_code, 400)
        post(c, "/api/auth/register/", {"username": "Erin", "password": "a-long-passphrase-9"})
        r = post(Client(), "/api/auth/register/", {"username": "erin", "password": "a-long-passphrase-9"})
        self.assertEqual(r.status_code, 409, "usernames are unique regardless of case")

    @override_settings(ALLOW_REGISTRATION=False)
    def test_registration_can_be_switched_off(self):
        r = post(Client(), "/api/auth/register/", {"username": "frank", "password": "a-long-passphrase-9"})
        self.assertEqual(r.status_code, 403)

    def test_login_logout_and_me(self):
        User.objects.create_user("gina", password="a-long-passphrase-9")
        c = Client()
        self.assertEqual(c.get("/api/auth/me/").status_code, 401)
        self.assertEqual(post(c, "/api/auth/login/", {"username": "gina", "password": "wrong"}).status_code, 401)
        self.assertEqual(post(c, "/api/auth/login/", {"username": "gina", "password": "a-long-passphrase-9"}).status_code, 200)
        self.assertEqual(c.get("/api/auth/me/").status_code, 200)
        self.assertEqual(post(c, "/api/auth/logout/", {}).status_code, 200)
        self.assertEqual(c.get("/api/auth/me/").status_code, 401)

    def test_writes_require_the_csrf_token(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(post(c, "/api/auth/register/", {"username": "hank", "password": "a-long-passphrase-9"}).status_code, 403)
        c.get("/api/auth/csrf/")  # sets the cookie
        token = c.cookies["csrftoken"].value
        r = c.post(
            "/api/auth/register/",
            json.dumps({"username": "hank", "password": "a-long-passphrase-9"}),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(r.status_code, 201)

    def test_garbage_bodies_are_rejected_not_crashes(self):
        c = Client()
        r = c.post("/api/auth/login/", "not json", content_type="application/json")
        self.assertEqual(r.status_code, 401)
        r = c.post("/api/auth/register/", "[1, 2]", content_type="application/json")
        self.assertEqual(r.status_code, 400)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginLockoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        User.objects.create_user("hana", password="a-long-passphrase-9")
        User.objects.create_user("ivan", password="a-long-passphrase-9")

    def fail(self, client, name, times):
        return [post(client, "/api/auth/login/", {"username": name, "password": "nope"}).status_code for _ in range(times)]

    def test_repeated_failures_lock_that_username_out_even_with_the_right_password(self):
        c = Client()
        self.assertEqual(self.fail(c, "hana", 5), [401] * 5)
        r = post(c, "/api/auth/login/", {"username": "hana", "password": "a-long-passphrase-9"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r["Retry-After"], "900")

    def test_lockout_is_per_username_and_case_insensitive(self):
        c = Client()
        self.fail(c, "Hana", 5)
        self.assertEqual(post(c, "/api/auth/login/", {"username": "HANA", "password": "a-long-passphrase-9"}).status_code, 429)
        self.assertEqual(post(c, "/api/auth/login/", {"username": "ivan", "password": "a-long-passphrase-9"}).status_code, 200)

    def test_a_successful_sign_in_resets_the_count(self):
        c = Client()
        self.fail(c, "hana", 4)
        self.assertEqual(post(c, "/api/auth/login/", {"username": "hana", "password": "a-long-passphrase-9"}).status_code, 200)
        self.assertEqual(self.fail(c, "hana", 4), [401] * 4, "the earlier failures no longer count")

    def test_trying_many_usernames_from_one_address_is_also_limited(self):
        with override_settings(LOGIN_MAX_FAILURES_PER_IP=6):
            c = Client()
            codes = [post(c, "/api/auth/login/", {"username": f"user{i}", "password": "x"}).status_code for i in range(7)]
            self.assertEqual(codes, [401] * 6 + [429])

    def test_lockout_ends_when_the_window_passes(self):
        c = Client()
        with override_settings(LOGIN_LOCKOUT_SECONDS=2):
            self.fail(c, "hana", 5)
            self.assertEqual(post(c, "/api/auth/login/", {"username": "hana", "password": "a-long-passphrase-9"}).status_code, 429)
            import time
            time.sleep(2.2)
            self.assertEqual(post(c, "/api/auth/login/", {"username": "hana", "password": "a-long-passphrase-9"}).status_code, 200)
