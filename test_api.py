from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test-oceanguard.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("APP_SECRET", "ci-secret")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin123")

    import importlib
    import database
    import backend

    importlib.reload(database)
    importlib.reload(backend)
    return TestClient(backend.app)


def test_health_and_config(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    config = client.get("/api/config")
    assert config.status_code == 200
    assert config.json()["map"]["google_maps_link_supported"] is True


def test_categories_reports_and_analytics(client):
    categories = client.get("/api/categories")
    assert categories.status_code == 200
    category_ids = {item["id"] for item in categories.json()["categories"]}
    assert "oil_spill" in category_ids
    assert "high_waves" in category_ids

    reports = client.get("/api/reports")
    assert reports.status_code == 200
    data = reports.json()["reports"]
    assert len(data) >= 5
    assert all("report_code" in item for item in data)
    assert all(-90 <= item["latitude"] <= 90 for item in data)
    assert all(-180 <= item["longitude"] <= 180 for item in data)

    analytics = client.get("/api/analytics/stats")
    assert analytics.status_code == 200
    assert analytics.json()["total_reports"] >= 5


def test_login_registration_and_admin_protection(client):
    unauthorised = client.patch(
        "/api/reports/1",
        json={"status": "Verified", "admin_notes": "test"},
    )
    assert unauthorised.status_code == 403

    login = client.post(
        "/api/auth/login",
        json={"login": "admin", "password": "admin123"},
    )
    assert login.status_code == 200
    token = login.json()["token"]
    assert "." in token

    me = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer " + token},
    )
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "admin"

    register = client.post(
        "/api/auth/register",
        json={
            "username": "student_demo",
            "email": "student_demo@example.com",
            "password": "password123",
            "full_name": "Student Demo",
            "role": "admin",
        },
    )
    assert register.status_code == 200
    assert register.json()["user"]["role"] == "user"

    bad_admin = client.patch(
        "/api/reports/1",
        json={"status": "Verified", "admin_notes": "verified in test"},
        headers={"Authorization": "Bearer " + register.json()["token"]},
    )
    assert bad_admin.status_code == 403


def test_tracking_lifecycle(client):
    locations = client.get("/api/tracking")
    assert locations.status_code == 200

    update = client.post(
        "/api/tracking",
        json={
            "vessel_id": "TEST-VESSEL-01",
            "latitude": 11.2,
            "longitude": 79.95,
            "accuracy": 8,
            "speed_knots": 5.2,
            "heading": 90,
        },
    )
    assert update.status_code == 200

    locations = client.get("/api/tracking")
    assert any(
        item["vessel_id"] == "TEST-VESSEL-01"
        for item in locations.json()["locations"]
    )

    stop = client.delete("/api/tracking/TEST-VESSEL-01")
    assert stop.status_code == 200

    locations = client.get("/api/tracking")
    assert all(
        item["vessel_id"] != "TEST-VESSEL-01"
        for item in locations.json()["locations"]
    )


def test_frontend_contract():
    path = Path(__file__).resolve().parent / "static" / "index.html"
    assert path.exists()
    html = path.read_text(encoding="utf-8")

    required = [
        'id="map"',
        'id="report-form"',
        'id="tracking-toggle"',
        'id="admin-login-form"',
        '/api/reports',
        '/api/tracking',
        '/api/weather',
        '/api/marine',
    ]
    for marker in required:
        assert marker in html

    import re

    declared_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r"getElementById\(['\"]([^'\"]+)['\"]\)", html))
    assert js_ids.issubset(declared_ids)

    assert "tile.openstreetmap.org" in html
    assert "google.com/maps" in html

def test_external_weather_and_marine_contract(client, monkeypatch):
    import backend

    async def fake_fetch(url, params, cache_key):
        if "marine-api.open-meteo.com" in url:
            assert params["cell_selection"] == "sea"
            return {
                "latitude": 11.15,
                "longitude": 79.95,
                "timezone": "Asia/Kolkata",
                "current": {
                    "wave_height": 1.2,
                    "wave_direction": 180,
                    "wave_period": 6.5,
                    "wind_wave_height": 0.8,
                    "swell_wave_height": 0.9,
                    "sea_surface_temperature": 29.1,
                    "ocean_current_velocity": 0.4,
                    "ocean_current_direction": 90,
                },
                "hourly": {
                    "wave_height": [1.2, 1.8, 1.5],
                    "swell_wave_height": [0.9, 1.1, 1.0],
                },
            }
        assert url == "https://api.open-meteo.com/v1/forecast"
        return {
            "latitude": 11.15,
            "longitude": 79.95,
            "timezone": "Asia/Kolkata",
            "current": {
                "temperature_2m": 30.2,
                "wind_speed_10m": 18.0,
                "wind_gusts_10m": 29.0,
            },
        }

    monkeypatch.setattr(backend, "fetch_open_meteo", fake_fetch)

    weather = client.get("/api/weather?latitude=11.15&longitude=79.95")
    assert weather.status_code == 200
    assert weather.json()["current"]["wind_speed_10m"] == 18.0

    marine = client.get("/api/marine?latitude=11.15&longitude=79.95")
    assert marine.status_code == 200
    data = marine.json()
    assert data["current"]["wave_height"] == 1.2
    assert data["current"]["next_12h_wave_peak_m"] == 1.8
    assert data["current"]["next_12h_swell_peak_m"] == 1.1

