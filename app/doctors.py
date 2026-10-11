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
)
from app.auth import login_required
from app.db import get_db, get_next_sequence_value
from app.validators import validate_doctor

bp = Blueprint("doctors", __name__, url_prefix="/doctors")


@bp.route("/")
@login_required
def index():
    """List all doctors with search (by Name, Qualification, or ID) and status filtering."""
    db = get_db()
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "all").strip().lower()

    query = {}

    if search:
        regex = {"$regex": re.escape(search), "$options": "i"}
        if search.isdigit():
            query["$or"] = [
                {"Doctor_ID": int(search)},
                {"D_Name": regex},
                {"D_Qualification": regex},
            ]
        else:
            query["$or"] = [
                {"D_Name": regex},
                {"D_Qualification": regex},
            ]

    if status_filter == "active":
        query["is_active"] = 1
    elif status_filter == "inactive":
        query["is_active"] = 0

    doctors = list(db.doctors.find(query).sort("Doctor_ID", -1))

    total_count = db.doctors.count_documents({})
    active_count = db.doctors.count_documents({"is_active": 1})
    inactive_count = total_count - active_count

    return render_template(
        "doctors/index.html",
        doctors=doctors,
        search=search,
        status_filter=status_filter,
        active_count=active_count,
        inactive_count=inactive_count,
        total_count=total_count,
    )


@bp.route("/create", methods=("GET", "POST"))
@login_required
def create():
    """Register a new doctor."""
    if request.method == "POST":
        name = request.form.get("name")
        qualification = request.form.get("qualification")
        experience_str = request.form.get("experience")
        phone = request.form.get("phone")

        errors, cleaned_data = validate_doctor(name, qualification, experience_str, phone)

        db = get_db()
        if not errors:
            existing = db.doctors.find_one({"D_Phone": cleaned_data["D_Phone"]})
            if existing:
                errors.append(f"Phone number is already associated with Dr. {existing['D_Name']} (ID: #{existing['Doctor_ID']}).")

        if not errors:
            try:
                new_doctor_id = get_next_sequence_value(db, "Doctor_ID")
                db.doctors.insert_one({
                    "Doctor_ID": new_doctor_id,
                    "D_Name": cleaned_data["D_Name"],
                    "D_Qualification": cleaned_data["D_Qualification"],
                    "Experience": cleaned_data["Experience"],
                    "D_Phone": cleaned_data["D_Phone"],
                    "is_active": 1,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                flash(f"Doctor '{cleaned_data['D_Name']}' (ID: #{new_doctor_id}) registered successfully.", "success")
                return redirect(url_for("doctors.detail", doctor_id=new_doctor_id))
            except Exception as e:
                flash(f"Database error registering doctor: {e}", "danger")
        else:
            for error in errors:
                flash(error, "danger")

    return render_template("doctors/create.html")


@bp.route("/<int:doctor_id>")
@login_required
def detail(doctor_id):
    """View doctor profile details and their assigned clinical appointments."""
    db = get_db()
    doctor = db.doctors.find_one({"Doctor_ID": doctor_id})
    if doctor is None:
        flash(f"Doctor #{doctor_id} was not found.", "warning")
        return redirect(url_for("doctors.index"))

    raw_appts = list(db.appointments.find({"Doctor_ID": doctor_id}).sort([("A_Date", -1), ("A_Time", -1)]))
    appointments = []
    for a in raw_appts:
        patient = db.patients.find_one({"Patient_id": a.get("Patient_id")}) or {}
        a_copy = dict(a)
        a_copy["Patient_Name"] = patient.get("P_Name", "Unknown Patient")
        a_copy["Blood_Group"] = patient.get("Blood_Group", "-")
        appointments.append(a_copy)

    scheduled_count = sum(1 for a in appointments if a.get("Status") == "Scheduled")
    completed_count = sum(1 for a in appointments if a.get("Status") == "Completed")

    return render_template(
        "doctors/detail.html",
        doctor=doctor,
        appointments=appointments,
        scheduled_count=scheduled_count,
        completed_count=completed_count,
    )


@bp.route("/<int:doctor_id>/edit", methods=("GET", "POST"))
@login_required
def edit(doctor_id):
    """Edit doctor information."""
    db = get_db()
    doctor = db.doctors.find_one({"Doctor_ID": doctor_id})
    if doctor is None:
        flash(f"Doctor #{doctor_id} was not found.", "warning")
        return redirect(url_for("doctors.index"))

    if request.method == "POST":
        name = request.form.get("name")
        qualification = request.form.get("qualification")
        experience_str = request.form.get("experience")
        phone = request.form.get("phone")

        errors, cleaned_data = validate_doctor(name, qualification, experience_str, phone)

        if not errors:
            duplicate = db.doctors.find_one({
                "D_Phone": cleaned_data["D_Phone"],
                "Doctor_ID": {"$ne": doctor_id}
            })
            if duplicate:
                errors.append(f"Phone number is already associated with Dr. {duplicate['D_Name']} (ID: #{duplicate['Doctor_ID']}).")

        if not errors:
            try:
                db.doctors.update_one(
                    {"Doctor_ID": doctor_id},
                    {"$set": {
                        "D_Name": cleaned_data["D_Name"],
                        "D_Qualification": cleaned_data["D_Qualification"],
                        "Experience": cleaned_data["Experience"],
                        "D_Phone": cleaned_data["D_Phone"],
                    }}
                )
                flash(f"Doctor #{doctor_id} updated successfully.", "success")
                return redirect(url_for("doctors.detail", doctor_id=doctor_id))
            except Exception as e:
                flash(f"Database error updating doctor: {e}", "danger")
        else:
            for error in errors:
                flash(error, "danger")

    return render_template("doctors/edit.html", doctor=doctor)


@bp.route("/<int:doctor_id>/toggle-status", methods=("POST",))
@login_required
def toggle_status(doctor_id):
    """Toggle doctor active / inactive on-duty status."""
    db = get_db()
    doctor = db.doctors.find_one({"Doctor_ID": doctor_id})
    if doctor is None:
        flash(f"Doctor #{doctor_id} not found.", "warning")
        return redirect(url_for("doctors.index"))

    current_active = doctor.get("is_active", 1)
    new_status = 0 if current_active == 1 else 1
    db.doctors.update_one({"Doctor_ID": doctor_id}, {"$set": {"is_active": new_status}})

    action = "deactivated (off-duty)" if new_status == 0 else "reactivated (on-duty)"
    flash(f"Doctor '{doctor.get('D_Name')}' has been {action}.", "info")
    return redirect(request.referrer or url_for("doctors.detail", doctor_id=doctor_id))


@bp.route("/<int:doctor_id>/delete", methods=("POST",))
@login_required
def delete(doctor_id):
    """Safely handle doctor deletion. Blocks deletion if doctor has existing appointments."""
    db = get_db()
    doctor = db.doctors.find_one({"Doctor_ID": doctor_id})
    if doctor is None:
        flash(f"Doctor #{doctor_id} not found.", "warning")
        return redirect(url_for("doctors.index"))

    appt_count = db.appointments.count_documents({"Doctor_ID": doctor_id})
    if appt_count > 0:
        flash(
            f"Cannot delete Doctor '{doctor['D_Name']}' (ID: #{doctor_id}): "
            f"This doctor has {appt_count} clinical appointment record(s). "
            f"Please deactivate the doctor instead to preserve historical appointment records.",
            "danger",
        )
        return redirect(url_for("doctors.detail", doctor_id=doctor_id))

    try:
        db.doctors.delete_one({"Doctor_ID": doctor_id})
        flash(f"Doctor record '{doctor['D_Name']}' (ID: #{doctor_id}) was successfully deleted.", "success")
        return redirect(url_for("doctors.index"))
    except Exception as e:
        flash(f"Cannot delete doctor #{doctor_id}: {e}", "danger")
        return redirect(url_for("doctors.detail", doctor_id=doctor_id))
