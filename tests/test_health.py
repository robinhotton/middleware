"""Tests pour les endpoints de base de l'application."""

from fastapi.testclient import TestClient


async def test_health(client: TestClient):
    """Verifie que GET /health retourne status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_home_redirect(client: TestClient):
    """Verifie que GET / redirige vers /docs."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"] == "/docs"


async def test_security_headers_present(client: TestClient):
    """Verifie que les en-tetes de securite sont presents sur chaque reponse."""
    resp = client.get("/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Content-Security-Policy") is not None
    assert resp.headers.get("Referrer-Policy") is not None
