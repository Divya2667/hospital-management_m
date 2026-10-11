import os
import csv
import logging
from pathlib import Path
from werkzeug.security import generate_password_hash

logger = logging.getLogger(__name__)

BLOOD_GROUPS = ["O+", "A+", "B+", "AB+", "O-", "A-", "B-", "AB-"]
PAYMENT_MODE_MAP = {
    "Credit Card": "Card",
    "Debit Card": "Card",
    "Card": "Card",
    "Cash": "Cash",
    "UPI": "UPI",
    "Insurance": "Insurance",
    "Net Banking": "Net Banking",
}


def find_dataset_dir(custom_path=None):
    """Locate the dataset directory containing CSV files."""
    candidates = []
    if custom_path:
        candidates.append(Path(custom_path))

    current_file = Path(__file__).resolve()
    project_root = current_file.parent.parent
    candidates.append(project_root / "dataset")
    candidates.append(Path.cwd() / "dataset")

    for c in candidates:
        if c.exists() and (c / "patients.csv").exists():
            return c
    return None


def import_csv_dataset(db, dataset_dir=None):
    """Import records from dataset CSV files into MongoDB collections."""
    data_dir = find_dataset_dir(dataset_dir)
    if not data_dir:
        raise FileNotFoundError(f"Could not locate dataset folder. Searched candidates from {Path.cwd()}")

    stats = {
        "patients": 0,
        "doctors": 0,
        "appointments": 0,
        "treatments": 0,
        "bills": 0,
        "admin_created": False,
    }

    max_p_id = 0
    max_d_id = 0
    max_a_id = 0
    max_b_id = 0
    max_t_id = 0

    # 1. Patients
    patients_file = data_dir / "patients.csv"
    if patients_file.exists():
        with open(patients_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_raw_id = row.get("patient_id", "").strip()
                if not p_raw_id:
                    continue
                patient_id = int(p_raw_id.replace("P", "").lstrip("0") or "0")
                max_p_id = max(max_p_id, patient_id)
                first = row.get("first_name", "").strip()
                last = row.get("last_name", "").strip()
                name = f"{first} {last}".strip() or f"Patient {patient_id}"

                dob = row.get("date_of_birth", "").strip()
                birth_year = int(dob[:4]) if dob and len(dob) >= 4 and dob[:4].isdigit() else 1985
                age = max(0, min(120, 2026 - birth_year))

                raw_gender = row.get("gender", "").strip().upper()
                gender = "Male" if raw_gender == "M" else ("Female" if raw_gender == "F" else "Other")
                blood_group = BLOOD_GROUPS[(patient_id - 1) % len(BLOOD_GROUPS)]

                db.patients.update_one(
                    {"Patient_id": patient_id},
                    {"$set": {
                        "Patient_id": patient_id,
                        "P_Name": name,
                        "P_Age": age,
                        "P_Gender": gender,
                        "Blood_Group": blood_group,
                        "is_active": 1,
                    }},
                    upsert=True
                )
                stats["patients"] += 1

    # 2. Doctors
    doctors_file = data_dir / "doctors.csv"
    if doctors_file.exists():
        with open(doctors_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_raw_id = row.get("doctor_id", "").strip()
                if not d_raw_id:
                    continue
                doctor_id = int(d_raw_id.replace("D", "").lstrip("0") or "0")
                max_d_id = max(max_d_id, doctor_id)
                first = row.get("first_name", "").strip()
                last = row.get("last_name", "").strip()
                name = f"Dr. {first} {last}".strip()

                spec = row.get("specialization", "General Medicine").strip()
                qual = f"MD {spec}"
                exp = int(row.get("years_experience", 5))
                phone = row.get("phone_number", "555-0100").strip()

                db.doctors.update_one(
                    {"Doctor_ID": doctor_id},
                    {"$set": {
                        "Doctor_ID": doctor_id,
                        "D_Name": name,
                        "D_Qualification": qual,
                        "Experience": exp,
                        "D_Phone": phone,
                        "is_active": 1,
                    }},
                    upsert=True
                )
                stats["doctors"] += 1

    # 3. Appointments
    appts_file = data_dir / "appointments.csv"
    if appts_file.exists():
        with open(appts_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                a_raw_id = row.get("appointment_id", "").strip()
                if not a_raw_id:
                    continue
                appt_id = int(a_raw_id.replace("A", "").lstrip("0") or "0")
                max_a_id = max(max_a_id, appt_id)
                p_id = int(row.get("patient_id", "P1").replace("P", "").lstrip("0") or "1")
                d_id = int(row.get("doctor_id", "D1").replace("D", "").lstrip("0") or "1")
                a_date = row.get("appointment_date", "").strip()
                raw_time = row.get("appointment_time", "09:00").strip()
                a_time = raw_time[:5] if len(raw_time) >= 5 else "09:00"
                reason = row.get("reason_for_visit", "Consultation").strip()

                raw_status = row.get("status", "Scheduled").strip()
                if raw_status.lower() in ("no-show", "noshow"):
                    status = "Cancelled"
                elif raw_status in ("Scheduled", "Completed", "Cancelled"):
                    status = raw_status
                else:
                    status = "Scheduled"

                db.appointments.update_one(
                    {"Appointment_ID": appt_id},
                    {"$set": {
                        "Appointment_ID": appt_id,
                        "Patient_id": p_id,
                        "Doctor_ID": d_id,
                        "A_Date": a_date,
                        "A_Time": a_time,
                        "Reason": reason,
                        "Duration_Min": 30,
                        "Status": status,
                    }},
                    upsert=True
                )
                stats["appointments"] += 1

    # 4. Treatments
    treatments_file = data_dir / "treatments.csv"
    if treatments_file.exists():
        with open(treatments_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                t_raw_id = row.get("treatment_id", "").strip()
                if not t_raw_id:
                    continue
                t_id = int(t_raw_id.replace("T", "").lstrip("0") or "0")
                max_t_id = max(max_t_id, t_id)
                a_id = int(row.get("appointment_id", "A1").replace("A", "").lstrip("0") or "1")
                t_type = row.get("treatment_type", "General").strip()
                desc = row.get("description", "").strip()
                cost = float(row.get("cost", 0.0))
                t_date = row.get("treatment_date", "").strip()

                db.treatments.update_one(
                    {"Treatment_ID": t_id},
                    {"$set": {
                        "Treatment_ID": t_id,
                        "Appointment_ID": a_id,
                        "Treatment_Type": t_type,
                        "Description": desc,
                        "Cost": cost,
                        "Treatment_Date": t_date,
                    }},
                    upsert=True
                )
                stats["treatments"] += 1

    # 5. Billing
    billing_file = data_dir / "billing.csv"
    if billing_file.exists():
        with open(billing_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                b_raw_id = row.get("bill_id", "").strip()
                if not b_raw_id:
                    continue
                bill_id = int(b_raw_id.replace("B", "").lstrip("0") or "0")
                max_b_id = max(max_b_id, bill_id)
                p_id = int(row.get("patient_id", "P1").replace("P", "").lstrip("0") or "1")
                b_date = row.get("bill_date", "").strip()
                amount = float(row.get("amount", 100.0))
                raw_pay = row.get("payment_method", "Cash").strip()
                pay_mode = PAYMENT_MODE_MAP.get(raw_pay, "Cash")

                db.bills.update_one(
                    {"Bill_ID": bill_id},
                    {"$set": {
                        "Bill_ID": bill_id,
                        "Patient_id": p_id,
                        "B_Date": b_date,
                        "B_Amount": amount,
                        "Pay_Mode": pay_mode,
                    }},
                    upsert=True
                )
                stats["bills"] += 1

    # 6. Synchronize ID Counters
    db.counters.update_one({"_id": "Patient_id"}, {"$max": {"seq": max_p_id}}, upsert=True)
    db.counters.update_one({"_id": "Doctor_ID"}, {"$max": {"seq": max_d_id}}, upsert=True)
    db.counters.update_one({"_id": "Appointment_ID"}, {"$max": {"seq": max_a_id}}, upsert=True)
    db.counters.update_one({"_id": "Treatment_ID"}, {"$max": {"seq": max_t_id}}, upsert=True)
    db.counters.update_one({"_id": "Bill_ID"}, {"$max": {"seq": max_b_id}}, upsert=True)

    # 7. Ensure Default Administrator
    admin = db.users.find_one({"Username": "admin"})
    if not admin:
        db.users.insert_one({
            "User_ID": 1,
            "Username": "admin",
            "Password_Hash": generate_password_hash("Admin@123"),
            "Role": "Admin",
            "Full_Name": "System Administrator",
            "Email": "admin@hospital.local",
        })
        db.counters.update_one({"_id": "User_ID"}, {"$max": {"seq": 1}}, upsert=True)
        stats["admin_created"] = True

    return stats
