import pytest
from werkzeug.security import generate_password_hash
from app.db import get_db, get_next_sequence_value


def create_authenticated_user(app, client, username="admin_user", role="Admin"):
    """Helper to register and login a user for dashboard testing."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.update_one(
            {"Username": username},
            {"$set": {
                "User_ID": u_id,
                "Username": username,
                "Password_Hash": generate_password_hash("pass123"),
                "Role": role,
            }},
            upsert=True,
        )

    client.post("/auth/login", data={"username": username, "password": "pass123"})


def test_dashboard_unauthenticated_redirect(client):
    """Unauthenticated users must be redirected to login."""
    res = client.get("/dashboard")
    assert res.status_code == 302
    assert "/auth/login?next=/dashboard" in res.headers["Location"]


def test_dashboard_authenticated_empty_state(app, client):
    """Authenticated user sees dashboard structure and empty state counts of 0."""
    create_authenticated_user(app, client, "doc_dan", "Doctor")
    response = client.get("/dashboard")
    assert response.status_code == 200

    # Verification of base layout elements
    assert b"Hospital Operations Dashboard" in response.data
    assert b"doc_dan" in response.data
    assert b"Doctor" in response.data
    assert b"sidebar-wrapper" in response.data
    assert b"sidebarToggle" in response.data
    assert b"btn-logout" in response.data

    # Verification of summary metric cards and zero counts
    assert b'id="val-patients-count">0</div>' in response.data
    assert b'id="val-doctors-count">0</div>' in response.data
    assert b'id="val-appointments-count">0</div>' in response.data
    assert b'id="val-bills-count">0</div>' in response.data

    # Verification of empty state messages
    assert b"No Appointments Yet" in response.data
    assert b"No Billing Records Yet" in response.data


def test_dashboard_dynamic_aggregations_and_joins(app, client):
    """Verify dynamic aggregation counts and recent appointment/bill table rows."""
    create_authenticated_user(app, client, "hospital_admin", "Admin")

    with app.app_context():
        db = get_db()
        p1 = get_next_sequence_value(db, "Patient_id")
        p2 = get_next_sequence_value(db, "Patient_id")
        p3 = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({"Patient_id": p1, "P_Name": "Emily Clark", "P_Age": 32, "P_Gender": "Female", "Blood_Group": "O+", "is_active": 1})
        db.patients.insert_one({"Patient_id": p2, "P_Name": "David Miller", "P_Age": 45, "P_Gender": "Male", "Blood_Group": "A+", "is_active": 1})
        db.patients.insert_one({"Patient_id": p3, "P_Name": "Inactive Patient", "P_Age": 60, "P_Gender": "Male", "Blood_Group": "B-", "is_active": 0})

        d1 = get_next_sequence_value(db, "Doctor_ID")
        d2 = get_next_sequence_value(db, "Doctor_ID")
        d3 = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({"Doctor_ID": d1, "D_Name": "Dr. Gregory House", "D_Qualification": "MD Diagnostics", "Experience": 15, "D_Phone": "555-101", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d2, "D_Name": "Dr. Allison Cameron", "D_Qualification": "MD Immunology", "Experience": 8, "D_Phone": "555-102", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d3, "D_Name": "Dr. Retired", "D_Qualification": "MBBS", "Experience": 30, "D_Phone": "555-103", "is_active": 0})

        a1 = get_next_sequence_value(db, "Appointment_ID")
        a2 = get_next_sequence_value(db, "Appointment_ID")
        db.appointments.insert_one({
            "Appointment_ID": a1,
            "Patient_id": p1,
            "Doctor_ID": d1,
            "A_Date": "2026-10-15",
            "A_Time": "10:00",
            "Reason": "Cardiac Consultation",
            "Duration_Min": 30,
            "Status": "Scheduled",
        })
        db.appointments.insert_one({
            "Appointment_ID": a2,
            "Patient_id": p2,
            "Doctor_ID": d2,
            "A_Date": "2026-10-14",
            "A_Time": "14:30",
            "Reason": "Routine Followup",
            "Duration_Min": 30,
            "Status": "Completed",
        })

        b1 = get_next_sequence_value(db, "Bill_ID")
        b2 = get_next_sequence_value(db, "Bill_ID")
        db.bills.insert_one({"Bill_ID": b1, "Patient_id": p1, "B_Date": "2026-10-14", "B_Amount": 150.00, "Pay_Mode": "Cash"})
        db.bills.insert_one({"Bill_ID": b2, "Patient_id": p2, "B_Date": "2026-10-15", "B_Amount": 250.50, "Pay_Mode": "UPI"})

    # Query dashboard
    response = client.get("/dashboard")
    assert response.status_code == 200

    # 1. Active Patients = 2, Total = 3
    assert b'id="val-patients-count">2</div>' in response.data
    assert b"3 total registered" in response.data

    # 2. Active Doctors = 2
    assert b'id="val-doctors-count">2</div>' in response.data

    # 3. Appointments = 2 (1 scheduled)
    assert b'id="val-appointments-count">2</div>' in response.data
    assert b"1 scheduled upcoming" in response.data

    # 4. Total Bills = 2, Total Revenue = $400.50
    assert b'id="val-bills-count">2</div>' in response.data
    assert b"$400.50" in response.data

    # 5. Appointments table verification
    assert b"Emily Clark" in response.data
    assert b"Dr. Gregory House" in response.data
    assert b"Cardiac Consultation" in response.data
    assert b"David Miller" in response.data
    assert b"Dr. Allison Cameron" in response.data
    assert b"Scheduled" in response.data
    assert b"Completed" in response.data

    # 6. Bills table verification
    assert b"UPI" in response.data
    assert b"Cash" in response.data
    assert b"$150.00" in response.data
    assert b"$250.50" in response.data


def test_clickable_cards_and_navigation_links(app, client):
    """Summary cards must be clickable links leading to corresponding management modules."""
    create_authenticated_user(app, client, "nav_tester", "Admin")
    response = client.get("/dashboard")
    assert response.status_code == 200

    assert b'id="card-metric-patients"' in response.data
    assert b'id="card-metric-doctors"' in response.data
    assert b'id="card-metric-appointments"' in response.data
    assert b'id="card-metric-billing"' in response.data
