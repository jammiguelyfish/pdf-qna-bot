import json

from django.contrib.auth import get_user_model
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
