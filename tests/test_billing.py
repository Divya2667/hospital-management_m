import pytest
from werkzeug.security import generate_password_hash
from app.db import get_db, get_next_sequence_value


def login_admin(app, client):
    """Helper to authenticate admin user."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.update_one(
            {"Username": "admin_billing_tester"},
            {"$set": {
                "User_ID": u_id,
                "Username": "admin_billing_tester",
                "Password_Hash": generate_password_hash("pass123"),
                "Role": "Admin",
            }},
            upsert=True,
        )

    client.post("/auth/login", data={"username": "admin_billing_tester", "password": "pass123"})


def seed_test_patient(app, name="Jane Billing", age=28, gender="Female", blood_group="A+", is_active=1):
    """Helper to insert a test patient."""
    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({
            "Patient_id": p_id,
            "P_Name": name,
            "P_Age": age,
            "P_Gender": gender,
            "Blood_Group": blood_group,
            "is_active": is_active,
        })
        return p_id


def seed_test_bill(app, patient_id, b_date="2026-10-15", amount=150.00, pay_mode="Cash"):
    """Helper to insert a test bill."""
    with app.app_context():
        db = get_db()
        b_id = get_next_sequence_value(db, "Bill_ID")
        db.bills.insert_one({
            "Bill_ID": b_id,
            "Patient_id": patient_id,
            "B_Date": b_date,
            "B_Amount": amount,
            "Pay_Mode": pay_mode,
        })
        return b_id


def test_billing_routes_require_authentication(client):
    """Ensure all billing management routes require authentication and redirect to login."""
    routes = [
        ("GET", "/billing/"),
        ("GET", "/billing/create"),
        ("POST", "/billing/create"),
        ("GET", "/billing/1"),
        ("GET", "/billing/1/edit"),
        ("POST", "/billing/1/edit"),
        ("POST", "/billing/1/delete"),
    ]

    for method, path in routes:
        if method == "GET":
            response = client.get(path, follow_redirects=False)
        else:
            response = client.post(path, data={}, follow_redirects=False)

        assert response.status_code == 302, f"Route {method} {path} should redirect unauthenticated user"
        assert "/auth/login" in response.headers["Location"]


def test_billing_validation_rules(app, client):
    """Verify input validation handles invalid amounts, payment modes, dates, and missing patients."""
    login_admin(app, client)
    p_id = seed_test_patient(app, name="Validation Patient")

    # 1. Non-existent patient
    resp = client.post(
        "/billing/create",
        data={
            "patient_id": "99999",
            "b_date": "2026-10-15",
            "b_amount": "100.00",
            "pay_mode": "Cash",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"The selected patient does not exist in the database." in resp.data

    # 2. Non-numeric or negative or zero amount
    for bad_amt in ["0", "-25.50", "abc", ""]:
        resp = client.post(
            "/billing/create",
            data={
                "patient_id": str(p_id),
                "b_date": "2026-10-15",
                "b_amount": bad_amt,
                "pay_mode": "Cash",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert (
            b"Bill amount must be greater than zero." in resp.data
            or b"Bill amount is required." in resp.data
            or b"Bill amount must be a valid positive number." in resp.data
        )

    # 3. Invalid payment mode
    resp = client.post(
        "/billing/create",
        data={
            "patient_id": str(p_id),
            "b_date": "2026-10-15",
            "b_amount": "120.00",
            "pay_mode": "Bitcoin",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Payment mode must be one of" in resp.data

    # 4. Invalid date format
    resp = client.post(
        "/billing/create",
        data={
            "patient_id": str(p_id),
            "b_date": "invalid-date",
            "b_amount": "120.00",
            "pay_mode": "Card",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Bill date must be in valid YYYY-MM-DD format." in resp.data


def test_billing_create_success_and_detail_view(app, client):
    """Test creating an invoice and viewing its detailed printable receipt."""
    login_admin(app, client)
    p_id = seed_test_patient(app, name="Robert Receipt")

    resp = client.post(
        "/billing/create",
        data={
            "patient_id": str(p_id),
            "b_date": "2026-10-15",
            "b_amount": "275.50",
            "pay_mode": "UPI",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"generated successfully" in resp.data
    assert b"Robert Receipt" in resp.data
    assert b"275.50" in resp.data
    assert b"UPI" in resp.data
    assert b"PAID" in resp.data

    with app.app_context():
        db = get_db()
        bill = db.bills.find_one({"Patient_id": p_id})
        assert bill is not None
        assert bill["B_Amount"] == 275.50
        assert bill["Pay_Mode"] == "UPI"
        assert bill["B_Date"] == "2026-10-15"
        bill_id = bill["Bill_ID"]

    detail_resp = client.get(f"/billing/{bill_id}")
    assert detail_resp.status_code == 200
    assert b"City General Hospital" in detail_resp.data
    assert b"Robert Receipt" in detail_resp.data
    assert b"275.50" in detail_resp.data
    assert b"window.print()" in detail_resp.data


def test_billing_aggregates_and_calculations(app, client):
    """Verify total revenue, invoice counts, average invoice amount, and payment mode breakdown."""
    login_admin(app, client)
    p_id = seed_test_patient(app, name="Financial Patient")

    seed_test_bill(app, p_id, amount=100.00, pay_mode="Cash")
    seed_test_bill(app, p_id, amount=200.00, pay_mode="Card")
    seed_test_bill(app, p_id, amount=300.00, pay_mode="UPI")

    resp = client.get("/billing/")
    assert resp.status_code == 200

    assert b"600.00" in resp.data
    assert b"Invoices Issued" in resp.data
    assert b"200.00" in resp.data


def test_billing_search_and_filtering(app, client):
    """Test searching by patient name, filtering by payment mode, and filtering by date range."""
    login_admin(app, client)
    p1_id = seed_test_patient(app, name="Alice Anderson")
    p2_id = seed_test_patient(app, name="Bob Builder")

    b1_id = seed_test_bill(app, p1_id, b_date="2026-10-01", amount=150.00, pay_mode="Cash")
    b2_id = seed_test_bill(app, p2_id, b_date="2026-10-20", amount=450.00, pay_mode="Insurance")

    # 1. Search by name "Alice"
    resp = client.get("/billing/?q=Alice")
    assert resp.status_code == 200
    assert b"Alice Anderson" in resp.data
    assert b"Bob Builder" not in resp.data

    # 2. Search by Bill ID
    resp = client.get(f"/billing/?q={b2_id}")
    assert resp.status_code == 200
    assert b"Bob Builder" in resp.data
    assert b"Alice Anderson" not in resp.data

    # 3. Filter by Payment Mode "Insurance"
    resp = client.get("/billing/?pay_mode=Insurance")
    assert resp.status_code == 200
    assert b"Bob Builder" in resp.data
    assert b"Alice Anderson" not in resp.data

    # 4. Filter by Date range
    resp = client.get("/billing/?date_from=2026-10-15&date_to=2026-10-25")
    assert resp.status_code == 200
    assert b"Bob Builder" in resp.data
    assert b"Alice Anderson" not in resp.data


def test_billing_edit(app, client):
    """Test updating an existing invoice."""
    login_admin(app, client)
    p_id = seed_test_patient(app, name="Edit Target")
    b_id = seed_test_bill(app, p_id, amount=100.00, pay_mode="Cash")

    resp = client.post(
        f"/billing/{b_id}/edit",
        data={
            "patient_id": str(p_id),
            "b_date": "2026-10-18",
            "b_amount": "350.00",
            "pay_mode": "Net Banking",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"updated successfully" in resp.data
    assert b"350.00" in resp.data
    assert b"Net Banking" in resp.data

    with app.app_context():
        db = get_db()
        bill = db.bills.find_one({"Bill_ID": b_id})
        assert bill["B_Amount"] == 350.00
        assert bill["Pay_Mode"] == "Net Banking"
        assert bill["B_Date"] == "2026-10-18"


def test_billing_delete(app, client):
    """Test deleting an invoice permanently."""
    login_admin(app, client)
    p_id = seed_test_patient(app, name="Delete Target")
    b_id = seed_test_bill(app, p_id, amount=85.00, pay_mode="Card")

    resp = client.post(f"/billing/{b_id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    assert b"was permanently deleted" in resp.data

    with app.app_context():
        db = get_db()
        bill = db.bills.find_one({"Bill_ID": b_id})
        assert bill is None


def test_billing_create_preselect_patient_from_query_param(app, client):
    """Verify that visiting /billing/create?patient_id=<id> pre-selects the patient."""
    login_admin(app, client)
    p_id = seed_test_patient(app, name="Preselected Patient")

    resp = client.get(f"/billing/create?patient_id={p_id}")
    assert resp.status_code == 200
    assert str(p_id).encode() in resp.data
    assert b"selected" in resp.data
