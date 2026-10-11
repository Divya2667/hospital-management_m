import pytest
from werkzeug.security import generate_password_hash
from app.db import get_db, get_next_sequence_value


def login_admin(app, client):
    """Helper to authenticate a staff/admin user."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.update_one(
            {"Username": "admin_patient_test"},
            {"$set": {
                "User_ID": u_id,
                "Username": "admin_patient_test",
                "Password_Hash": generate_password_hash("pass123"),
                "Role": "Admin",
            }},
            upsert=True,
        )

    client.post("/auth/login", data={"username": "admin_patient_test", "password": "pass123"})


def test_patient_routes_require_authentication(client):
    """All patient routes must redirect unauthenticated visitors."""
    assert client.get("/patients/").status_code == 302
    assert client.get("/patients/create").status_code == 302
    assert client.get("/patients/1").status_code == 302
    assert client.get("/patients/1/edit").status_code == 302
    assert client.post("/patients/1/toggle-status").status_code == 302
    assert client.post("/patients/1/delete").status_code == 302


def test_patient_create_validation_and_success(app, client):
    """Test server-side validation and successful creation of a patient."""
    login_admin(app, client)

    # 1. Validation failure: empty name
    res = client.post(
        "/patients/create",
        data={"name": "", "age": "25", "gender": "Male", "blood_group": "O+"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b"Patient name is required." in res.data

    # 2. Validation failure: age out of range
    res = client.post(
        "/patients/create",
        data={"name": "Old Person", "age": "150", "gender": "Male", "blood_group": "O+"},
        follow_redirects=True,
    )
    assert b"Patient age must be between 0 and 120." in res.data

    # 3. Validation failure: invalid gender
    res = client.post(
        "/patients/create",
        data={"name": "Test Person", "age": "30", "gender": "Unknown", "blood_group": "O+"},
        follow_redirects=True,
    )
    assert b"Gender must be one of: Male, Female, Other." in res.data

    # 4. Validation failure: invalid blood group
    res = client.post(
        "/patients/create",
        data={"name": "Test Person", "age": "30", "gender": "Female", "blood_group": "X+"},
        follow_redirects=True,
    )
    assert b"Blood group must be one of:" in res.data

    # 5. Successful registration
    success_res = client.post(
        "/patients/create",
        data={"name": "Samantha Wright", "age": "29", "gender": "Female", "blood_group": "B+"},
        follow_redirects=True,
    )
    assert success_res.status_code == 200
    assert b"Samantha Wright" in success_res.data
    assert b"29 Years" in success_res.data
    assert b"B+" in success_res.data

    with app.app_context():
        db = get_db()
        patient = db.patients.find_one({"P_Name": "Samantha Wright"})
        assert patient is not None
        assert patient["P_Age"] == 29
        assert patient["P_Gender"] == "Female"
        assert patient["Blood_Group"] == "B+"
        assert patient["is_active"] == 1


def test_patient_edit(app, client):
    """Test editing an existing patient's details."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        patient_id = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({
            "Patient_id": patient_id,
            "P_Name": "Robert Fox",
            "P_Age": 50,
            "P_Gender": "Male",
            "Blood_Group": "A+",
            "is_active": 1,
        })

    # GET edit form
    get_res = client.get(f"/patients/{patient_id}/edit")
    assert get_res.status_code == 200
    assert b"Robert Fox" in get_res.data

    # POST updated details
    post_res = client.post(
        f"/patients/{patient_id}/edit",
        data={"name": "Robert Fox Jr.", "age": "51", "gender": "Male", "blood_group": "AB+"},
        follow_redirects=True,
    )
    assert post_res.status_code == 200
    assert b"Robert Fox Jr." in post_res.data
    assert b"51 Years" in post_res.data
    assert b"AB+" in post_res.data

    with app.app_context():
        db = get_db()
        updated = db.patients.find_one({"Patient_id": patient_id})
        assert updated["P_Name"] == "Robert Fox Jr."
        assert updated["P_Age"] == 51
        assert updated["Blood_Group"] == "AB+"


def test_patient_search_and_status_filtering(app, client):
    """Test search by name, search by ID, and active/inactive status filtering."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        p1 = get_next_sequence_value(db, "Patient_id")
        p2 = get_next_sequence_value(db, "Patient_id")
        p3 = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({"Patient_id": p1, "P_Name": "Alice Johnson", "P_Age": 25, "P_Gender": "Female", "Blood_Group": "O+", "is_active": 1})
        db.patients.insert_one({"Patient_id": p2, "P_Name": "Bob Smith", "P_Age": 40, "P_Gender": "Male", "Blood_Group": "A-", "is_active": 0})
        db.patients.insert_one({"Patient_id": p3, "P_Name": "Alicia Keys", "P_Age": 35, "P_Gender": "Female", "Blood_Group": "B+", "is_active": 1})

    # Search by partial name "Alic"
    search_res = client.get("/patients/?search=Alic")
    assert b"Alice Johnson" in search_res.data
    assert b"Alicia Keys" in search_res.data
    assert b"Bob Smith" not in search_res.data

    # Filter active only
    active_res = client.get("/patients/?status=active")
    assert b"Alice Johnson" in active_res.data
    assert b"Bob Smith" not in active_res.data

    # Filter inactive only
    inactive_res = client.get("/patients/?status=inactive")
    assert b"Bob Smith" in inactive_res.data
    assert b"Alice Johnson" not in inactive_res.data


def test_patient_deactivation_toggle(app, client):
    """Test toggling a patient active and inactive."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        patient_id = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({"Patient_id": patient_id, "P_Name": "Mark Otto", "P_Age": 33, "P_Gender": "Male", "Blood_Group": "O-", "is_active": 1})

    # Deactivate
    toggle_res = client.post(f"/patients/{patient_id}/toggle-status", follow_redirects=True)
    assert toggle_res.status_code == 200
    assert b"has been deactivated." in toggle_res.data

    with app.app_context():
        db = get_db()
        doc = db.patients.find_one({"Patient_id": patient_id})
        assert doc["is_active"] == 0

    # Reactivate
    toggle_res2 = client.post(f"/patients/{patient_id}/toggle-status", follow_redirects=True)
    assert toggle_res2.status_code == 200
    assert b"has been reactivated." in toggle_res2.data

    with app.app_context():
        db = get_db()
        doc = db.patients.find_one({"Patient_id": patient_id})
        assert doc["is_active"] == 1


def test_patient_detail_appointment_and_billing_history(app, client):
    """Test patient detail view displays complete appointment history, bills, and totals."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        d_id = get_next_sequence_value(db, "Doctor_ID")
        a_id = get_next_sequence_value(db, "Appointment_ID")
        b_id_1 = get_next_sequence_value(db, "Bill_ID")
        b_id_2 = get_next_sequence_value(db, "Bill_ID")

        db.patients.insert_one({"Patient_id": p_id, "P_Name": "Clara Oswald", "P_Age": 26, "P_Gender": "Female", "Blood_Group": "AB+", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d_id, "D_Name": "Dr. Who", "D_Qualification": "MD Time Lord", "Experience": 900, "D_Phone": "555-TARDIS", "is_active": 1})
        db.appointments.insert_one({
            "Appointment_ID": a_id,
            "Patient_id": p_id,
            "Doctor_ID": d_id,
            "A_Date": "2026-10-20",
            "A_Time": "09:30",
            "Reason": "Tachyon Exposure Check",
            "Duration_Min": 30,
            "Status": "Scheduled",
        })
        db.bills.insert_one({"Bill_ID": b_id_1, "Patient_id": p_id, "B_Date": "2026-10-18", "B_Amount": 350.00, "Pay_Mode": "Insurance"})
        db.bills.insert_one({"Bill_ID": b_id_2, "Patient_id": p_id, "B_Date": "2026-10-20", "B_Amount": 120.50, "Pay_Mode": "Card"})

    detail_res = client.get(f"/patients/{p_id}")
    assert detail_res.status_code == 200
    assert b"Dr. Who" in detail_res.data
    assert b"Tachyon Exposure Check" in detail_res.data
    assert b"2026-10-20" in detail_res.data
    assert b"$350.00" in detail_res.data
    assert b"$120.50" in detail_res.data
    assert b"$470.50" in detail_res.data


def test_patient_safe_deletion_prevented_with_records(app, client):
    """Safe deletion must block deleting a patient with existing appointments or bills."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        d_id = get_next_sequence_value(db, "Doctor_ID")
        a_id = get_next_sequence_value(db, "Appointment_ID")

        db.patients.insert_one({"Patient_id": p_id, "P_Name": "Protected Patient", "P_Age": 45, "P_Gender": "Male", "Blood_Group": "O+", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d_id, "D_Name": "Dr. Care", "D_Qualification": "MBBS", "Experience": 5, "D_Phone": "555-001", "is_active": 1})
        db.appointments.insert_one({
            "Appointment_ID": a_id,
            "Patient_id": p_id,
            "Doctor_ID": d_id,
            "A_Date": "2026-10-22",
            "A_Time": "11:00",
            "Reason": "Checkup",
            "Duration_Min": 30,
            "Status": "Scheduled",
        })

    del_res = client.post(f"/patients/{p_id}/delete", follow_redirects=True)
    assert del_res.status_code == 200
    assert b"Cannot delete Patient" in del_res.data
    assert b"Please deactivate the patient instead" in del_res.data

    with app.app_context():
        db = get_db()
        assert db.patients.find_one({"Patient_id": p_id}) is not None


def test_patient_deletion_success_standalone(app, client):
    """Deleting a patient without any appointment or billing records should succeed."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({"Patient_id": p_id, "P_Name": "Disposable Patient", "P_Age": 22, "P_Gender": "Other", "Blood_Group": "A+", "is_active": 1})

    del_res = client.post(f"/patients/{p_id}/delete", follow_redirects=True)
    assert del_res.status_code == 200
    assert b"was successfully deleted." in del_res.data

    with app.app_context():
        db = get_db()
        assert db.patients.find_one({"Patient_id": p_id}) is None
