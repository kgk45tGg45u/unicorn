import pytest


def test_home_page_ok(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "manifest.webmanifest" in response.content.decode()


def test_offline_page_ok(client):
    assert client.get("/offline/").status_code == 200


def test_service_worker_served_from_root(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/javascript")


@pytest.mark.django_db
def test_healthz_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_url_shows_friendly_404(client):
    response = client.get("/no-such-page/")
    assert response.status_code == 404
    assert "cannot find that page" in response.content.decode()
