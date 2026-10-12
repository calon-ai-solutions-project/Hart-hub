from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from ..models import RunnerToken


class RunnerTokenAuthentication(BaseAuthentication):
    """`Authorization: Bearer hhr_...` - the sync runner's machine credential."""

    def authenticate(self, request):
        header = get_authorization_header(request).split()
        if not header or header[0].lower() != b"bearer":
            return None
        if len(header) != 2:
            raise AuthenticationFailed("Invalid authorization header.")
        key = header[1].decode("utf-8", errors="ignore")
        token = RunnerToken.objects.filter(key_hash=RunnerToken.hash_key(key), revoked_at__isnull=True).first()
        if token is None:
            raise AuthenticationFailed("Invalid runner token.")
        now = timezone.now()
        if token.last_used_at is None or now - token.last_used_at > timedelta(minutes=1):
            RunnerToken.objects.filter(pk=token.pk).update(last_used_at=now)  # not on every photo
        return AnonymousUser(), token

    def authenticate_header(self, request):
        return "Bearer"


class IsRunner(BasePermission):
    def has_permission(self, request, view):
        return isinstance(request.auth, RunnerToken)
