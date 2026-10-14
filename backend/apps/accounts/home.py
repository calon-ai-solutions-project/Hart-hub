"""The home dashboard after sign-in: what each role needs to see first."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Count
from django.urls import path
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.models import Conversation
from apps.enquiries.models import Enquiry
from apps.matching.services.search import available_stock
from apps.quotes.models import Quote

from .permissions import ADMIN, OWNER, SALES, CanView, enquiries_for, role_of


def person(user):
    return (user.get_full_name() or user.email) if user else ""


def enquiry_row(enquiry):
    chosen = next((o for o in enquiry.options.all() if o.number == enquiry.chosen_number), None)
    return {"id": str(enquiry.id), "phone": enquiry.customer.phone, "step": enquiry.step,
            "step_label": enquiry.get_step_display(), "updated_at": enquiry.updated_at,
            "assigned_to": person(enquiry.assigned_to),
            "car": chosen.customer["card"]["title"] if chosen else "",
            "price_pence": chosen.customer["card"]["price_pence"] if chosen else None}


def won_deals(queryset, limit=20):
    chosen = queryset.filter(step=Enquiry.Step.HANDED_OVER, chosen_number__isnull=False)
    return [enquiry_row(e) for e in chosen.select_related("customer", "assigned_to").prefetch_related("options")
            .order_by("-updated_at")[:limit]]


class HomeView(APIView):
    permission_classes = [CanView]

    def get(self, request):
        user, role = request.user, role_of(request.user)
        now = timezone.now()
        week = now - timedelta(days=7)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        visible = enquiries_for(user, Enquiry.objects.all())
        steps = dict(visible.values_list("step").annotate(n=Count("id")).values_list("step", "n"))
        data = {"role": role, "stock_live": available_stock(now).count(),
                "enquiries": {"waiting_approval": steps.get(Enquiry.Step.AWAITING_APPROVAL, 0),
                              "quoting": steps.get(Enquiry.Step.QUOTING, 0) + steps.get(Enquiry.Step.FORM_DONE, 0),
                              "form_sent": steps.get(Enquiry.Step.FORM_SENT, 0),
                              "options_sent": steps.get(Enquiry.Step.OPTIONS_SENT, 0),
                              "needs_person": steps.get(Enquiry.Step.NEEDS_PERSON, 0),
                              "chosen": steps.get(Enquiry.Step.HANDED_OVER, 0)}}

        if role == SALES:
            mine = visible.filter(assigned_to=user)
            data["my_day"] = {
                "chosen_this_week": mine.filter(step=Enquiry.Step.HANDED_OVER, updated_at__gte=week).count(),
                "chats_this_week": Conversation.objects.filter(user=user, updated_at__gte=week).count(),
            }
            attention = visible.filter(step__in=(Enquiry.Step.AWAITING_APPROVAL, Enquiry.Step.NEEDS_PERSON,
                                                 Enquiry.Step.HANDED_OVER))
            data["to_do"] = [enquiry_row(e) for e in attention.select_related("customer", "assigned_to")
                             .prefetch_related("options").order_by("-updated_at")[:8]]

        if role == OWNER:
            quotes_today = Quote.objects.filter(created_at__gte=today)
            data["quotes_today"] = {"done": quotes_today.filter(status=Quote.Status.DONE).count(),
                                    "failed": quotes_today.filter(status=Quote.Status.FAILED).count()}
            people = []
            for member in get_user_model().objects.filter(is_active=True, role__in=(OWNER, SALES)).order_by("email"):
                assigned = Enquiry.objects.filter(assigned_to=member)
                people.append({
                    "name": person(member), "role": member.get_role_display(),
                    "open": assigned.exclude(step__in=(Enquiry.Step.HANDED_OVER, Enquiry.Step.CLOSED)).count(),
                    "chosen_this_week": assigned.filter(step=Enquiry.Step.HANDED_OVER, updated_at__gte=week).count(),
                    "chats_this_week": Conversation.objects.filter(user=member, updated_at__gte=week).count(),
                })
            data["team"] = people
            data["recent_wins"] = won_deals(Enquiry.objects.all(), limit=6)

        if role == ADMIN:
            data["won_deals"] = won_deals(Enquiry.objects.all())
            data["won_this_week"] = Enquiry.objects.filter(step=Enquiry.Step.HANDED_OVER, updated_at__gte=week).count()
        return Response(data)


urlpatterns = [path("home", HomeView.as_view())]
