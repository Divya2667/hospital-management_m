import re
from datetime import datetime, date

# Reusable Input Validation Functions

ALLOWED_GENDERS = ["Male", "Female", "Other"]
ALLOWED_BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
ALLOWED_PAYMENT_MODES = ["Cash", "Card", "UPI", "Insurance", "Net Banking"]
ALLOWED_APPOINTMENT_STATUSES = ["Scheduled", "Completed", "Cancelled"]


def time_to_minutes(time_str):
    """Convert HH:MM to total minutes from midnight."""
    try:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError, AttributeError):
        return None


def minutes_to_time(minutes):
    """Convert total minutes from midnight to HH:MM format."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


def check_appointment_overlap(db, doctor_id, date_str, start_min, end_min, exclude_appointment_id=None):
    """Check if the proposed appointment interval overlaps with any non-cancelled appointment
    for the specified doctor on that date.
    
    Returns:
        (has_conflict: bool, conflicting_appointment: dict or None)
    """
    filter_query = {
        "Doctor_ID": int(doctor_id),
        "A_Date": str(date_str),
        "Status": {"$ne": "Cancelled"},
    }
    if exclude_appointment_id is not None:
        filter_query["Appointment_ID"] = {"$ne": int(exclude_appointment_id)}

    existing_appointments = list(db.appointments.find(filter_query))

    for appt in existing_appointments:
        exist_start = time_to_minutes(appt.get("A_Time"))
        if exist_start is None:
            continue
        exist_duration = appt.get("Duration_Min") or 30
        exist_end = exist_start + exist_duration

        # Precise interval overlap condition: [S_new, E_new) overlaps [S_exist, E_exist)
        if start_min < exist_end and end_min > exist_start:
            return True, {
                "Appointment_ID": appt.get("Appointment_ID"),
                "Start_Time": appt.get("A_Time"),
                "End_Time": minutes_to_time(exist_end),
                "Duration_Min": exist_duration,
            }

    return False, None


def validate_patient(name, age_str, gender, blood_group):
    """Validate patient registration and update inputs."""
    errors = []
    cleaned_name = (name or "").strip()
    cleaned_gender = (gender or "").strip()
    cleaned_blood_group = (blood_group or "").strip()
    cleaned_age = None

    if not cleaned_name:
        errors.append("Patient name is required.")
    elif len(cleaned_name) > 100:
        errors.append("Patient name must be under 100 characters.")

    if age_str is None or str(age_str).strip() == "":
        errors.append("Patient age is required.")
    else:
        try:
            cleaned_age = int(age_str)
            if cleaned_age < 0 or cleaned_age > 120:
                errors.append("Patient age must be between 0 and 120.")
        except (ValueError, TypeError):
            errors.append("Age must be a valid whole number.")

    if not cleaned_gender:
        errors.append("Gender is required.")
    elif cleaned_gender not in ALLOWED_GENDERS:
        errors.append(f"Gender must be one of: {', '.join(ALLOWED_GENDERS)}.")

    if not cleaned_blood_group:
        errors.append("Blood group is required.")
    elif cleaned_blood_group not in ALLOWED_BLOOD_GROUPS:
        errors.append(f"Blood group must be one of: {', '.join(ALLOWED_BLOOD_GROUPS)}.")

    cleaned_data = {
        "P_Name": cleaned_name,
        "P_Age": cleaned_age,
        "P_Gender": cleaned_gender,
        "Blood_Group": cleaned_blood_group,
    }

    return errors, cleaned_data


def validate_doctor(name, qualification, experience_str, phone):
    """Validate doctor registration and update inputs."""
    errors = []
    cleaned_name = (name or "").strip()
    cleaned_qualification = (qualification or "").strip()
    cleaned_phone = (phone or "").strip()
    cleaned_experience = None

    if not cleaned_name:
        errors.append("Doctor name is required.")
    elif len(cleaned_name) > 100:
        errors.append("Doctor name must be under 100 characters.")

    if not cleaned_qualification:
        errors.append("Doctor qualification is required.")
    elif len(cleaned_qualification) > 150:
        errors.append("Qualification must be under 150 characters.")

    if experience_str is None or str(experience_str).strip() == "":
        errors.append("Experience in years is required.")
    else:
        try:
            cleaned_experience = int(experience_str)
            if cleaned_experience < 0:
                errors.append("Experience cannot be negative.")
            elif cleaned_experience > 75:
                errors.append("Experience must be a realistic number (0 to 75 years).")
        except (ValueError, TypeError):
            errors.append("Experience must be a valid whole number.")

    if not cleaned_phone:
        errors.append("Phone number is required.")
    else:
        digits_only = re.sub(r"\D", "", cleaned_phone)
        if len(digits_only) < 7 or len(digits_only) > 15:
            errors.append("Phone number must contain between 7 and 15 digits.")

    cleaned_data = {
        "D_Name": cleaned_name,
        "D_Qualification": cleaned_qualification,
        "Experience": cleaned_experience,
        "D_Phone": cleaned_phone,
    }

    return errors, cleaned_data


def validate_bill(patient_id_raw, date_str, amount_raw, pay_mode, db=None):
    """Validate patient bill creation and update inputs.
    
    Returns:
        (errors: list, cleaned_data: dict)
    """
    errors = []
    cleaned_patient_id = None
    cleaned_amount = None
    cleaned_date = (date_str or "").strip()
    cleaned_pay_mode = (pay_mode or "").strip()

    # Patient verification
    if not patient_id_raw or not str(patient_id_raw).isdigit():
        errors.append("Please select a valid patient.")
    else:
        cleaned_patient_id = int(patient_id_raw)
        if db is not None:
            patient_exists = db.patients.find_one({"Patient_id": cleaned_patient_id})
            if not patient_exists:
                errors.append("The selected patient does not exist in the database.")

    # Date verification
    if not cleaned_date:
        errors.append("Bill date is required.")
    else:
        try:
            datetime.strptime(cleaned_date, "%Y-%m-%d")
        except ValueError:
            errors.append("Bill date must be in valid YYYY-MM-DD format.")

    # Amount verification
    if amount_raw is None or str(amount_raw).strip() == "":
        errors.append("Bill amount is required.")
    else:
        try:
            cleaned_amount = round(float(amount_raw), 2)
            if cleaned_amount <= 0:
                errors.append("Bill amount must be greater than zero.")
        except (ValueError, TypeError):
            errors.append("Bill amount must be a valid positive number.")

    # Payment Mode verification
    if not cleaned_pay_mode:
        errors.append("Payment mode is required.")
    elif cleaned_pay_mode not in ALLOWED_PAYMENT_MODES:
        errors.append(f"Payment mode must be one of: {', '.join(ALLOWED_PAYMENT_MODES)}.")

    cleaned_data = {
        "Patient_id": cleaned_patient_id,
        "B_Date": cleaned_date,
        "B_Amount": cleaned_amount,
        "Pay_Mode": cleaned_pay_mode,
    }

    return errors, cleaned_data

