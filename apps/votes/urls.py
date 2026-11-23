from django.urls import path

from . import views

app_name = "votes"

urlpatterns = [
    path("votes/", views.vote_list, name="list"),
    path("votes/check/", views.check_receipt, name="check"),
    path("votes/petitions/open/<str:number>/", views.open_petition, name="open_petition"),
    path("votes/petitions/<int:pk>/", views.petition_page, name="petition"),
    path("votes/petitions/<int:pk>/sign/", views.sign_petition, name="sign"),
    path("votes/<int:pk>/", views.referendum_page, name="referendum"),
    path("votes/<int:pk>/vote/", views.cast_vote, name="cast"),
]
