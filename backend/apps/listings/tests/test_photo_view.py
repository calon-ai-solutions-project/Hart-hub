from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase

NAME = "listings/motorway/30000004/thumbs/01.webp"


class ListingPhotoViewTests(TestCase):
    def setUp(self):
        default_storage.save(NAME, ContentFile(b"webp-bytes"))
        self.addCleanup(default_storage.delete, NAME)
        self.user = get_user_model().objects.create_user(email="staff@example.com", password="a-long-test-password")

    def test_signed_in_staff_get_the_photo_at_its_fixed_address(self):
        self.client.force_login(self.user)
        response = self.client.get(f"/media/{NAME}")
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/webp"))
        self.assertEqual(b"".join(response.streaming_content), b"webp-bytes")

    def test_nobody_else_gets_it(self):
        self.assertEqual(self.client.get(f"/media/{NAME}").status_code, 403)

    def test_only_car_photos_are_served(self):
        default_storage.save("quotes/2026/10/doc.pdf", ContentFile(b"%PDF"))
        self.addCleanup(default_storage.delete, "quotes/2026/10/doc.pdf")
        self.client.force_login(self.user)
        for path in ("/media/quotes/2026/10/doc.pdf", "/media/listings/../quotes/2026/10/doc.pdf",
                     "/media/listings/motorway/30000004/notes.txt", "/media/listings/motorway/30000004/09.webp"):
            self.assertEqual(self.client.get(path).status_code, 404, path)
