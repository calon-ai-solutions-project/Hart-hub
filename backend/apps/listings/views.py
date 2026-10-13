import re

from django.core.files.storage import FileSystemStorage, default_storage
from django.http import FileResponse, Http404, HttpResponseForbidden, HttpResponseRedirect
from django.views.decorators.http import require_GET

# listings/<platform>/<external id>/01.jpg and .../thumbs/01.webp: car photos only, never quote documents
PHOTO_NAME = re.compile(r"^[a-z0-9_-]+/[A-Za-z0-9_.-]+/(thumbs/)?\d{2,3}\.(jpg|webp)$")
TYPES = {"jpg": "image/jpeg", "webp": "image/webp"}


@require_GET
def listing_photo(request, name):
    """A car photo at an address that never changes, for signed-in staff.

    Cards saved in a chat keep this address. With Cloudinary or a bucket it forwards to where the
    file is kept; without one the file is read from local storage.
    """
    if not request.user.is_authenticated:
        return HttpResponseForbidden()
    if not PHOTO_NAME.match(name):
        raise Http404
    key = f"listings/{name}"
    if not isinstance(default_storage, FileSystemStorage):
        response = HttpResponseRedirect(default_storage.url(key))
        response["Cache-Control"] = "private, max-age=1800"  # well inside a bucket's signed link hour
        return response
    if not default_storage.exists(key):
        raise Http404
    response = FileResponse(default_storage.open(key), content_type=TYPES[name.rsplit(".", 1)[1]])
    response["Cache-Control"] = "private, max-age=86400"
    return response
