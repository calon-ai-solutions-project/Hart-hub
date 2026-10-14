"""Two sets of endpoints.

- /api/sim/...           staff only: the WhatsApp-style simulator and the enquiry dashboard.
- /api/public/forms/...  no login: the one-time enquiry form a customer opens from the link.
"""

from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import CanSell, CanView, enquiries_for, may_work_on
from apps.core.services import emit_event, get_setting

from .models import Customer, Enquiry, EnquiryMessage
from .services import engine

TABS = {
    "bot": Enquiry.BOT_STEPS,
    "person": (Enquiry.Step.NEEDS_PERSON,),
    "chosen": (Enquiry.Step.HANDED_OVER,),
}


def message_json(message):
    return {"id": str(message.id), "direction": message.direction, "sender": message.sender, "body": message.body,
            "media_url": message.media_url, "created_at": message.created_at,
            "staff_name": (message.sent_by.first_name or message.sent_by.email) if message.sent_by else ""}


def enquiry_json(enquiry, full=False):
    data = {
        "id": str(enquiry.id), "phone": enquiry.customer.phone, "step": enquiry.step,
        "step_label": enquiry.get_step_display(), "intent": enquiry.intent, "intent_label": enquiry.get_intent_display(),
        "intent_by": enquiry.intent_by, "intent_confidence": enquiry.intent_confidence,
        "needs_person_reason": enquiry.needs_person_reason, "created_at": enquiry.created_at,
        "updated_at": enquiry.updated_at, "chosen_number": enquiry.chosen_number,
        "assigned_to": (enquiry.assigned_to.first_name or enquiry.assigned_to.email) if enquiry.assigned_to else "",
        "form_submitted_at": enquiry.form_submitted_at, "quotes_tried": enquiry.quotes_tried,
        "quoting_started_at": enquiry.quoting_started_at, "quoting_finished_at": enquiry.quoting_finished_at,
        "last_inbound_at": enquiry.last_inbound_at,
        "chosen_at": enquiry.updated_at if enquiry.step == Enquiry.Step.HANDED_OVER else None,
    }
    if full:
        data["messages"] = [message_json(m) for m in enquiry.messages.all()]
        options = list(enquiry.options.all())
        data["options"] = [{"number": o.number, "sent": o.sent, "customer": o.customer, "staff": o.staff}
                           for o in options]
        chosen = next((o for o in options if o.number == enquiry.chosen_number), None)
        data["chosen_title"] = chosen.customer["card"]["title"] if chosen else ""
        requirement = enquiry.requirement
        data["request"] = None if requirement is None else {
            name: getattr(requirement, name) for name in (*requirement.FIELDS, "notes")}
    return data


class InboundSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=30)
    text = serializers.CharField(max_length=2000)


def workable(request, enquiry_id):
    """The enquiry, if this person may act on it; otherwise a 403 or 404 response."""
    enquiry = get_object_or_404(enquiries_for(request.user, Enquiry.objects.all()), pk=enquiry_id)
    if not may_work_on(request.user, enquiry):
        return None, Response({"detail": "This enquiry belongs to someone else, or your role is read only."},
                              status=status.HTTP_403_FORBIDDEN)
    return enquiry, None


class SimInboundView(APIView):
    """A customer message, as the WhatsApp webhook will deliver it later."""

    throttle_scope = "chat"
    permission_classes = [CanSell]  # typing as the customer is a demo tool for the selling roles

    def post(self, request):
        serializer = InboundSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = engine.handle_inbound(serializer.validated_data["phone"], serializer.validated_data["text"],
                                       business_number=str(get_setting("public_whatsapp_number") or ""))
        return Response({"ignored": result["ignored"], "intent": result["intent"],
                         "enquiry": enquiry_json(result["enquiry"]) if result["enquiry"] else None,
                         "replies": [message_json(m) for m in result["replies"]]})


class SimPhoneView(APIView):
    """Everything stored for one customer number, oldest first: what their phone would show."""

    permission_classes = [CanView]

    def get(self, request, phone):
        phone = engine.e164(phone)
        messages = [message_json(m) for m in EnquiryMessage.objects.filter(enquiry__customer__phone=phone)
                    .select_related("sent_by").order_by("enquiry__created_at", "created_at")]
        current = Enquiry.objects.filter(customer__phone=phone).select_related("customer", "assigned_to") \
            .order_by("-created_at").first()
        return Response({"phone": phone, "messages": messages,
                         "enquiry": enquiry_json(current) if current else None})

    def delete(self, request, phone):
        """Start a demo number again from nothing. Simulator numbers only."""
        if not CanSell().has_permission(request, self):
            return Response({"detail": "Your role is read only."}, status=status.HTTP_403_FORBIDDEN)
        phone = engine.e164(phone)
        customer = Customer.objects.filter(phone=phone).first()
        if customer is None:
            return Response(status=status.HTTP_204_NO_CONTENT)
        if customer.enquiries.exclude(channel="simulator").exists():
            return Response({"detail": "Only simulator conversations can be cleared."}, status=400)
        customer.delete()
        emit_event("enquiry.simulator_cleared", {"phone_last4": phone[-4:]}, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EnquiryListView(APIView):
    permission_classes = [CanView]

    def get(self, request):
        enquiries = enquiries_for(request.user, Enquiry.objects.select_related("customer", "assigned_to"))
        counts = enquiries.aggregate(**{tab: Count("id", filter=Q(step__in=steps)) for tab, steps in TABS.items()})
        tab = request.query_params.get("tab", "bot")
        latest = EnquiryMessage.objects.filter(enquiry=OuterRef("pk")).order_by("-created_at")
        shown = enquiries.filter(step__in=TABS.get(tab, TABS["bot"])).annotate(
            last_body=Subquery(latest.values("body")[:1]), last_direction=Subquery(latest.values("direction")[:1]),
            last_at=Subquery(latest.values("created_at")[:1]))[:100]
        rows = []
        for e in shown:
            row = enquiry_json(e)
            row["last_message"] = {"body": " ".join((e.last_body or "").split())[:90], "direction": e.last_direction,
                                   "at": e.last_at}
            rows.append(row)
        return Response({"counts": counts, "enquiries": rows})


class EnquiryView(APIView):
    permission_classes = [CanView]

    def get(self, request, enquiry_id):
        enquiries = enquiries_for(request.user, Enquiry.objects.select_related("customer", "requirement", "assigned_to")
                                  .prefetch_related(Prefetch("messages", EnquiryMessage.objects.select_related("sent_by")),
                                                    "options"))
        enquiry = get_object_or_404(enquiries, pk=enquiry_id)
        data = enquiry_json(enquiry, full=True)
        data["can_act"] = may_work_on(request.user, enquiry)
        return Response(data)


class EnquiryApproveView(APIView):
    """'Approve & send': the options go to the customer only when a person says so (unless auto-send is on)."""

    permission_classes = [CanSell]

    def post(self, request, enquiry_id):
        enquiry, refused = workable(request, enquiry_id)
        if refused:
            return refused
        try:
            enquiry = engine.send_options(enquiry, request.user)
        except engine.CannotSend as e:
            return Response({"detail": str(e)}, status=status.HTTP_409_CONFLICT)
        return Response(enquiry_json(enquiry, full=True))


# ---------------------------------------------------------------- the public form

FIELDS = [
    {"name": "make_model", "label": "Make & model", "placeholder": "e.g. BMW 1 Series, or an SUV"},
    {"name": "colour", "label": "Preferred colour", "placeholder": "e.g. Grey or black"},
    {"name": "needed_by", "label": "Needed by", "placeholder": "e.g. End of October"},
    {"name": "gearbox", "label": "Gearbox", "options": ["Auto", "Manual", "Either"]},
    {"name": "monthly_budget", "label": "Max monthly budget", "placeholder": "e.g. £400"},
    {"name": "deposit", "label": "Deposit", "placeholder": "e.g. £3,000"},
    {"name": "part_exchange", "label": "Part-exchange? (optional)", "placeholder": "e.g. 2017 Ford Focus"},
]


class FormSerializer(serializers.Serializer):
    answers = serializers.DictField(child=serializers.CharField(allow_blank=True, max_length=200))


class PublicFormView(APIView):
    """The customer's one-time form. No login: the link itself is the key, and it works once."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "public"

    def get(self, request, token):
        enquiry = engine.form_for(token)
        if enquiry is None:
            return Response({"detail": "This link has expired. Message us again and we'll send a new one."}, status=404)
        return Response({"submitted": bool(enquiry.form_submitted_at), "fields": FIELDS})

    def post(self, request, token):
        enquiry = engine.form_for(token)
        if enquiry is None:
            return Response({"detail": "This link has expired. Message us again and we'll send a new one."}, status=404)
        serializer = FormSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        answers = serializer.validated_data["answers"]
        if not any(answers.get(f["name"], "").strip() for f in FIELDS if f["name"] != "part_exchange"):
            return Response({"detail": "Tell us at least what you're looking for or your budget."}, status=400)
        _, accepted = engine.submit_form(enquiry, answers)
        return Response({"submitted": True, "already": not accepted})


urlpatterns = [
    path("sim/inbound", SimInboundView.as_view()),
    path("sim/phones/<str:phone>", SimPhoneView.as_view()),
    path("sim/enquiries", EnquiryListView.as_view()),
    path("sim/enquiries/<uuid:enquiry_id>", EnquiryView.as_view()),
    path("sim/enquiries/<uuid:enquiry_id>/approve", EnquiryApproveView.as_view()),
    path("public/forms/<str:token>", PublicFormView.as_view()),
]
