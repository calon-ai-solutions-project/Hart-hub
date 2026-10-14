"""Role rules, checked on the server: owner sees and does everything, sales works on unassigned and own
enquiries, admin only reads."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.enquiries.models import Customer, Enquiry
from apps.enquiries.services import engine

User = get_user_model()


def client_for(user):
    api = APIClient()
    api.force_authenticate(user)
    return api


class RoleTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user("owner@example.com", "a-long-test-password", role="owner")
        self.sales = User.objects.create_user("sales@example.com", "a-long-test-password", role="sales")
        self.colleague = User.objects.create_user("sales2@example.com", "a-long-test-password", role="sales")
        self.admin = User.objects.create_user("admin@example.com", "a-long-test-password", role="admin")
        customer = Customer.objects.create(phone="+447700900123")
        self.unassigned = Enquiry.objects.create(customer=customer, intent="other_business", step="needs_person")
        self.theirs = Enquiry.objects.create(customer=customer, intent="car_enquiry", step="needs_person",
                                             assigned_to=self.colleague)

    def test_sections_travel_with_the_session(self):
        for user, sections in ((self.owner, ["home", "chat", "whatsapp"]), (self.sales, ["home", "chat", "whatsapp"]),
                               (self.admin, ["home", "whatsapp"])):
            api = APIClient()
            api.force_login(user)
            self.assertEqual(api.get("/api/auth/me").json()["user"]["sections"], sections)

    def test_admin_cannot_use_the_stock_chat_or_request_quotes(self):
        api = client_for(self.admin)
        self.assertEqual(api.get("/api/chat/conversations").status_code, 403)
        self.assertEqual(api.post("/api/quotes", {"listing_ids": []}, format="json").status_code, 403)
        self.assertEqual(client_for(self.sales).get("/api/chat/conversations").status_code, 200)

    def test_admin_reads_enquiries_but_cannot_act(self):
        api = client_for(self.admin)
        self.assertEqual(len(api.get("/api/sim/enquiries?tab=person").json()["enquiries"]), 2)
        detail = api.get(f"/api/sim/enquiries/{self.unassigned.id}").json()
        self.assertFalse(detail["can_act"])
        self.assertEqual(api.post(f"/api/sim/enquiries/{self.unassigned.id}/approve").status_code, 403)
        self.assertEqual(api.post("/api/sim/inbound", {"phone": "+447700900456", "text": "hi"},
                                  format="json").status_code, 403)
        self.assertEqual(api.delete("/api/sim/phones/+447700900123").status_code, 403)

    def test_sales_sees_unassigned_and_own_enquiries_only(self):
        api = client_for(self.sales)
        ids = [e["id"] for e in api.get("/api/sim/enquiries?tab=person").json()["enquiries"]]
        self.assertEqual(ids, [str(self.unassigned.id)])
        self.assertEqual(api.get(f"/api/sim/enquiries/{self.theirs.id}").status_code, 404)
        self.assertEqual(api.post(f"/api/sim/enquiries/{self.theirs.id}/approve").status_code, 404)
        # an unassigned one may be acted on (here it has nothing to approve, so the answer is "not ready", not "refused")
        self.assertEqual(api.post(f"/api/sim/enquiries/{self.unassigned.id}/approve").status_code, 409)
        Enquiry.objects.filter(pk=self.unassigned.pk).update(assigned_to=self.sales)
        self.assertEqual(client_for(self.colleague).get(f"/api/sim/enquiries/{self.unassigned.id}").status_code, 404)

    def test_there_is_no_replying_from_the_website(self):
        api = client_for(self.owner)
        self.assertEqual(api.post(f"/api/sim/enquiries/{self.unassigned.id}/reply", {"text": "hi"},
                                  format="json").status_code, 404)

    def test_owner_sees_and_acts_on_everything(self):
        api = client_for(self.owner)
        self.assertEqual(len(api.get("/api/sim/enquiries?tab=person").json()["enquiries"]), 2)
        self.assertTrue(api.get(f"/api/sim/enquiries/{self.theirs.id}").json()["can_act"])

    def test_home_dashboard_by_role(self):
        with mock.patch.object(engine, "start_preparing"):
            sales = client_for(self.sales).get("/api/home").json()
            owner = client_for(self.owner).get("/api/home").json()
            admin = client_for(self.admin).get("/api/home").json()
        self.assertIn("my_day", sales)
        self.assertNotIn("team", sales)
        self.assertEqual(sales["enquiries"]["needs_person"], 1)  # not the colleague's
        self.assertEqual({p["name"] for p in owner["team"]}, {"owner@example.com", "sales@example.com",
                                                              "sales2@example.com"})
        self.assertEqual(owner["enquiries"]["needs_person"], 2)
        self.assertIn("won_deals", admin)
        self.assertNotIn("team", admin)
        self.assertIn(APIClient().get("/api/home").status_code, (401, 403))
