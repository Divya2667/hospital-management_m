from flask import Blueprint, render_template, redirect, url_for, g
from app.auth import login_required
from app.db import get_db

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def root():
    """Application root: always route visitors to authentication portal."""
    return redirect(url_for("auth.login"))


@bp.route("/dashboard")
@login_required
def index():
    """Render the central dashboard with live aggregate metrics and recent records from MongoDB."""
    db = get_db()

    # 1. Patient Metrics
    active_patients_count = db.patients.count_documents({"is_active": 1})
    total_patients_count = db.patients.count_documents({})

    # 2. Doctor Metrics
    active_doctors_count = db.doctors.count_documents({"is_active": 1})

    # 3. Appointment Metrics
    total_appointments_count = db.appointments.count_documents({})
    scheduled_appointments_count = db.appointments.count_documents({"Status": "Scheduled"})

    # 4. Financial Metrics
    total_bills_count = db.bills.count_documents({})
    rev_pipe = [{"$group": {"_id": None, "total": {"$sum": "$B_Amount"}}}]
    rev_res = list(db.bills.aggregate(rev_pipe))
    total_revenue = rev_res[0]["total"] if rev_res else 0.0

    # 5. Recent Appointments with Patient & Doctor details
    raw_recent_appts = list(db.appointments.find({}).sort([("A_Date", -1), ("A_Time", -1)]).limit(5))
    recent_appointments = []
    for a in raw_recent_appts:
        p = db.patients.find_one({"Patient_id": a.get("Patient_id")}) or {}
        d = db.doctors.find_one({"Doctor_ID": a.get("Doctor_ID")}) or {}
        a_copy = dict(a)
        a_copy["Patient_Name"] = p.get("P_Name", "Unknown Patient")
        a_copy["Doctor_Name"] = d.get("D_Name", "Unknown Doctor")
        recent_appointments.append(a_copy)

    # 6. Recent Bills with Patient details
    raw_recent_bills = list(db.bills.find({}).sort("Bill_ID", -1).limit(5))
    recent_bills = []
    for b in raw_recent_bills:
        p = db.patients.find_one({"Patient_id": b.get("Patient_id")}) or {}
        b_copy = dict(b)
        b_copy["Patient_Name"] = p.get("P_Name", "Unknown Patient")
        recent_bills.append(b_copy)

    # 7. Live analytics: Monthly Appointment Volume (12 months)
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    monthly_data = {f"{i:02d}": 0 for i in range(1, 13)}
    for a in db.appointments.find({}, {"A_Date": 1}):
        d_str = a.get("A_Date", "")
        if len(d_str) >= 7 and d_str[4] == "-":
            m = d_str[5:7]
            if m in monthly_data:
                monthly_data[m] += 1
    trend_labels = month_names
    trend_counts = [monthly_data[f"{i:02d}"] for i in range(1, 13)]

    # 8. Live analytics: Settlement breakdown by payment mode
    pay_counts = {}
    for b in db.bills.find({}, {"Pay_Mode": 1}):
        m = b.get("Pay_Mode", "Cash")
        pay_counts[m] = pay_counts.get(m, 0) + 1
    settlement_labels = list(pay_counts.keys())
    settlement_counts = list(pay_counts.values())

    return render_template(
        "dashboard.html",
        active_patients_count=active_patients_count,
        total_patients_count=total_patients_count,
        active_doctors_count=active_doctors_count,
        total_appointments_count=total_appointments_count,
        scheduled_appointments_count=scheduled_appointments_count,
        total_bills_count=total_bills_count,
        total_revenue=total_revenue,
        recent_appointments=recent_appointments,
        recent_bills=recent_bills,
        trend_labels=trend_labels,
        trend_counts=trend_counts,
        settlement_labels=settlement_labels,
        settlement_counts=settlement_counts,
    )
