import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def settings_en(settings):
    settings.LANGUAGE_CODE = "en"
    return settings


@pytest.fixture(autouse=True)
def test_keys_and_private_media(settings, tmp_path):
    """Tests never use the real keys or the real private folder."""
    settings.UNICORN_MASTER_KEY = Fernet.generate_key().decode()
    settings.UNICORN_HMAC_KEY = "ab" * 32
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path / "private_media")
