from django.urls import path

from . import views

urlpatterns = [
    path("chat/", views.Ask.as_view()),
    path("conversations/", views.ConversationList.as_view()),
    path("conversations/<int:pk>/", views.ConversationDetail.as_view()),
]
