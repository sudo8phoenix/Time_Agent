from fastapi.testclient import TestClient
from app.main import app

def test_liveness():
    response = TestClient(app).get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_built_frontend_is_served_without_masking_unknown_api_routes():
    client = TestClient(app)
    frontend = client.get("/")
    assert frontend.status_code == 200
    assert '<div id="root"></div>' in frontend.text

    missing_api = client.get("/api/v1/not-a-route")
    assert missing_api.status_code == 404
    assert missing_api.json() == {"detail": "API route not found"}
