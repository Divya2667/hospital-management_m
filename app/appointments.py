import re
from datetime import datetime, date
from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from app.auth import login_required
from app.db import get_db, get_next_sequence_value
from app.validators import (
    time_to_minutes,
    minutes_to_time,
    check_appointment_overlap,
    ALLOWED_APPOINTMENT_STATUSES,
)

bp = Blueprint("appointments", __name__, url_prefix="/appointments")


@bp.route("/")
@login_required
def index():
    """List appointments with search and multi-criteria filters (Patient, Doctor, Date, Status)."""
    db = get_db()
    search = request.args.get("search", "").strip()
    filter_patient = request.args.get("patient_id", "").strip()
    filter_doctor = request.args.get("doctor_id", "").strip()
    filter_date = request.args.get("date", "").strip()
    filter_status = request.args.get("status", "all").strip()

    filter_query = {}

    if filter_patient and filter_patient.isdigit():
        filter_query["Patient_id"] = int(filter_patient)

    if filter_doctor and filter_doctor.isdigit():
        filter_query["Doctor_ID"] = int(filter_doctor)

    if filter_date:
        filter_query["A_Date"] = filter_date

    if filter_status and filter_status != "all":
        filter_query["Status"] = filter_status

    raw_appointments = list(db.appointments.find(filter_query).sort([("A_Date", -1), ("A_Time", -1)]))

    # Pre-fetch patients and doctors to efficiently map relations
    patients_map = {p["Patient_id"]: p for p in db.patients.find({})}
    doctors_map = {d["Doctor_ID"]: d for d in db.doctors.find({})}

    appointments = []
    for a in raw_appointments:
        p = patients_map.get(a.get("Patient_id"), {})
        d = doctors_map.get(a.get("Doctor_ID"), {})
        a_copy = dict(a)
        a_copy["Patient_Name"] = p.get("P_Name", "Unknown Patient")
        a_copy["Blood_Group"] = p.get("Blood_Group", "-")
        a_copy["Doctor_Name"] = d.get("D_Name", "Unknown Doctor")
        a_copy["D_Qualification"] = d.get("D_Qualification", "")

        # In-memory search filter if search string was provided
        if search:
            search_lower = search.lower()
            reason = str(a_copy.get("Reason", "")).lower()
            p_name = a_copy["Patient_Name"].lower()
            d_name = a_copy["Doctor_Name"].lower()
            if search_lower not in reason and search_lower not in p_name and search_lower not in d_name:
                continue

        appointments.append(a_copy)

    patients = list(db.patients.find({}, {"Patient_id": 1, "P_Name": 1}).sort("P_Name", 1))
    doctors = list(db.doctors.find({}, {"Doctor_ID": 1, "D_Name": 1}).sort("D_Name", 1))

    total_count = db.appointments.count_documents({})
    scheduled_count = db.appointments.count_documents({"Status": "Scheduled"})
    completed_count = db.appointments.count_documents({"Status": "Completed"})
    cancelled_count = db.appointments.count_documents({"Status": "Cancelled"})

    return render_template(
        "appointments/index.html",
        appointments=appointments,
        search=search,
        filter_patient=filter_patient,
        filter_doctor=filter_doctor,
        filter_date=filter_date,
        filter_status=filter_status,
        patients=patients,
        doctors=doctors,
        total_count=total_count,
        scheduled_count=scheduled_count,
        completed_count=completed_count,
        cancelled_count=cancelled_count,
        allowed_statuses=ALLOWED_APPOINTMENT_STATUSES,
    )


@bp.route("/create", methods=("GET", "POST"))
@login_required
def create():
    """Schedule a new appointment with conflict detection and clinic hour enforcement."""
    db = get_db()
    clinic_open = current_app.config.get("CLINIC_OPEN_TIME", "09:00")
    clinic_close = current_app.config.get("CLINIC_CLOSE_TIME", "17:00")
    default_duration = current_app.config.get("DEFAULT_APPOINTMENT_DURATION", 30)

    if request.method == "POST":
        patient_id_raw = request.form.get("patient_id", "").strip()
        doctor_id_raw = request.form.get("doctor_id", "").strip()
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        reason = request.form.get("reason", "").strip()
        duration_raw = request.form.get("duration", str(default_duration)).strip()

        errors = []

        patient = None
        if not patient_id_raw or not patient_id_raw.isdigit():
            errors.append("Please select a valid patient.")
        else:
            patient = db.patients.find_one({"Patient_id": int(patient_id_raw)})
            if not patient:
                errors.append("The selected patient does not exist.")

        doctor = None
        if not doctor_id_raw or not doctor_id_raw.isdigit():
            errors.append("Please select a valid doctor.")
        else:
            doctor = db.doctors.find_one({"Doctor_ID": int(doctor_id_raw)})
            if not doctor:
                errors.append("The selected doctor does not exist.")
            elif doctor.get("is_active") != 1:
                errors.append(f"Dr. {doctor['D_Name']} is currently inactive/off-duty and cannot accept new appointments.")

        if not reason:
            errors.append("Please enter the clinical reason for the appointment.")
        elif len(reason) > 250:
            errors.append("Reason must be 250 characters or less.")

        duration = default_duration
        if duration_raw:
            try:
                duration = int(duration_raw)
                if duration <= 0 or duration > 180:
                    errors.append("Duration must be between 5 and 180 minutes.")
            except ValueError:
                errors.append("Duration must be a valid number.")

        if not date_str:
            errors.append("Please select an appointment date.")
        else:
            try:
                appt_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if appt_date < date.today():
                    errors.append("Appointment date cannot be in the past.")
            except ValueError:
                errors.append("Date must be in YYYY-MM-DD format.")

        start_min = time_to_minutes(time_str)
        if start_min is None:
            errors.append("Please enter a valid appointment time in HH:MM format.")
        else:
            open_min = time_to_minutes(clinic_open)
            close_min = time_to_minutes(clinic_close)
            end_min = start_min + duration

            if start_min < open_min:
                errors.append(f"Appointment time ({time_str}) cannot be earlier than clinic opening hours ({clinic_open}).")
            elif end_min > close_min:
                errors.append(
                    f"Appointment ({time_str} to {minutes_to_time(end_min)}) extends beyond clinic closing hours ({clinic_close})."
                )

        if not errors and doctor and start_min is not None:
            has_conflict, conflict = check_appointment_overlap(
                db, int(doctor_id_raw), date_str, start_min, start_min + duration
            )
            if has_conflict:
                doc_title = doctor["D_Name"] if doctor["D_Name"].startswith("Dr.") else f"Dr. {doctor['D_Name']}"
                errors.append(
                    f"Scheduling Conflict: {doc_title} already has an appointment scheduled "
                    f"from {conflict['Start_Time']} to {conflict['End_Time']} on {date_str}. "
                    f"Please choose another time slot or another doctor."
                )

        if not errors:
            try:
                new_appt_id = get_next_sequence_value(db, "Appointment_ID")
                db.appointments.insert_one({
                    "Appointment_ID": new_appt_id,
                    "Patient_id": int(patient_id_raw),
                    "Doctor_ID": int(doctor_id_raw),
                    "A_Date": date_str,
                    "A_Time": time_str,
                    "Reason": reason,
                    "Duration_Min": duration,
                    "Status": "Scheduled",
                    "Created_At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                doc_title = doctor["D_Name"] if doctor["D_Name"].startswith("Dr.") else f"Dr. {doctor['D_Name']}"
                flash(
                    f"Appointment #{new_appt_id} scheduled successfully for {patient['P_Name']} "
                    f"with {doc_title} on {date_str} at {time_str}.",
                    "success",
                )
                return redirect(url_for("appointments.detail", appointment_id=new_appt_id))
            except Exception as e:
                flash(f"Database error creating appointment: {e}", "danger")
        else:
            for error in errors:
                flash(error, "danger")

    active_patients = list(db.patients.find({"is_active": 1}).sort("P_Name", 1))
    active_doctors = list(db.doctors.find({"is_active": 1}).sort("D_Name", 1))

    pre_patient = request.args.get("patient_id", "")
    pre_doctor = request.args.get("doctor_id", "")

    return render_template(
        "appointments/create.html",
        active_patients=active_patients,
        active_doctors=active_doctors,
        pre_patient=pre_patient,
        pre_doctor=pre_doctor,
        clinic_open=clinic_open,
        clinic_close=clinic_close,
        default_duration=default_duration,
    )


@bp.route("/<int:appointment_id>")
@login_required
def detail(appointment_id):
    """View appointment record details, participants, and status management actions."""
    db = get_db()
    raw_appointment = db.appointments.find_one({"Appointment_ID": appointment_id})
    if raw_appointment is None:
        flash(f"Appointment #{appointment_id} not found.", "warning")
        return redirect(url_for("appointments.index"))

    patient = db.patients.find_one({"Patient_id": raw_appointment.get("Patient_id")}) or {}
    doctor = db.doctors.find_one({"Doctor_ID": raw_appointment.get("Doctor_ID")}) or {}

    appointment = dict(raw_appointment)
    appointment["Patient_Name"] = patient.get("P_Name", "Unknown Patient")
    appointment["P_Age"] = patient.get("P_Age", "-")
    appointment["P_Gender"] = patient.get("P_Gender", "-")
    appointment["Blood_Group"] = patient.get("Blood_Group", "-")
    appointment["Doctor_Name"] = doctor.get("D_Name", "Unknown Doctor")
    appointment["D_Qualification"] = doctor.get("D_Qualification", "")
    appointment["Doctor_Phone"] = doctor.get("D_Phone", "")

    start_min = time_to_minutes(appointment.get("A_Time"))
    end_time = minutes_to_time(start_min + appointment.get("Duration_Min", 30)) if start_min else "N/A"

    return render_template(
        "appointments/detail.html",
        appointment=appointment,
        end_time=end_time,
    )


@bp.route("/<int:appointment_id>/edit", methods=("GET", "POST"))
@login_required
def edit(appointment_id):
    """Reschedule or edit appointment details with self-exclusion from conflict check."""
    db = get_db()
    appointment = db.appointments.find_one({"Appointment_ID": appointment_id})
    if appointment is None:
        flash(f"Appointment #{appointment_id} not found.", "warning")
        return redirect(url_for("appointments.index"))

    clinic_open = current_app.config.get("CLINIC_OPEN_TIME", "09:00")
    clinic_close = current_app.config.get("CLINIC_CLOSE_TIME", "17:00")
    default_duration = current_app.config.get("DEFAULT_APPOINTMENT_DURATION", 30)

    if request.method == "POST":
        doctor_id_raw = request.form.get("doctor_id", "").strip()
        date_str = request.form.get("date", "").strip()
        time_str = request.form.get("time", "").strip()
        reason = request.form.get("reason", "").strip()
        duration_raw = request.form.get("duration", str(appointment.get("Duration_Min", default_duration))).strip()
        status = request.form.get("status", appointment.get("Status")).strip()

        errors = []

        doctor = None
        if not doctor_id_raw or not doctor_id_raw.isdigit():
            errors.append("Please select a valid doctor.")
        else:
            doctor = db.doctors.find_one({"Doctor_ID": int(doctor_id_raw)})
            if not doctor:
                errors.append("The selected doctor does not exist.")

        if not reason:
            errors.append("Please enter the clinical reason.")
        elif len(reason) > 250:
            errors.append("Reason must be 250 characters or less.")

        duration = default_duration
        if duration_raw:
            try:
                duration = int(duration_raw)
                if duration <= 0 or duration > 180:
                    errors.append("Duration must be between 5 and 180 minutes.")
            except ValueError:
                errors.append("Duration must be a valid number.")

        if not date_str:
            errors.append("Please select a date.")
        else:
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                errors.append("Date must be in YYYY-MM-DD format.")

        start_min = time_to_minutes(time_str)
        if start_min is None:
            errors.append("Please enter a valid time in HH:MM format.")
        else:
            open_min = time_to_minutes(clinic_open)
            close_min = time_to_minutes(clinic_close)
            end_min = start_min + duration

            if start_min < open_min or end_min > close_min:
                errors.append(f"Appointment must fall within clinic hours ({clinic_open} to {clinic_close}).")

        if not errors and doctor and start_min is not None and status != "Cancelled":
            has_conflict, conflict = check_appointment_overlap(
                db, int(doctor_id_raw), date_str, start_min, start_min + duration, exclude_appointment_id=appointment_id
            )
            if has_conflict:
                doc_title = doctor["D_Name"] if doctor["D_Name"].startswith("Dr.") else f"Dr. {doctor['D_Name']}"
                errors.append(
                    f"Scheduling Conflict: {doc_title} already has an appointment scheduled "
                    f"from {conflict['Start_Time']} to {conflict['End_Time']} on {date_str}."
                )

        if not errors:
            try:
                db.appointments.update_one(
                    {"Appointment_ID": appointment_id},
                    {"$set": {
                        "Doctor_ID": int(doctor_id_raw),
                        "A_Date": date_str,
                        "A_Time": time_str,
                        "Reason": reason,
                        "Duration_Min": duration,
                        "Status": status,
                    }}
                )
                flash(f"Appointment #{appointment_id} updated successfully.", "success")
                return redirect(url_for("appointments.detail", appointment_id=appointment_id))
            except Exception as e:
                flash(f"Database error updating appointment: {e}", "danger")
        else:
            for error in errors:
                flash(error, "danger")

    doctors = list(db.doctors.find({
        "$or": [{"is_active": 1}, {"Doctor_ID": appointment.get("Doctor_ID")}]
    }).sort("D_Name", 1))
    patient = db.patients.find_one({"Patient_id": appointment.get("Patient_id")})

    return render_template(
        "appointments/edit.html",
        appointment=appointment,
        patient=patient,
        doctors=doctors,
        clinic_open=clinic_open,
        clinic_close=clinic_close,
        allowed_statuses=ALLOWED_APPOINTMENT_STATUSES,
    )


@bp.route("/<int:appointment_id>/cancel", methods=("POST",))
@login_required
def cancel(appointment_id):
    """Cancel appointment. Cancelled appointments release the slot for other bookings."""
    db = get_db()
    appt = db.appointments.find_one({"Appointment_ID": appointment_id})
    if not appt:
        flash(f"Appointment #{appointment_id} not found.", "warning")
        return redirect(url_for("appointments.index"))

    db.appointments.update_one({"Appointment_ID": appointment_id}, {"$set": {"Status": "Cancelled"}})
    flash(f"Appointment #{appointment_id} has been cancelled. The time slot is now available for other bookings.", "info")
    return redirect(request.referrer or url_for("appointments.detail", appointment_id=appointment_id))


@bp.route("/<int:appointment_id>/complete", methods=("POST",))
@login_required
def complete(appointment_id):
    """Mark appointment as completed."""
    db = get_db()
    appt = db.appointments.find_one({"Appointment_ID": appointment_id})
    if not appt:
        flash(f"Appointment #{appointment_id} not found.", "warning")
        return redirect(url_for("appointments.index"))

    db.appointments.update_one({"Appointment_ID": appointment_id}, {"$set": {"Status": "Completed"}})
    flash(f"Appointment #{appointment_id} marked as completed.", "success")
    return redirect(request.referrer or url_for("appointments.detail", appointment_id=appointment_id))
