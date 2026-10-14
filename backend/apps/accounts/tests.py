from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User


class AuthApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales@example.com", "a-long-password", first_name="Sam", role="sales")
        self.api = APIClient(enforce_csrf_checks=True)

    def csrf(self):
        self.api.get("/api/auth/me")
        return self.api.cookies["csrftoken"].value

    def test_me_is_empty_and_hands_out_the_csrf_cookie_when_signed_out(self):
        response = self.api.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user": None, "app": None})
        self.assertIn("csrftoken", response.cookies)

    def test_sign_in_then_use_the_chat_then_sign_out(self):
        token = self.csrf()
        response = self.api.post("/api/auth/login", {"email": "Sales@Example.com", "password": "a-long-password"},
                                 format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["user"], {"email": "sales@example.com", "name": "Sam", "role": "sales",
                                                   "role_label": "Sales", "sections": ["home", "chat", "whatsapp"]})
        self.assertEqual(response.json()["app"], {"ai_enabled": False, "quote_term_months": 48})

        token = self.csrf()  # signing in rotates it
        self.assertEqual(self.api.get("/api/auth/me").json()["user"]["email"], "sales@example.com")
        self.assertEqual(self.api.post("/api/chat/conversations", format="json", HTTP_X_CSRFTOKEN=token).status_code, 201)

        self.assertEqual(self.api.post("/api/auth/logout", format="json", HTTP_X_CSRFTOKEN=token).status_code, 204)
        self.assertIsNone(self.api.get("/api/auth/me").json()["user"])
        self.assertIn(self.api.get("/api/chat/conversations").status_code, (401, 403))

    def test_wrong_details_are_refused_without_saying_which_part_was_wrong(self):
        token = self.csrf()
        for email, password in (("sales@example.com", "wrong"), ("nobody@example.com", "a-long-password")):
            response = self.api.post("/api/auth/login", {"email": email, "password": password}, format="json",
                                     HTTP_X_CSRFTOKEN=token)
            self.assertEqual((response.status_code, response.json()["detail"]), (400, "Email or password is incorrect."))
        self.user.is_active = False
        self.user.save()
        response = self.api.post("/api/auth/login", {"email": "sales@example.com", "password": "a-long-password"},
                                 format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 400)

    def test_sign_in_needs_the_csrf_token(self):
        self.csrf()
        response = self.api.post("/api/auth/login", {"email": "sales@example.com", "password": "a-long-password"},
                                 format="json")
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.api.get("/api/auth/me").json()["user"])
