import json


def test_app_creation(app):
    """Test that the application initializes successfully with test config."""
    assert app is not None
    assert app.testing is True
    assert "MONGO_URI" in app.config


def test_index_route(client):
    """Test that the index route redirects unauthenticated users to the login portal."""
    response = client.get("/", follow_redirects=True)
    assert response.status_code == 200
    assert b"Hospital Portal" in response.data


def test_health_route(client):
    """Test that the health check endpoint returns 200 and correct JSON structure."""
    response = client.get("/health")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "healthy"
    assert data["app"] == "Hospital Management System"
    assert "clinic_hours" in data


def test_config_override():
    """Test that application factory properly honors custom test configuration."""
    from app import create_app

    custom_app = create_app(test_config={"TEST_CUSTOM_KEY": "CustomValue", "TESTING": True})
    assert custom_app.config["TEST_CUSTOM_KEY"] == "CustomValue"
