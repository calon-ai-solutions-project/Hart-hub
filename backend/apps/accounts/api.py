"""Sign-in for the portal (the React app in web/). Session cookies, CSRF-protected."""

from django.contrib.auth import authenticate, login, logout
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai.client import ai_enabled
from apps.core.services import get_setting


def session_json(request):
    """Who is signed in, and the few settings the portal needs to draw itself."""
    user = request.user if request.user.is_authenticated else None
    return {
        "user": user and {"email": user.email, "name": user.get_full_name(), "role": user.role},
        "app": {"ai_enabled": ai_enabled(), "quote_term_months": int(get_setting("codeweavers_term_months"))} if user else None,
    }


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(max_length=200, trim_whitespace=False)


@method_decorator(ensure_csrf_cookie, name="dispatch")
class MeView(APIView):
    """Always answers 200, and always sets the CSRF cookie the portal needs before it can sign in."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(session_json(request))


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    authentication_classes = []  # signing in is the one call made without a session
    permission_classes = [AllowAny]
    throttle_scope = "login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(request, username=serializer.validated_data["email"].lower(),
                            password=serializer.validated_data["password"])
        if user is None or not user.is_active:
            # the same answer whether the email or the password is wrong
            return Response({"detail": "Email or password is incorrect."}, status=status.HTTP_400_BAD_REQUEST)
        login(request._request, user)
        request._request.user = user
        return Response(session_json(request._request))


class LogoutView(APIView):
    def post(self, request):
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


urlpatterns = [
    path("auth/me", MeView.as_view(), name="auth-me"),
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
]
