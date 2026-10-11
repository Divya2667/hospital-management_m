import pytest
from werkzeug.security import generate_password_hash
from app.db import get_db, get_next_sequence_value


def login_admin(app, client):
    """Helper to authenticate a staff/admin user."""
    with app.app_context():
        db = get_db()
        u_id = get_next_sequence_value(db, "User_ID")
        db.users.update_one(
            {"Username": "admin_doctor_test"},
            {"$set": {
                "User_ID": u_id,
                "Username": "admin_doctor_test",
                "Password_Hash": generate_password_hash("pass123"),
                "Role": "Admin",
            }},
            upsert=True,
        )

    client.post("/auth/login", data={"username": "admin_doctor_test", "password": "pass123"})


def test_doctor_routes_require_authentication(client):
    """All doctor management endpoints must redirect unauthenticated visitors."""
    assert client.get("/doctors/").status_code == 302
    assert client.get("/doctors/create").status_code == 302
    assert client.get("/doctors/1").status_code == 302
    assert client.get("/doctors/1/edit").status_code == 302
    assert client.post("/doctors/1/toggle-status").status_code == 302
    assert client.post("/doctors/1/delete").status_code == 302


def test_doctor_create_validation_and_duplicate_phone(app, client):
    """Test doctor field validation, duplicate phone rejection, and successful insertion."""
    login_admin(app, client)

    # 1. Validation failure: empty name
    res = client.post(
        "/doctors/create",
        data={"name": "", "qualification": "MD", "experience": "5", "phone": "555-1234"},
        follow_redirects=True,
    )
    assert b"Doctor name is required." in res.data

    # 2. Validation failure: empty qualification
    res = client.post(
        "/doctors/create",
        data={"name": "Dr. Strange", "qualification": "", "experience": "5", "phone": "555-1234"},
        follow_redirects=True,
    )
    assert b"Doctor qualification is required." in res.data

    # 3. Validation failure: negative experience
    res = client.post(
        "/doctors/create",
        data={"name": "Dr. Strange", "qualification": "MD", "experience": "-1", "phone": "555-1234"},
        follow_redirects=True,
    )
    assert b"Experience cannot be negative." in res.data

    # 4. Validation failure: invalid/too short phone
    res = client.post(
        "/doctors/create",
        data={"name": "Dr. Strange", "qualification": "MD", "experience": "5", "phone": "123"},
        follow_redirects=True,
    )
    assert b"Phone number must contain between 7 and 15 digits." in res.data

    # 5. Successful doctor creation
    success_res = client.post(
        "/doctors/create",
        data={
            "name": "Dr. Leonard McCoy",
            "qualification": "Chief Medical Officer, MD",
            "experience": "20",
            "phone": "555-888-9999",
        },
        follow_redirects=True,
    )
    assert success_res.status_code == 200
    assert b"Dr. Leonard McCoy" in success_res.data
    assert b"Chief Medical Officer, MD" in success_res.data
    assert b"20 Years" in success_res.data

    # 6. Duplicate phone rejection
    dup_res = client.post(
        "/doctors/create",
        data={
            "name": "Dr. Impostor",
            "qualification": "MBBS",
            "experience": "2",
            "phone": "555-888-9999",
        },
        follow_redirects=True,
    )
    assert b"Phone number is already associated with" in dup_res.data


def test_doctor_edit(app, client):
    """Test editing doctor credentials and experience."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        doctor_id = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({
            "Doctor_ID": doctor_id,
            "D_Name": "Dr. Beverly Crusher",
            "D_Qualification": "MD Neuro",
            "Experience": 15,
            "D_Phone": "555-111-2222",
            "is_active": 1,
        })

    # GET edit form
    get_res = client.get(f"/doctors/{doctor_id}/edit")
    assert get_res.status_code == 200
    assert b"Dr. Beverly Crusher" in get_res.data

    # POST updated details
    post_res = client.post(
        f"/doctors/{doctor_id}/edit",
        data={
            "name": "Dr. Beverly Crusher",
            "qualification": "MD Neurology, CMO",
            "experience": "16",
            "phone": "555-111-2222",
        },
        follow_redirects=True,
    )
    assert post_res.status_code == 200
    assert b"MD Neurology, CMO" in post_res.data
    assert b"16 Years" in post_res.data

    with app.app_context():
        db = get_db()
        updated = db.doctors.find_one({"Doctor_ID": doctor_id})
        assert updated["D_Qualification"] == "MD Neurology, CMO"
        assert updated["Experience"] == 16


def test_doctor_search_and_status_filtering(app, client):
    """Test searching doctors by name or qualification and filtering by active/inactive status."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        d1 = get_next_sequence_value(db, "Doctor_ID")
        d2 = get_next_sequence_value(db, "Doctor_ID")
        d3 = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({"Doctor_ID": d1, "D_Name": "Dr. Sanjay Gupta", "D_Qualification": "MD Neurosurgery", "Experience": 18, "D_Phone": "555-301-0001", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d2, "D_Name": "Dr. Atul Gawande", "D_Qualification": "MD General Surgery", "Experience": 22, "D_Phone": "555-301-0002", "is_active": 0})
        db.doctors.insert_one({"Doctor_ID": d3, "D_Name": "Dr. Paul Farmer", "D_Qualification": "MD Infectious Disease", "Experience": 25, "D_Phone": "555-301-0003", "is_active": 1})

    # Search by qualification "Neuro"
    search_res = client.get("/doctors/?search=Neuro")
    assert b"Dr. Sanjay Gupta" in search_res.data
    assert b"Dr. Atul Gawande" not in search_res.data

    # Filter active only
    active_res = client.get("/doctors/?status=active")
    assert b"Dr. Sanjay Gupta" in active_res.data
    assert b"Dr. Paul Farmer" in active_res.data
    assert b"Dr. Atul Gawande" not in active_res.data

    # Filter inactive only
    inactive_res = client.get("/doctors/?status=inactive")
    assert b"Dr. Atul Gawande" in inactive_res.data
    assert b"Dr. Sanjay Gupta" not in inactive_res.data


def test_doctor_deactivation_toggle(app, client):
    """Test toggling doctor on-duty and off-duty status."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        doctor_id = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({"Doctor_ID": doctor_id, "D_Name": "Dr. Toggle Test", "D_Qualification": "MBBS", "Experience": 6, "D_Phone": "555-444-5555", "is_active": 1})

    # Deactivate
    toggle_res = client.post(f"/doctors/{doctor_id}/toggle-status", follow_redirects=True)
    assert toggle_res.status_code == 200
    assert b"deactivated (off-duty)" in toggle_res.data

    with app.app_context():
        db = get_db()
        doc = db.doctors.find_one({"Doctor_ID": doctor_id})
        assert doc["is_active"] == 0

    # Reactivate
    toggle_res2 = client.post(f"/doctors/{doctor_id}/toggle-status", follow_redirects=True)
    assert toggle_res2.status_code == 200
    assert b"reactivated (on-duty)" in toggle_res2.data

    with app.app_context():
        db = get_db()
        doc = db.doctors.find_one({"Doctor_ID": doctor_id})
        assert doc["is_active"] == 1


def test_doctor_assigned_appointments_history(app, client):
    """Test doctor detail view displays their clinical appointments schedule."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        d_id = get_next_sequence_value(db, "Doctor_ID")
        a_id = get_next_sequence_value(db, "Appointment_ID")

        db.patients.insert_one({"Patient_id": p_id, "P_Name": "Rose Tyler", "P_Age": 21, "P_Gender": "Female", "Blood_Group": "O+", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d_id, "D_Name": "Dr. John Watson", "D_Qualification": "MD Military Surgery", "Experience": 12, "D_Phone": "555-221-BAKR", "is_active": 1})
        db.appointments.insert_one({
            "Appointment_ID": a_id,
            "Patient_id": p_id,
            "Doctor_ID": d_id,
            "A_Date": "2026-10-25",
            "A_Time": "14:00",
            "Reason": "Shoulder Wound Assessment",
            "Duration_Min": 30,
            "Status": "Scheduled",
        })

    res = client.get(f"/doctors/{d_id}")
    assert res.status_code == 200
    assert b"Dr. John Watson" in res.data
    assert b"Rose Tyler" in res.data
    assert b"Shoulder Wound Assessment" in res.data
    assert b"14:00" in res.data
    assert b"1 Appointments" in res.data


def test_doctor_safe_deletion_prevented_with_appointments(app, client):
    """Safe deletion must prevent deleting doctors who have historical appointment records."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        d_id = get_next_sequence_value(db, "Doctor_ID")
        a_id = get_next_sequence_value(db, "Appointment_ID")

        db.patients.insert_one({"Patient_id": p_id, "P_Name": "Patient One", "P_Age": 30, "P_Gender": "Male", "Blood_Group": "A+", "is_active": 1})
        db.doctors.insert_one({"Doctor_ID": d_id, "D_Name": "Dr. Essential", "D_Qualification": "MD Cardiology", "Experience": 20, "D_Phone": "555-900-1111", "is_active": 1})
        db.appointments.insert_one({
            "Appointment_ID": a_id,
            "Patient_id": p_id,
            "Doctor_ID": d_id,
            "A_Date": "2026-10-26",
            "A_Time": "10:00",
            "Reason": "ECG Followup",
            "Duration_Min": 30,
            "Status": "Scheduled",
        })

    del_res = client.post(f"/doctors/{d_id}/delete", follow_redirects=True)
    assert del_res.status_code == 200
    assert b"Cannot delete Doctor" in del_res.data
    assert b"Please deactivate the doctor instead" in del_res.data

    with app.app_context():
        db = get_db()
        assert db.doctors.find_one({"Doctor_ID": d_id}) is not None


def test_doctor_deletion_success_standalone(app, client):
    """Deleting a doctor with zero appointments must succeed."""
    login_admin(app, client)

    with app.app_context():
        db = get_db()
        d_id = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({"Doctor_ID": d_id, "D_Name": "Dr. Temporary", "D_Qualification": "MBBS", "Experience": 1, "D_Phone": "555-000-9999", "is_active": 1})

    del_res = client.post(f"/doctors/{d_id}/delete", follow_redirects=True)
    assert del_res.status_code == 200
    assert b"was successfully deleted." in del_res.data

    with app.app_context():
        db = get_db()
        assert db.doctors.find_one({"Doctor_ID": d_id}) is None
