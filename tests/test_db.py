import pytest
from app.db import get_db, close_db, get_next_sequence_value


def test_get_close_db(app):
    """Test that get_db returns the same connection in context and cleans up on teardown."""
    with app.app_context():
        db = get_db()
        assert db is get_db()
        assert db.name == app.config["MONGO_DB_NAME"]


def test_init_db_command(runner, monkeypatch):
    """Test the flask init-db CLI command."""
    class Recorder:
        called = False

    def fake_init_db():
        Recorder.called = True

    monkeypatch.setattr("app.db.init_db", fake_init_db)
    result = runner.invoke(args=["init-db"])
    assert "Initialized the MongoDB database successfully." in result.output
    assert Recorder.called is True


def test_patient_crud_and_sequences(app):
    """Test Patient sequence generation and collection operations."""
    with app.app_context():
        db = get_db()
        p_id = get_next_sequence_value(db, "Patient_id")
        db.patients.insert_one({
            "Patient_id": p_id,
            "P_Name": "John Doe",
            "P_Age": 35,
            "P_Gender": "Male",
            "Blood_Group": "O+",
            "is_active": 1,
        })
        doc = db.patients.find_one({"Patient_id": p_id})
        assert doc is not None
        assert doc["P_Name"] == "John Doe"
        assert doc["P_Age"] == 35


def test_doctor_crud_and_phone(app):
    """Test Doctor collection insertion and retrieval."""
    with app.app_context():
        db = get_db()
        d_id = get_next_sequence_value(db, "Doctor_ID")
        db.doctors.insert_one({
            "Doctor_ID": d_id,
            "D_Name": "Dr. Smith",
            "D_Qualification": "MD Cardiology",
            "Experience": 12,
            "D_Phone": "9876543210",
            "is_active": 1,
        })
        doc = db.doctors.find_one({"D_Phone": "9876543210"})
        assert doc is not None
        assert doc["Doctor_ID"] == d_id


def test_appointment_and_bill_sequences(app):
    """Test atomic sequence generation for appointments and bills."""
    with app.app_context():
        db = get_db()
        a_id_1 = get_next_sequence_value(db, "Appointment_ID")
        a_id_2 = get_next_sequence_value(db, "Appointment_ID")
        b_id = get_next_sequence_value(db, "Bill_ID")
        assert a_id_2 == a_id_1 + 1
        assert b_id >= 1


def test_user_admin_initialized(app):
    """Test default admin user is initialized upon init_db."""
    with app.app_context():
        db = get_db()
        admin = db.users.find_one({"Username": "admin"})
        assert admin is not None
        assert admin["Role"] == "Admin"


def test_load_dataset_cli_and_seeder(runner, app):
    """Verify that flask load-dataset CLI command imports dataset CSVs into MongoDB."""
    result = runner.invoke(args=["load-dataset"])
    assert "MongoDB dataset loaded successfully:" in result.output
    assert "50 patients" in result.output
    assert "10 doctors" in result.output
    assert "200 appointments" in result.output
    assert "200 bills" in result.output

    with app.app_context():
        db = get_db()
        assert db.patients.count_documents({}) == 50
        assert db.doctors.count_documents({}) == 10
        assert db.appointments.count_documents({}) == 200
        assert db.bills.count_documents({}) == 200
