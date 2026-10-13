from django.urls import path

from . import views

urlpatterns = [
    path("chat/conversations", views.ConversationsView.as_view(), name="chat-conversations"),
    path("chat/conversations/<uuid:conversation_id>", views.ConversationView.as_view(), name="chat-conversation"),
    path("chat/conversations/<uuid:conversation_id>/messages", views.MessagesView.as_view(), name="chat-messages"),
]
