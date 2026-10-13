from unittest import mock

from django.core.files.base import ContentFile
from django.test import SimpleTestCase

from apps.core.storage import CloudinaryStorage, target

PHOTO = "listings/motorway/30000004/thumbs/01.webp"
PDF = "quotes/2026/10/0b5c.pdf"


class CloudinaryStorageTests(SimpleTestCase):
    def setUp(self):
        import cloudinary

        cloudinary.config(cloud_name="demo-cloud", api_key="1", api_secret="s")
        self.storage = CloudinaryStorage()

    def test_photos_are_public_images_and_documents_are_private(self):
        self.assertEqual(target(PHOTO), ("listings/motorway/30000004/thumbs/01", "image", "upload", "webp"))
        self.assertEqual(target(PDF), (PDF, "raw", "authenticated", None))

    def test_addresses(self):
        self.assertEqual(self.storage.url(PHOTO),
                         "https://res.cloudinary.com/demo-cloud/image/upload/v1/listings/motorway/30000004/thumbs/01.webp")
        document = self.storage.url(PDF)  # no public address: a signed link to the download API
        self.assertTrue(document.startswith("https://api.cloudinary.com/v1_1/demo-cloud/raw/download?"))
        self.assertIn("signature=", document)
        self.assertIn("type=authenticated", document)

    def test_saving_replaces_the_file_at_its_fixed_name(self):
        with mock.patch("cloudinary.uploader.upload") as upload:
            name = self.storage.save(PHOTO, ContentFile(b"webp"))
        self.assertEqual(name, PHOTO)
        sent = upload.call_args
        self.assertEqual(sent.args[0], b"webp")
        self.assertEqual((sent.kwargs["public_id"], sent.kwargs["resource_type"], sent.kwargs["overwrite"]),
                         ("listings/motorway/30000004/thumbs/01", "image", True))

    def test_delete(self):
        with mock.patch("cloudinary.uploader.destroy") as destroy:
            self.storage.delete(PDF)
        destroy.assert_called_once_with(PDF, resource_type="raw", type="authenticated", invalidate=True)
