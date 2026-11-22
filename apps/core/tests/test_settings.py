from django.conf import settings


def test_time_zone_and_user_model():
    assert settings.TIME_ZONE == "Europe/Berlin"
    assert settings.USE_TZ
    assert settings.AUTH_USER_MODEL == "members.User"
