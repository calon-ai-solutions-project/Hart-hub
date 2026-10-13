from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.services import emit_event

from .. import services
from ..models import Conversation


class MessageSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    role = serializers.CharField()
    kind = serializers.CharField()
    body = serializers.CharField()
    payload = serializers.JSONField()
    created_at = serializers.DateTimeField()


class NewMessageSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    form = serializers.DictField(required=False, child=serializers.CharField(allow_blank=True, max_length=200))
    remove = serializers.ChoiceField(required=False, choices=list(services.REMOVALS))  # the x on a filter chip

    def validate(self, data):
        typed = (data.get("text") or "").strip() or any((v or "").strip() for v in (data.get("form") or {}).values())
        if not typed and not data.get("remove"):
            raise serializers.ValidationError("Type a message or fill in the form.")
        return data


def conversation_json(conversation, messages=None):
    requirement = conversation.requirement
    data = {"id": conversation.id, "title": str(conversation), "updated_at": conversation.updated_at,
            "deposit_pence": requirement.deposit_pence if requirement else None}
    if messages is not None:
        data["messages"] = MessageSerializer(messages, many=True).data
    return data


class ChatView(APIView):
    """Staff session login (the default authentication). A salesperson only sees their own chats."""

    throttle_scope = "chat"

    def conversation(self, request, conversation_id):
        return get_object_or_404(Conversation, pk=conversation_id, user=request.user)


class ConversationsView(ChatView):
    def get(self, request):
        return Response([conversation_json(c) for c in request.user.chat_conversations.all()[:50]])

    def post(self, request):
        conversation = services.start_conversation(request.user)
        return Response(conversation_json(conversation, conversation.messages.all()), status=status.HTTP_201_CREATED)


class ConversationView(ChatView):
    def get(self, request, conversation_id):
        conversation = self.conversation(request, conversation_id)
        return Response(conversation_json(conversation, conversation.messages.all()))

    def delete(self, request, conversation_id):
        """Delete one of your own chats and its messages. Quotes already fetched are kept for the record."""
        conversation = self.conversation(request, conversation_id)
        emit_event("chat.deleted", {"conversation_id": str(conversation.id), "title": str(conversation)},
                   actor=request.user)
        conversation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MessagesView(ChatView):
    def post(self, request, conversation_id):
        conversation = self.conversation(request, conversation_id)
        serializer = NewMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        messages = services.reply(conversation, **serializer.validated_data)
        return Response({"messages": MessageSerializer(messages, many=True).data,
                         "conversation": conversation_json(conversation)}, status=status.HTTP_201_CREATED)
