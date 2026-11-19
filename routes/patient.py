import json
from datetime import date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from routes.utils import role_required, render_placeholder

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")

def format_short_doctor(first, last):
    initial = f"{first[0]}." if first else ""
    return f"Dr. {initial} {last}".strip()

def to_iso_date(d):
    if not d:
        return ""
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)

@patient_bp.route("/dashboard")
@role_required("patient")
def dashboard():
    patient_id = session.get("user_id")
    first_name = session.get("user_name", "Patient").split()[0]

    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor(dictionary=True)

        # 1. Upcoming scheduled appointment (closest first)
        cursor.execute(
            """
            SELECT a.appointment_id, a.date, a.time, a.reason,
                   d.first_name AS doctor_first, d.last_name AS doctor_last, d.practice,
                   o.street_address, o.office_id
            FROM Appointment a
            JOIN Doctor d ON a.doctor_id = d.doctor_id
            JOIN Office o ON a.office_id = o.office_id
            WHERE a.patient_id = %s AND a.status = 'scheduled' AND a.date >= CURRENT_DATE
            ORDER BY a.date ASC, a.time ASC
            LIMIT 1
            """,
            (patient_id,)
        )
        upcoming_appointments = cursor.fetchall()

        # 2. Recent past visits (newest to oldest)
        cursor.execute(
            """
            SELECT a.appointment_id, a.date, a.time, a.reason AS medical_history, a.status,
                   d.first_name AS doctor_first, d.last_name AS doctor_last
            FROM Appointment a
            JOIN Doctor d ON a.doctor_id = d.doctor_id
            WHERE a.patient_id = %s AND a.status IN ('attended', 'no-show', 'cancelled')
            ORDER BY a.date DESC, a.time DESC
            LIMIT 5
            """,
            (patient_id,)
        )
        recent_visits = cursor.fetchall()

        # 3. All scheduled appointments (for interactive monthly calendar highlighting)
        cursor.execute(
            """
            SELECT a.appointment_id, a.date, a.time, a.reason, a.status,
                   d.first_name AS doctor_first, d.last_name AS doctor_last,
                   o.street_address
            FROM Appointment a
            JOIN Doctor d ON a.doctor_id = d.doctor_id
            JOIN Office o ON a.office_id = o.office_id
            WHERE a.patient_id = %s AND a.status = 'scheduled'
            ORDER BY a.date ASC, a.time ASC
            """,
            (patient_id,)
        )
        all_scheduled = cursor.fetchall()

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f"Error loading dashboard: {str(e)}", "danger")
        upcoming_appointments = []
        recent_visits = []
        all_scheduled = []

    # Process next appointment
    next_appointment = None
    if upcoming_appointments:
        nxt = upcoming_appointments[0]
        appt_date = nxt["date"]
        date_str = appt_date.strftime("%a, %B %d").replace(" 0", " ") if hasattr(appt_date, "strftime") else str(appt_date)
        doc_name = format_short_doctor(nxt["doctor_first"], nxt["doctor_last"])
        clinic_name = nxt.get("practice") or nxt.get("street_address") or "Main Clinic"

        next_appointment = {
            "id": nxt["appointment_id"],
            "date_display": date_str,
            "doctor_clinic": f"{doc_name} - {clinic_name}",
            "reason": nxt["reason"] or "General Consultation"
        }

    # Process recent visits
    formatted_recent_visits = []
    for v in recent_visits:
        v_date = v["date"]
        date_str = v_date.strftime("%b %d, %Y") if hasattr(v_date, "strftime") else str(v_date)
        doc_str = format_short_doctor(v["doctor_first"], v["doctor_last"])

        formatted_recent_visits.append({
            "id": v["appointment_id"],
            "date_display": date_str,
            "doctor": doc_str,
            "reason": v["medical_history"] or "Consultation",
            "status": v["status"]
        })

    # Calendar events dictionary keyed by YYYY-MM-DD
    calendar_events = {}
    for a in all_scheduled:
        date_key = to_iso_date(a["date"])
        if date_key not in calendar_events:
            calendar_events[date_key] = []
        calendar_events[date_key].append({
            "id": a["appointment_id"],
            "doctor": format_short_doctor(a["doctor_first"], a["doctor_last"]),
            "reason": a["reason"] or "Scheduled Visit",
            "office": a["street_address"]
        })

    return render_template(
        "patient/dashboard.html",
        first_name=first_name,
        next_appointment=next_appointment,
        recent_visits=formatted_recent_visits,
        calendar_events_json=json.dumps(calendar_events)
    )

@patient_bp.route("/book")
@role_required("patient")
def book():
    return render_placeholder("Book Appointment")

@patient_bp.route("/appointments")
@role_required("patient")
def appointments():
    return render_placeholder("My Appointments")

@patient_bp.route("/providers")
@role_required("patient")
def providers():
    return render_placeholder("Find a Provider")

@patient_bp.route("/history")
@role_required("patient")
def history():
    return render_placeholder("Medical History")

@patient_bp.route("/profile")
@role_required("patient")
def profile():
    return render_placeholder("My Profile")
