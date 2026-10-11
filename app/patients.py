import re
from datetime import datetime
from flask import (
    Blueprint,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
    abort,
)
from app.auth import login_required
from app.db import get_db, get_next_sequence_value
from app.validators import (
    validate_patient,
    ALLOWED_GENDERS,
    ALLOWED_BLOOD_GROUPS,
)

bp = Blueprint("patients", __name__, url_prefix="/patients")


@bp.route("/")
@login_required
def index():
    """List patients with search and status filtering."""
    db = get_db()
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "all").strip().lower()

    query = {}

    if search:
        if search.isdigit():
            query["$or"] = [
                {"Patient_id": int(search)},
                {"P_Name": {"$regex": re.escape(search), "$options": "i"}}
            ]
        else:
            query["P_Name"] = {"$regex": re.escape(search), "$options": "i"}

    if status_filter == "active":
        query["is_active"] = 1
    elif status_filter == "inactive":
        query["is_active"] = 0

    patients = list(db.patients.find(query).sort("Patient_id", -1))

    total_count = db.patients.count_documents({})
    active_count = db.patients.count_documents({"is_active": 1})
    inactive_count = total_count - active_count

    return render_template(
        "patients/index.html",
        patients=patients,
        search=search,
        status_filter=status_filter,
        active_count=active_count,
        inactive_count=inactive_count,
        total_count=total_count,
    )


@bp.route("/create", methods=("GET", "POST"))
@login_required
def create():
    """Register a new patient."""
    if request.method == "POST":
        name = request.form.get("name")
        age_str = request.form.get("age")
        gender = request.form.get("gender")
        blood_group = request.form.get("blood_group")

        errors, cleaned_data = validate_patient(name, age_str, gender, blood_group)

        if not errors:
            db = get_db()
            try:
                new_patient_id = get_next_sequence_value(db, "Patient_id")
                db.patients.insert_one({
                    "Patient_id": new_patient_id,
                    "P_Name": cleaned_data["P_Name"],
                    "P_Age": cleaned_data["P_Age"],
                    "P_Gender": cleaned_data["P_Gender"],
                    "Blood_Group": cleaned_data["Blood_Group"],
                    "is_active": 1,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                flash(f"Patient '{cleaned_data['P_Name']}' (ID: #{new_patient_id}) registered successfully.", "success")
                return redirect(url_for("patients.detail", patient_id=new_patient_id))
            except Exception as e:
                flash(f"Database error registering patient: {e}", "danger")
        else:
            for error in errors:
                flash(error, "danger")

    return render_template(
        "patients/create.html",
        allowed_genders=ALLOWED_GENDERS,
        allowed_blood_groups=ALLOWED_BLOOD_GROUPS,
    )


@bp.route("/<int:patient_id>")
@login_required
def detail(patient_id):
    """View patient details, complete appointment history, and billing history."""
    db = get_db()
    patient = db.patients.find_one({"Patient_id": patient_id})
    if patient is None:
        flash(f"Patient #{patient_id} was not found.", "warning")
        return redirect(url_for("patients.index"))

    # Patient's appointment history with assigned Doctor details
    raw_appts = list(db.appointments.find({"Patient_id": patient_id}).sort([("A_Date", -1), ("A_Time", -1)]))
    appointments = []
    for a in raw_appts:
        doc = db.doctors.find_one({"Doctor_ID": a.get("Doctor_ID")}) or {}
        a_copy = dict(a)
        a_copy["Doctor_Name"] = doc.get("D_Name", "Unknown Doctor")
        a_copy["D_Qualification"] = doc.get("D_Qualification", "")
        appointments.append(a_copy)

    # Patient's billing history
    bills = list(db.bills.find({"Patient_id": patient_id}).sort("Bill_ID", -1))
    total_billed = sum(bill.get("B_Amount", 0.0) for bill in bills)

    return render_template(
        "patients/detail.html",
        patient=patient,
        appointments=appointments,
        bills=bills,
        total_billed=total_billed,
    )


@bp.route("/<int:patient_id>/edit", methods=("GET", "POST"))
@login_required
def edit(patient_id):
    """Edit patient information."""
    db = get_db()
    patient = db.patients.find_one({"Patient_id": patient_id})
    if patient is None:
        flash(f"Patient #{patient_id} was not found.", "warning")
        return redirect(url_for("patients.index"))

    if request.method == "POST":
        name = request.form.get("name")
        age_str = request.form.get("age")
        gender = request.form.get("gender")
        blood_group = request.form.get("blood_group")

        errors, cleaned_data = validate_patient(name, age_str, gender, blood_group)

        if not errors:
            try:
                db.patients.update_one(
                    {"Patient_id": patient_id},
                    {"$set": {
                        "P_Name": cleaned_data["P_Name"],
                        "P_Age": cleaned_data["P_Age"],
                        "P_Gender": cleaned_data["P_Gender"],
                        "Blood_Group": cleaned_data["Blood_Group"],
                    }}
                )
                flash(f"Patient #{patient_id} updated successfully.", "success")
                return redirect(url_for("patients.detail", patient_id=patient_id))
            except Exception as e:
                flash(f"Database error updating patient: {e}", "danger")
        else:
            for error in errors:
                flash(error, "danger")

    return render_template(
        "patients/edit.html",
        patient=patient,
        allowed_genders=ALLOWED_GENDERS,
        allowed_blood_groups=ALLOWED_BLOOD_GROUPS,
    )


@bp.route("/<int:patient_id>/toggle-status", methods=("POST",))
@login_required
def toggle_status(patient_id):
    """Toggle patient active / inactive status safely without destroying history."""
    db = get_db()
    patient = db.patients.find_one({"Patient_id": patient_id})
    if patient is None:
        flash(f"Patient #{patient_id} not found.", "warning")
        return redirect(url_for("patients.index"))

    current_active = patient.get("is_active", 1)
    new_status = 0 if current_active == 1 else 1
    db.patients.update_one({"Patient_id": patient_id}, {"$set": {"is_active": new_status}})

    action = "deactivated" if new_status == 0 else "reactivated"
    flash(f"Patient '{patient.get('P_Name')}' has been {action}.", "info")
    return redirect(request.referrer or url_for("patients.detail", patient_id=patient_id))


@bp.route("/<int:patient_id>/delete", methods=("POST",))
@login_required
def delete(patient_id):
    """Safely handle deletion attempts. Blocks deletion if patient has appointments or bills."""
    db = get_db()
    patient = db.patients.find_one({"Patient_id": patient_id})
    if patient is None:
        flash(f"Patient #{patient_id} not found.", "warning")
        return redirect(url_for("patients.index"))

    appt_count = db.appointments.count_documents({"Patient_id": patient_id})
    bill_count = db.bills.count_documents({"Patient_id": patient_id})

    if appt_count > 0 or bill_count > 0:
        flash(
            f"Cannot delete Patient '{patient['P_Name']}' (ID: #{patient_id}): "
            f"This patient has {appt_count} appointment(s) and {bill_count} billing record(s). "
            f"Please deactivate the patient instead to preserve historical records.",
            "danger",
        )
        return redirect(url_for("patients.detail", patient_id=patient_id))

    try:
        db.patients.delete_one({"Patient_id": patient_id})
        flash(f"Patient record '{patient['P_Name']}' (ID: #{patient_id}) was successfully deleted.", "success")
        return redirect(url_for("patients.index"))
    except Exception as e:
        flash(f"Cannot delete patient #{patient_id}: {e}", "danger")
        return redirect(url_for("patients.detail", patient_id=patient_id))
