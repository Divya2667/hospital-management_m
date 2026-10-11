from datetime import date, datetime
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from app.auth import login_required
from app.db import get_db, get_next_sequence_value
from app.validators import ALLOWED_PAYMENT_MODES, validate_bill

bp = Blueprint("billing", __name__, url_prefix="/billing")


@bp.route("/")
@login_required
def index():
    """Listing view of all billing records and invoices with multi-criteria filters,
    search by patient or invoice number, and financial aggregates."""
    db = get_db()

    q = request.args.get("q", "").strip()
    pay_mode = request.args.get("pay_mode", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()

    filter_query = {}
    if pay_mode and pay_mode in ALLOWED_PAYMENT_MODES:
        filter_query["Pay_Mode"] = pay_mode

    if date_from and date_to:
        filter_query["B_Date"] = {"$gte": date_from, "$lte": date_to}
    elif date_from:
        filter_query["B_Date"] = {"$gte": date_from}
    elif date_to:
        filter_query["B_Date"] = {"$lte": date_to}

    raw_bills = list(db.bills.find(filter_query).sort([("B_Date", -1), ("Bill_ID", -1)]))
    patients_map = {p["Patient_id"]: p for p in db.patients.find({})}

    bills = []
    for b in raw_bills:
        p = patients_map.get(b.get("Patient_id"), {})
        b_copy = dict(b)
        b_copy["Patient_Name"] = p.get("P_Name", "Unknown Patient")
        b_copy["Patient_Age"] = p.get("P_Age", "-")
        b_copy["Patient_Gender"] = p.get("P_Gender", "-")
        b_copy["Patient_Blood_Group"] = p.get("Blood_Group", "-")

        if q:
            if q.isdigit() and b_copy.get("Bill_ID") != int(q) and q.lower() not in b_copy["Patient_Name"].lower():
                continue
            elif not q.isdigit() and q.lower() not in b_copy["Patient_Name"].lower():
                continue

        bills.append(b_copy)

    total_revenue = sum(b.get("B_Amount", 0.0) for b in bills)
    total_invoices = len(bills)
    avg_invoice = (total_revenue / total_invoices) if total_invoices > 0 else 0.0

    mode_breakdown = {mode: {"count": 0, "amount": 0.0} for mode in ALLOWED_PAYMENT_MODES}
    for b in bills:
        m = b.get("Pay_Mode")
        if m in mode_breakdown:
            mode_breakdown[m]["count"] += 1
            mode_breakdown[m]["amount"] += b.get("B_Amount", 0.0)

    lifetime_count = db.bills.count_documents({})
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$B_Amount"}}}]
    res = list(db.bills.aggregate(pipeline))
    lifetime_revenue = res[0]["total"] if res else 0.0

    return render_template(
        "billing/index.html",
        bills=bills,
        total_revenue=total_revenue,
        total_invoices=total_invoices,
        avg_invoice=avg_invoice,
        mode_breakdown=mode_breakdown,
        lifetime_count=lifetime_count,
        lifetime_revenue=lifetime_revenue,
        search_query=q,
        current_pay_mode=pay_mode,
        current_date_from=date_from,
        current_date_to=date_to,
        allowed_modes=ALLOWED_PAYMENT_MODES,
    )


@bp.route("/create", methods=["GET", "POST"])
@login_required
def create():
    """Create a new hospital invoice / billing record."""
    db = get_db()
    today_str = date.today().isoformat()
    patients = list(db.patients.find({"is_active": 1}).sort("P_Name", 1))

    if request.method == "POST":
        patient_id_raw = request.form.get("patient_id")
        b_date_raw = request.form.get("b_date")
        b_amount_raw = request.form.get("b_amount")
        pay_mode_raw = request.form.get("pay_mode")

        errors, cleaned = validate_bill(
            patient_id_raw=patient_id_raw,
            date_str=b_date_raw,
            amount_raw=b_amount_raw,
            pay_mode=pay_mode_raw,
            db=db,
        )

        if errors:
            for error in errors:
                flash(error, "danger")
            form_data = {
                "patient_id": patient_id_raw,
                "b_date": b_date_raw,
                "b_amount": b_amount_raw,
                "pay_mode": pay_mode_raw,
            }
            return render_template(
                "billing/create.html",
                patients=patients,
                form_data=form_data,
                allowed_modes=ALLOWED_PAYMENT_MODES,
                today_str=today_str,
            )

        new_bill_id = get_next_sequence_value(db, "Bill_ID")
        db.bills.insert_one({
            "Bill_ID": new_bill_id,
            "Patient_id": cleaned["Patient_id"],
            "B_Date": cleaned["B_Date"],
            "B_Amount": cleaned["B_Amount"],
            "Pay_Mode": cleaned["Pay_Mode"],
            "Created_At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        flash(
            f"Invoice #{new_bill_id} generated successfully for ${cleaned['B_Amount']:.2f}.",
            "success",
        )
        return redirect(url_for("billing.detail", bill_id=new_bill_id))

    preselect_patient_id = request.args.get("patient_id", type=int)
    form_data = {
        "patient_id": preselect_patient_id or "",
        "b_date": today_str,
        "b_amount": "",
        "pay_mode": "Cash",
    }

    return render_template(
        "billing/create.html",
        patients=patients,
        form_data=form_data,
        allowed_modes=ALLOWED_PAYMENT_MODES,
        today_str=today_str,
    )


@bp.route("/<int:bill_id>")
@login_required
def detail(bill_id):
    """Detailed view and printable invoice / receipt for a billing record."""
    db = get_db()
    raw_bill = db.bills.find_one({"Bill_ID": bill_id})
    if not raw_bill:
        abort(404)

    patient = db.patients.find_one({"Patient_id": raw_bill.get("Patient_id")}) or {}
    bill = dict(raw_bill)
    bill["Patient_Name"] = patient.get("P_Name", "Unknown Patient")
    bill["Patient_Age"] = patient.get("P_Age", "-")
    bill["Patient_Gender"] = patient.get("P_Gender", "-")
    bill["Patient_Blood_Group"] = patient.get("Blood_Group", "-")

    raw_appts = list(db.appointments.find({"Patient_id": raw_bill.get("Patient_id")}).sort([("A_Date", -1), ("A_Time", -1)]).limit(3))
    appointments = []
    for a in raw_appts:
        d = db.doctors.find_one({"Doctor_ID": a.get("Doctor_ID")}) or {}
        a_copy = dict(a)
        a_copy["Doctor_Name"] = d.get("D_Name", "Unknown Doctor")
        a_copy["D_Qualification"] = d.get("D_Qualification", "")
        appointments.append(a_copy)

    return render_template(
        "billing/detail.html",
        bill=bill,
        appointments=appointments,
    )


@bp.route("/<int:bill_id>/edit", methods=["GET", "POST"])
@login_required
def edit(bill_id):
    """Edit an existing billing record."""
    db = get_db()
    raw_bill = db.bills.find_one({"Bill_ID": bill_id})
    if not raw_bill:
        abort(404)

    patient = db.patients.find_one({"Patient_id": raw_bill.get("Patient_id")}) or {}
    bill = dict(raw_bill)
    bill["Patient_Name"] = patient.get("P_Name", "Unknown Patient")

    patients = list(db.patients.find({
        "$or": [{"is_active": 1}, {"Patient_id": raw_bill.get("Patient_id")}]
    }).sort("P_Name", 1))

    if request.method == "POST":
        patient_id_raw = request.form.get("patient_id")
        b_date_raw = request.form.get("b_date")
        b_amount_raw = request.form.get("b_amount")
        pay_mode_raw = request.form.get("pay_mode")

        errors, cleaned = validate_bill(
            patient_id_raw=patient_id_raw,
            date_str=b_date_raw,
            amount_raw=b_amount_raw,
            pay_mode=pay_mode_raw,
            db=db,
        )

        if errors:
            for error in errors:
                flash(error, "danger")
            form_data = {
                "patient_id": patient_id_raw,
                "b_date": b_date_raw,
                "b_amount": b_amount_raw,
                "pay_mode": pay_mode_raw,
            }
            return render_template(
                "billing/edit.html",
                bill=bill,
                patients=patients,
                form_data=form_data,
                allowed_modes=ALLOWED_PAYMENT_MODES,
            )

        db.bills.update_one(
            {"Bill_ID": bill_id},
            {"$set": {
                "Patient_id": cleaned["Patient_id"],
                "B_Date": cleaned["B_Date"],
                "B_Amount": cleaned["B_Amount"],
                "Pay_Mode": cleaned["Pay_Mode"],
            }}
        )

        flash(f"Invoice #{bill_id} updated successfully.", "success")
        return redirect(url_for("billing.detail", bill_id=bill_id))

    form_data = {
        "patient_id": bill["Patient_id"],
        "b_date": bill["B_Date"],
        "b_amount": f"{bill['B_Amount']:.2f}",
        "pay_mode": bill["Pay_Mode"],
    }

    return render_template(
        "billing/edit.html",
        bill=bill,
        patients=patients,
        form_data=form_data,
        allowed_modes=ALLOWED_PAYMENT_MODES,
    )


@bp.route("/<int:bill_id>/delete", methods=["POST"])
@login_required
def delete(bill_id):
    """Delete a billing record."""
    db = get_db()
    bill = db.bills.find_one({"Bill_ID": bill_id})
    if not bill:
        abort(404)

    db.bills.delete_one({"Bill_ID": bill_id})
    flash(f"Invoice #{bill_id} (${bill.get('B_Amount', 0.0):.2f}) was permanently deleted.", "info")
    return redirect(url_for("billing.index"))
