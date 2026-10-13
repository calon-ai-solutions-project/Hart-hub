from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_sameorigin
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.chat.models import Conversation, Message
from apps.matching.services.parse import to_pence

from . import services
from .models import Quote


class QuoteRequestSerializer(serializers.Serializer):
    listing_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False, max_length=services.MAX_CARS)
    deposit = serializers.CharField(required=False, allow_blank=True, max_length=20)
    conversation = serializers.UUIDField(required=False)


class QuotesView(APIView):
    """Staff session login. Ask Codeweavers for quotes on chosen cars, and read how they are getting on."""

    throttle_scope = "chat"

    def post(self, request):
        serializer = QuoteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        conversation = None
        if data.get("conversation"):
            conversation = get_object_or_404(Conversation, pk=data["conversation"], user=request.user)
        typed = (data.get("deposit") or "").strip()
        if typed:  # staff changed it on the quote bar ("0" means no deposit)
            deposit = to_pence(typed) or 0
        else:  # otherwise the deposit the customer gave in the enquiry form
            requirement = conversation.requirement if conversation else None
            deposit = (requirement.deposit_pence if requirement else None) or 0
        try:
            quotes = services.request_quotes(request.user, data["listing_ids"], deposit, conversation)
        except services.CannotQuote as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        answer = {"quotes": [services.quote_json(q) for q in quotes]}
        if conversation:
            cars = "1 car" if len(quotes) == 1 else f"{len(quotes)} cars"
            asked = Message.objects.create(conversation=conversation, role=Message.Role.USER,
                                           body=f"Get finance quotes for {cars}")
            reply = Message.objects.create(
                conversation=conversation, role=Message.Role.BOT, kind=Message.Kind.QUOTES,
                body=(f"Codeweavers quotes for {cars}, over {quotes[0].term_months} months with "
                      f"{services.money(deposit).removesuffix('.00')} deposit:"),
                payload={"quote_ids": [str(q.id) for q in quotes]})
            conversation.save()  # moves the chat to the top of the list
            answer["messages"] = [
                {"id": m.id, "role": m.role, "kind": m.kind, "body": m.body, "payload": m.payload,
                 "created_at": m.created_at} for m in (asked, reply)]
        return Response(answer, status=status.HTTP_201_CREATED)

    def get(self, request):
        ids = [value for value in request.query_params.get("ids", "").split(",") if value][:50]
        services.fail_stuck()
        try:
            quotes = Quote.objects.filter(id__in=ids, requested_by=request.user).select_related("listing")
            found = {str(q.id): q for q in quotes}
        except (ValueError, serializers.ValidationError):
            return Response({"detail": "Bad quote id."}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"quotes": [services.quote_json(found[i]) for i in ids if i in found]})


class QuotePdfView(APIView):
    """Codeweavers' quote document, for the member of staff who asked for the quote (or the owner)."""

    throttle_scope = "chat"

    @method_decorator(xframe_options_sameorigin)  # the chat page previews it in a frame
    def get(self, request, quote_id):
        quotes = Quote.objects.all() if request.user.role == "owner" else Quote.objects.filter(requested_by=request.user)
        quote = get_object_or_404(quotes, pk=quote_id)
        if not quote.pdf:
            raise Http404("This quote has no document.")
        response = FileResponse(quote.pdf.open("rb"), content_type="application/pdf")
        how = "attachment" if request.query_params.get("download") else "inline"
        response["Content-Disposition"] = f'{how}; filename="Quote {quote.registration}.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response


urlpatterns = [
    path("quotes", QuotesView.as_view(), name="quotes"),
    path("quotes/<uuid:quote_id>/pdf", QuotePdfView.as_view(), name="quote-pdf"),
]
