"""Vector search over listings (pgvector).

Vectors only ever RANK cars that have already passed the hard filters, so a CLA never matches an SLK.
"""

import hashlib
import math

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.ai.client import AiUnavailable, embed, embeddings_enabled

from ..models import Listing, ListingEmbedding


def summary_text(listing):
    """What a car 'is', in words: this is the text that gets embedded."""
    gearbox = {"auto": "automatic", "manual": "manual"}.get(listing.gearbox_kind, listing.gearbox)
    head = " ".join(str(part) for part in (listing.year, listing.make, listing.model, listing.trim) if part)
    facts = ", ".join(part for part in (listing.body, listing.fuel, gearbox, listing.colour.lower()) if part)
    lines = [head or listing.title, listing.title if listing.title and listing.title not in head else "", facts]
    if listing.spec:
        lines.append(f"Spec: {listing.spec[:400]}")
    return ". ".join(line for line in lines if line)


def text_hash(text):
    return hashlib.sha256(f"{settings.OPENROUTER_EMBEDDING_MODEL}\n{text}".encode()).hexdigest()


def mark_if_changed(listing):
    """Called when a car is saved: if its description changed, its vector is queued to be redone."""
    ListingEmbedding.objects.filter(listing=listing).exclude(text_hash=text_hash(summary_text(listing))).update(stale=True)


def pending():
    """Fully captured cars with no vector yet, or whose description has changed."""
    return Listing.objects.filter(details_status=Listing.DetailsStatus.COMPLETE).filter(
        Q(embedding_row__isnull=True) | Q(embedding_row__stale=True))


def embed_pending(limit=500):
    """Embed up to `limit` waiting cars. Returns (embedded, still_waiting)."""
    if not embeddings_enabled():
        return 0, 0
    done = 0
    listings = list(pending().order_by("-last_seen_at")[:limit])
    for start in range(0, len(listings), settings.EMBEDDING_BATCH):
        batch = listings[start:start + settings.EMBEDDING_BATCH]
        texts = [summary_text(listing) for listing in batch]
        try:
            vectors = embed("listing-embedding", texts)
        except AiUnavailable:
            break  # try again on the next run; matching falls back to rules meanwhile
        now = timezone.now()
        for listing, text, vector in zip(batch, texts, vectors):
            ListingEmbedding.objects.update_or_create(listing=listing, defaults={
                "embedding": vector, "text_hash": text_hash(text), "stale": False, "embedded_at": now})
        done += len(batch)
    return done, pending().count()


def embed_query(text):
    """The vector for a customer's request, or None when vector search is off or unavailable."""
    if not embeddings_enabled() or not text.strip():
        return None
    try:
        return embed("requirement-embedding", [text[:1000]])[0]
    except AiUnavailable:
        return None


def similarities(listing_ids, query_vector):
    """{listing id: similarity 0..1} for the given cars; cars without a vector are simply absent."""
    if query_vector is None or not listing_ids:
        return {}
    rows = ListingEmbedding.objects.filter(listing_id__in=listing_ids)
    if connection.vendor == "postgresql":
        from pgvector.django import CosineDistance

        distances = rows.annotate(distance=CosineDistance("embedding", query_vector)).values_list("listing_id", "distance")
        return {listing_id: 1 - distance for listing_id, distance in distances}
    return {row.listing_id: cosine(row.embedding, query_vector) for row in rows}  # tests run on SQLite


def cosine(a, b):
    a, b = [float(x) for x in a], [float(x) for x in b]
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0
