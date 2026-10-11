import pytest
from flask import session, g
from werkzeug.security import generate_password_hash, check_password_hash
from app.db import get_db, get_next_sequence_value
from app import create_app


def test_login_page_renders(client):
    """Test that login page loads with HTTP 200 and contains required elements."""
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Hospital Portal" in response.data
    assert b"Username" in response.data
    assert b"Password" in response.data
    assert b"toggle-password-visibility" in response.data
    assert b"Sign In" in response.data


def test_unauthenticated_access_redirects(client):
    """Unauthenticated users attempting to access protected routes must be redirected to login."""
    res_dashboard = client.get("/dashboard")
    assert res_dashboard.status_code == 302
    assert "/auth/login?next=/dashboard" in res_dashboard.headers["Location"]

    res_root = client.get("/")
    assert res_root.status_code == 302
    assert "/auth/login" in res_root.headers["Location"]


def test_login_validation_empty_fields(client):
    """Submitting empty username or password should display a clear error message."""
    response = client.post("/auth/login", data={"username": "", "password": ""}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Please provide both username and password." in response.data


def test_login_invalid_credentials(app, client):
    """Submitting incorrect username or password should display generic error message."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.insert_one({
            "User_ID": u_id,
            "Username": "nurse_joy",
            "Password_Hash": generate_password_hash("securepass123"),
            "Role": "Staff",
        })

    # Wrong password
    res1 = client.post("/auth/login", data={"username": "nurse_joy", "password": "wrongpassword"}, follow_redirects=True)
    assert res1.status_code == 200
    assert b"Invalid username or password." in res1.data

    # Non-existent user
    res2 = client.post("/auth/login", data={"username": "ghost_user", "password": "anypassword"}, follow_redirects=True)
    assert res2.status_code == 200
    assert b"Invalid username or password." in res2.data


def test_login_successful_and_session(app, client):
    """Valid credentials authenticate user, start session, and grant access to dashboard."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.insert_one({
            "User_ID": u_id,
            "Username": "dr_house",
            "Password_Hash": generate_password_hash("vicodin123"),
            "Role": "Doctor",
        })

    # Perform login
    response = client.post("/auth/login", data={"username": "dr_house", "password": "vicodin123"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Hospital Operations Dashboard" in response.data
    assert b"dr_house" in response.data
    assert b"Doctor" in response.data

    # Check session state
    with client.session_transaction() as sess:
        assert sess.get("username") == "dr_house"
        assert sess.get("role") == "Doctor"
        assert "user_id" in sess


def test_open_redirect_protection(app, client):
    """Login next parameter should reject external URLs to prevent open redirect vulnerabilities."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.insert_one({
            "User_ID": u_id,
            "Username": "safe_user",
            "Password_Hash": generate_password_hash("password123"),
            "Role": "Staff",
        })

    # Attempt login with external next URL
    response = client.post(
        "/auth/login?next=https://attacker.com/steal-creds",
        data={"username": "safe_user", "password": "password123"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_logout(app, client):
    """POST to /auth/logout clears authenticated session and revokes access to protected routes."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.insert_one({
            "User_ID": u_id,
            "Username": "admin_test",
            "Password_Hash": generate_password_hash("adminpass"),
            "Role": "Admin",
        })

    client.post("/auth/login", data={"username": "admin_test", "password": "adminpass"})

    with client.session_transaction() as sess:
        assert sess.get("username") == "admin_test"

    logout_res = client.post("/auth/logout", follow_redirects=True)
    assert logout_res.status_code == 200
    assert b"You have been signed out successfully." in logout_res.data

    with client.session_transaction() as sess:
        assert "username" not in sess
        assert "user_id" not in sess

    dash_res = client.get("/dashboard")
    assert dash_res.status_code == 302
    assert "/auth/login" in dash_res.headers["Location"]


def test_logout_get_method_not_allowed(client):
    """GET requests to /auth/logout must return 405 Method Not Allowed."""
    res = client.get("/auth/logout")
    assert res.status_code == 405


def test_create_admin_cli_command(runner, app):
    """Test flask create-admin CLI command creates user with hashed password."""
    result = runner.invoke(args=["create-admin", "--username", "superadmin", "--password", "AdminSecret99", "--role", "Admin"])
    assert "Administrator account 'superadmin' (Role: Admin) created successfully." in result.output

    with app.app_context():
        db = get_db()
        user = db.users.find_one({"Username": "superadmin"})
        assert user is not None
        assert user["Password_Hash"] != "AdminSecret99"
        assert check_password_hash(user["Password_Hash"], "AdminSecret99")
        assert user["Role"] == "Admin"

    dup_result = runner.invoke(args=["create-admin", "--username", "superadmin", "--password", "AnotherPass"])
    assert "Error: A user with username 'superadmin' already exists." in dup_result.output


def test_csrf_protection_enforced():
    """Verify that when CSRF protection is active, POST requests without CSRF token are blocked."""
    csrf_app = create_app(
        test_config={
            "TESTING": True,
            "MONGO_URI": "mongomock://localhost",
            "MONGO_DB_NAME": "csrf_test_db",
            "WTF_CSRF_ENABLED": True,
            "SECRET_KEY": "test-csrf-secret",
        }
    )
    with csrf_app.app_context():
        from app.db import init_db
        init_db()

    csrf_client = csrf_app.test_client()
    response = csrf_client.post("/auth/login", data={"username": "admin", "password": "password"})
    assert response.status_code == 400
