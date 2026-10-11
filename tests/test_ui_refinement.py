import pytest
from werkzeug.security import generate_password_hash
from app.db import get_db, get_next_sequence_value


def login_admin(app, client):
    """Helper to authenticate admin user."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.update_one(
            {"Username": "admin_ui_tester"},
            {"$set": {
                "User_ID": u_id,
                "Username": "admin_ui_tester",
                "Password_Hash": generate_password_hash("pass123"),
                "Role": "Admin",
            }},
            upsert=True,
        )

    client.post("/auth/login", data={"username": "admin_ui_tester", "password": "pass123"})


def test_static_assets_serve_correctly(client):
    """Verify that custom design system CSS and JavaScript are accessible and served with 200 OK."""
    css_resp = client.get("/static/css/style.css")
    assert css_resp.status_code == 200
    assert b"--primary-teal" in css_resp.data
    assert b"pulse-indicator" in css_resp.data
    assert b"@media print" in css_resp.data

    js_resp = client.get("/static/js/main.js")
    assert js_resp.status_code == 200
    assert b"quickNavModal" in js_resp.data
    assert b"applyTheme" in js_resp.data or b"themeToggleBtn" in js_resp.data


def test_responsive_viewport_meta_tags(client):
    """Ensure viewport meta tag is present on all views for mobile device responsiveness."""
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert b'<meta name="viewport" content="width=device-width, initial-scale=1">' in resp.data


def test_base_layout_top_navigation_and_quick_action(app, client):
    """Verify top navbar contains Quick Action dropdown, search modal trigger, and live hours indicator."""
    login_admin(app, client)

    resp = client.get("/dashboard", follow_redirects=True)
    assert resp.status_code == 200

    assert b"quickActionsDropdown" in resp.data
    assert b"Register Patient" in resp.data
    assert b"Add Doctor" in resp.data
    assert b"Book Appointment" in resp.data
    assert b"Issue Invoice" in resp.data

    assert b"quickNavModal" in resp.data
    assert b"quickNavInput" in resp.data
    assert b"Ctrl K" in resp.data

    assert b"pulse-indicator" in resp.data
    assert b"CLINIC_OPEN_TIME" in resp.data or b"09:00" in resp.data


def test_flash_messages_container_and_dismissibility(app, client):
    """Test flash message structure, styling, and alert container."""
    login_admin(app, client)

    resp = client.post("/patients/create", data={"name": ""}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"flash-messages-container" in resp.data
    assert b"alert-custom" in resp.data
    assert b"btn-close" in resp.data


def test_doctor_title_clean_rendering_no_double_prefix(app, client):
    """Ensure doctor names starting with 'Dr.' do not render as 'Dr. Dr.'."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        d_id = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({
            "Doctor_ID": d_id,
            "D_Name": "Dr. Stephen Strange",
            "D_Qualification": "MD Sorcery",
            "Experience": 15,
            "D_Phone": "555-888-9999",
            "is_active": 1,
        })

    resp = client.get("/appointments/create")
    assert resp.status_code == 200
    assert b"Dr. Stephen Strange" in resp.data
    assert b"Dr. Dr. Stephen Strange" not in resp.data


def test_theme_toggle_and_clinical_charts_present(app, client):
    """Verify theme switcher button, Chart.js canvases, and telemetry are rendered in dashboard."""
    login_admin(app, client)

    resp = client.get("/dashboard", follow_redirects=True)
    assert resp.status_code == 200
    assert b"themeToggleBtn" in resp.data
    assert b"themeIcon" in resp.data
    assert b"activityTrendChart" in resp.data
    assert b"settlementMixChart" in resp.data
    assert b"liveDashboardClock" in resp.data
    assert b"chart.umd.min.js" in resp.data
    assert b"confetti.browser.min.js" in resp.data
