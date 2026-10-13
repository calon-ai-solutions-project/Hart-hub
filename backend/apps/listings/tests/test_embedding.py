from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import TestCase, override_settings

from apps.ai.client import AiUnavailable
from apps.listings.models import Listing, ListingEmbedding
from apps.listings.services import embedding
from apps.matching.models import Requirement
from apps.matching.services import search
from apps.sourcing.services.ingest import upsert_listing
from apps.sourcing.tests import fixtures

NOW = datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)
ON = override_settings(OPENROUTER_API_KEY="k", OPENROUTER_EMBEDDING_MODEL="some/embedder")

# A tiny stand-in for the embedding model: one axis per idea.
AXES = ("amg", "sport", "estate")


def fake_embed(feature, texts):
    return [[1.0 if axis in text.lower() else 0.05 for axis in AXES] for text in texts]


def car(external_id, trim, **fields):
    defaults = dict(platform="motorway", url=f"https://pro.motorway.co.uk/vehicles/{external_id}", make="Mercedes-Benz",
                    model="A-Class", details_status="complete", status="live", gearbox="Automatic", colour="Black",
                    year=2020, mileage=30000, suggested_price_pence=1500000, ends_at=NOW + timedelta(hours=30))
    return Listing.objects.create(external_id=str(external_id), trim=trim, **{**defaults, **fields})


@ON
@mock.patch.object(embedding, "embed", side_effect=fake_embed)
class EmbeddingTests(TestCase):
    def test_summary_describes_the_car(self, embed):
        text = embedding.summary_text(car(1, "A200 AMG Line Premium", body="Hatchback", fuel="Petrol", spec="Heated seats"))
        self.assertEqual(text, "2020 Mercedes-Benz A-Class A200 AMG Line Premium. Hatchback, Petrol, automatic, black. "
                               "Spec: Heated seats")

    def test_pending_cars_are_embedded_once(self, embed):
        car(1, "A200 AMG Line"), car(2, "A180 Sport"), car(3, "partial", details_status="partial")
        self.assertEqual(embedding.embed_pending(), (2, 0))
        self.assertEqual(ListingEmbedding.objects.count(), 2)
        self.assertEqual(embed.call_count, 1)  # one batched call, not one per car
        self.assertEqual(embedding.embed_pending(), (0, 0))  # nothing left: no second call, no second charge
        self.assertEqual(embed.call_count, 1)

    def test_a_changed_description_is_embedded_again_and_an_unchanged_one_is_not(self, embed):
        listing, _ = upsert_listing("motorway", fixtures.MOTORWAY, now=NOW)
        embedding.embed_pending()
        upsert_listing("motorway", {**fixtures.MOTORWAY, "highest_bid": 12500}, now=NOW)  # only the price moved
        self.assertFalse(ListingEmbedding.objects.get(listing=listing).stale)
        upsert_listing("motorway", {**fixtures.MOTORWAY, "colour": "Blue"}, now=NOW)
        self.assertTrue(ListingEmbedding.objects.get(listing=listing).stale)
        self.assertEqual(embedding.embed_pending(), (1, 0))
        self.assertFalse(ListingEmbedding.objects.get(listing=listing).stale)

    def test_service_failure_leaves_cars_waiting(self, embed):
        car(1, "A200 AMG Line")
        embed.side_effect = AiUnavailable("down")
        self.assertEqual(embedding.embed_pending(), (0, 1))
        self.assertIsNone(embedding.embed_query("amg line"))

    def test_similarity_ranks_loose_wording_inside_the_filtered_set(self, embed):
        sport, amg, estate = car(1, "A180 Sport"), car(2, "A200 AMG Line Premium"), car(3, "A180 SE", body="Estate")
        embedding.embed_pending()
        scores = embedding.similarities([sport.id, amg.id, estate.id], embedding.embed_query("AMG Line"))
        self.assertGreater(scores[amg.id], scores[sport.id])
        self.assertGreater(scores[amg.id], scores[estate.id])

        candidates, _ = search.find(Requirement(make="Mercedes", model="A Class", notes="AMG Line"), NOW)
        self.assertEqual(candidates[0].listing, amg)  # 'AMG Line' finds 'AMG Line Premium'
        self.assertIsNotNone(candidates[0].similarity)

    def test_vectors_never_override_a_hard_filter(self, embed):
        car(1, "A180 Sport")
        slk = car(2, "AMG Line", model="SLK")  # the closest wording, but the wrong model
        manual = car(3, "A200 AMG Line", gearbox="Manual")
        ended = car(4, "A200 AMG Line", status="ended")
        embedding.embed_pending()
        candidates, _ = search.find(Requirement(make="Mercedes", model="A Class", gearbox="auto", notes="AMG Line"), NOW)
        found = [c.listing for c in candidates]
        self.assertNotIn(manual, found)
        self.assertNotIn(ended, found)
        self.assertEqual(candidates[0].listing.trim, "A180 Sport")  # the right model comes first...
        self.assertEqual((candidates[1].listing, candidates[1].flags), (slk, ["different_model"]))  # ...the SLK is flagged

    def test_cars_without_a_vector_still_match_by_rules(self, embed):
        old = car(1, "A180 Sport", year=2016)
        new = car(2, "A180 Sport", year=2023)
        candidates, _ = search.find(Requirement(make="Mercedes", model="A Class"), NOW)  # nothing embedded yet
        self.assertEqual([c.listing for c in candidates], [new, old])
        self.assertIsNone(candidates[0].similarity)


class EmbeddingOffTests(TestCase):
    def test_everything_works_with_vector_search_switched_off(self):
        car(1, "A180 Sport")
        self.assertEqual(embedding.embed_pending(), (0, 0))
        self.assertIsNone(embedding.embed_query("amg line"))
        candidates, _ = search.find(Requirement(make="Mercedes", model="A Class"), NOW)
        self.assertEqual(len(candidates), 1)
