import pytest


@pytest.fixture
def settings_en(settings):
    settings.LANGUAGE_CODE = "en"
    return settings
