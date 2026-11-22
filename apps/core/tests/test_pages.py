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
