from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("tickets/", views.ticket_list, name="list"),
    path("tickets/new/", views.new_ticket, name="new"),
    path("tickets/flag/", views.flag_view, name="flag"),
    path("tickets/new/<str:key>/", views.new_ticket_form, name="new_form"),
    path("tickets/comments/<int:pk>/edit/", views.comment_edit, name="comment_edit"),
    path("tickets/comments/<int:pk>/helpful/", views.helpful, name="helpful"),
    path("tickets/<str:number>/", views.ticket_detail, name="detail"),
    path("tickets/mediation/new/", views.mediation_new, name="mediation_new"),
    path("tickets/<str:number>/mediation/", views.mediation_page, name="mediation"),
    path("tickets/<str:number>/mediation/<str:action>/", views.mediation_action, name="mediation_action"),
    path("tickets/<str:number>/contest/", views.contest_view, name="contest"),
    path("tickets/<str:number>/comment/", views.comment, name="comment"),
    path("seat/<int:pk>/", views.seat_page, name="seat"),
    path("seat/<int:pk>/vote/", views.seat_vote, name="seat_vote"),
    path("seat/<int:pk>/conflict/", views.seat_conflict, name="seat_conflict"),
    path("notifications/", views.notifications, name="notifications"),
]
