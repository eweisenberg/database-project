import json
import mysql.connector
from datetime import date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from routes.utils import role_required, render_placeholder

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")

def format_short_doctor(first, last):
    initial = f"{first[0]}." if first else ""
    return f"Dr. {initial} {last}".strip()

def format_time(t):
    if not t:
        return ""
    if isinstance(t, str):
        try:
            parts = t.split(":")
            h = int(parts[0])
            m = int(parts[1])
            period = "AM" if h < 12 else "PM"
            dh = h % 12
            if dh == 0:
                dh = 12
            return f"{dh}:{m:02d} {period}"
        except Exception:
            return t
    if isinstance(t, timedelta):
        total_seconds = int(t.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        period = "AM" if hours < 12 else "PM"
        display_hours = hours % 12
        if display_hours == 0:
            display_hours = 12
        return f"{display_hours}:{minutes:02d} {period}"
    if isinstance(t, time):
        return t.strftime("%I:%M %p").lstrip("0")
    return str(t)

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
            "time_display": format_time(nxt["time"]),
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
            "time": format_time(a["time"]),
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

@patient_bp.route("/book", methods=["GET", "POST"])
@role_required("patient")
def book():
    patient_id = session.get("user_id")

    if request.method == "POST":
        office_id = request.form.get("office_id")
        doctor_id = request.form.get("doctor_id")
        service_id = request.form.get("service_id")
        appt_date = request.form.get("date")
        appt_time = request.form.get("time")
        reason = request.form.get("reason", "").strip()

        if not all([office_id, doctor_id, service_id, appt_date, appt_time]):
            flash("Please select an office, provider, visit type, date, and time slot.", "danger")
            return redirect(url_for("patient.book", office_id=office_id, doctor_id=doctor_id))

        try:
            conn = get_db_connection("patient")
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO Appointment (date, time, reason, status, patient_id, service_id, doctor_id, office_id)
                VALUES (%s, %s, %s, 'scheduled', %s, %s, %s, %s)
                """,
                (appt_date, appt_time, reason, patient_id, service_id, doctor_id, office_id)
            )
            conn.commit()
            cursor.close()
            conn.close()

            flash("Appointment successfully scheduled!", "success")
            return redirect(url_for("patient.dashboard"))

        except mysql.connector.Error as err:
            # Trigger prevent_past_appointments raises SQLSTATE 45000 / errno 1644
            if err.errno == 1644 or getattr(err, "sqlstate", None) == "45000":
                flash(f"Cannot book appointment: {err.msg}", "danger")
            elif err.errno == 1062:
                flash("This time slot is already booked for this provider. Please select another slot.", "danger")
            else:
                flash(f"Database error: {err.msg}", "danger")
            return redirect(url_for("patient.book", office_id=office_id, doctor_id=doctor_id))
        except Exception as e:
            flash(f"An unexpected error occurred: {str(e)}", "danger")
            return redirect(url_for("patient.book", office_id=office_id, doctor_id=doctor_id))

    # GET request: load offices, doctors with WorksAt, and service types
    selected_doctor_id = request.args.get("doctor_id", type=int)
    selected_office_id = request.args.get("office_id", type=int)

    offices = []
    doctors = []
    service_types = []

    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT o.office_id, o.street_address, z.city, z.state
            FROM Office o
            JOIN ZipCode z ON o.zip_code = z.zip_code
            ORDER BY z.city ASC, o.street_address ASC
            """
        )
        offices = cursor.fetchall()

        cursor.execute(
            """
            SELECT d.doctor_id, d.first_name, d.last_name, d.practice, w.office_id
            FROM Doctor d
            JOIN WorksAt w ON d.doctor_id = w.doctor_id
            ORDER BY d.last_name ASC, d.first_name ASC
            """
        )
        raw_doctors = cursor.fetchall()
        for doc in raw_doctors:
            doctors.append({
                "doctor_id": doc["doctor_id"],
                "name_display": format_short_doctor(doc["first_name"], doc["last_name"]),
                "practice": doc.get("practice") or "General Practice",
                "office_id": doc["office_id"]
            })

        cursor.execute(
            """
            SELECT service_id, type, recall_interval
            FROM ServiceType
            ORDER BY type ASC
            """
        )
        service_types = cursor.fetchall()

        # If doctor selected without office, auto-assign first matching office
        if selected_doctor_id and not selected_office_id:
            for d in doctors:
                if d["doctor_id"] == selected_doctor_id:
                    selected_office_id = d["office_id"]
                    break

        cursor.close()
        conn.close()

    except Exception as e:
        flash(f"Error loading booking form: {str(e)}", "danger")

    return render_template(
        "patient/book.html",
        offices=offices,
        doctors=doctors,
        service_types=service_types,
        selected_doctor_id=selected_doctor_id,
        selected_office_id=selected_office_id
    )

@patient_bp.route("/api/booked-slots")
@role_required("patient")
def booked_slots():
    doctor_id = request.args.get("doctor_id")
    date_str = request.args.get("date")

    if not doctor_id or not date_str:
        return {"booked_times": []}

    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT time FROM Appointment
            WHERE doctor_id = %s AND date = %s AND status != 'cancelled'
            """,
            (doctor_id, date_str)
        )
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        booked = []
        for r in rows:
            t = r["time"]
            if isinstance(t, timedelta):
                total_seconds = int(t.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                booked.append(f"{hours:02d}:{minutes:02d}:00")
            elif isinstance(t, time):
                booked.append(t.strftime("%H:%M:%S"))
            elif isinstance(t, str):
                booked.append(t if len(t) == 8 else f"{t[:5]}:00")
        return {"booked_times": booked}
    except Exception as e:
        return {"booked_times": [], "error": str(e)}

@patient_bp.route("/appointments")
@role_required("patient")
def appointments():
    patient_id = session.get("user_id")
    filter_type = request.args.get("filter", "all").lower()
    sort_dir = request.args.get("sort", "desc").lower()

    if filter_type not in ("all", "upcoming", "past"):
        filter_type = "all"
    if sort_dir not in ("asc", "desc"):
        sort_dir = "desc"

    order_sql = f"ORDER BY a.date {sort_dir.upper()}, a.time {sort_dir.upper()}"

    formatted_appointments = []
    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor(dictionary=True)

        if filter_type == "upcoming":
            query = f"""
                SELECT a.appointment_id, a.date, a.time, a.reason, a.status,
                       d.first_name AS doctor_first, d.last_name AS doctor_last, d.doctor_id,
                       o.street_address, o.office_id
                FROM Appointment a
                JOIN Doctor d ON a.doctor_id = d.doctor_id
                JOIN Office o ON a.office_id = o.office_id
                WHERE a.patient_id = %s AND a.status = 'scheduled' AND a.date >= CURRENT_DATE
                {order_sql}
            """
        elif filter_type == "past":
            query = f"""
                SELECT a.appointment_id, a.date, a.time, a.reason, a.status,
                       d.first_name AS doctor_first, d.last_name AS doctor_last, d.doctor_id,
                       o.street_address, o.office_id
                FROM Appointment a
                JOIN Doctor d ON a.doctor_id = d.doctor_id
                JOIN Office o ON a.office_id = o.office_id
                WHERE a.patient_id = %s AND (a.status IN ('attended', 'no-show', 'cancelled') OR a.date < CURRENT_DATE)
                {order_sql}
            """
        else:
            query = f"""
                SELECT a.appointment_id, a.date, a.time, a.reason, a.status,
                       d.first_name AS doctor_first, d.last_name AS doctor_last, d.doctor_id,
                       o.street_address, o.office_id
                FROM Appointment a
                JOIN Doctor d ON a.doctor_id = d.doctor_id
                JOIN Office o ON a.office_id = o.office_id
                WHERE a.patient_id = %s
                {order_sql}
            """

        cursor.execute(query, (patient_id,))
        raw_rows = cursor.fetchall()
        cursor.close()
        conn.close()

        today_val = date.today()
        for r in raw_rows:
            r_date = r["date"]
            date_display = r_date.strftime("%b %d, %Y") if hasattr(r_date, "strftime") else str(r_date)
            time_display = format_time(r["time"])
            raw_time_str = r["time"].strftime("%H:%M:%S") if hasattr(r["time"], "strftime") else str(r["time"])
            doc_display = format_short_doctor(r["doctor_first"], r["doctor_last"])

            is_future_or_today = (r_date >= today_val) if hasattr(r_date, "year") else True
            can_modify = (r["status"] == "scheduled" and is_future_or_today)

            formatted_appointments.append({
                "id": r["appointment_id"],
                "doctor_id": r["doctor_id"],
                "doctor": doc_display,
                "reason": r.get("reason") or "General Consultation",
                "status": r["status"],
                "date_display": date_display,
                "time_display": time_display,
                "raw_date": to_iso_date(r_date),
                "raw_time": time_display,
                "can_modify": can_modify
            })

    except Exception as e:
        flash(f"Error loading appointments: {str(e)}", "danger")

    return render_template(
        "patient/appointments.html",
        appointments=formatted_appointments,
        current_filter=filter_type,
        current_sort=sort_dir
    )

@patient_bp.route("/appointments/reschedule", methods=["POST"])
@role_required("patient")
def reschedule_appointment():
    patient_id = session.get("user_id")
    appointment_id = request.form.get("appointment_id")
    new_date = request.form.get("date")
    new_time = request.form.get("time")

    if not appointment_id or not new_date or not new_time:
        flash("Please select both a new date and time slot.", "danger")
        return redirect(url_for("patient.appointments"))

    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor()

        # Milestone 2 UPDATE query
        cursor.execute(
            """
            UPDATE Appointment
            SET date = %s, time = %s, status = 'scheduled'
            WHERE appointment_id = %s AND patient_id = %s
            """,
            (new_date, new_time, appointment_id, patient_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        flash("Appointment successfully rescheduled!", "success")
    except mysql.connector.Error as err:
        if err.errno == 1644 or getattr(err, "sqlstate", None) == "45000":
            flash(f"Cannot reschedule: {err.msg}", "danger")
        elif err.errno == 1062:
            flash("This time slot is already booked for this provider. Please select another slot.", "danger")
        else:
            flash(f"Database error: {err.msg}", "danger")
    except Exception as e:
        flash(f"An unexpected error occurred: {str(e)}", "danger")

    return redirect(url_for("patient.appointments"))

@patient_bp.route("/appointments/cancel", methods=["POST"])
@role_required("patient")
def cancel_appointment():
    patient_id = session.get("user_id")
    appointment_id = request.form.get("appointment_id")

    if not appointment_id:
        flash("Invalid cancellation request.", "danger")
        return redirect(url_for("patient.appointments"))

    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor()

        # Milestone 2 DELETE query
        cursor.execute(
            """
            DELETE FROM Appointment
            WHERE appointment_id = %s AND patient_id = %s
            """,
            (appointment_id, patient_id)
        )
        conn.commit()
        cursor.close()
        conn.close()

        flash("Appointment cancelled and removed from your schedule.", "info")
    except mysql.connector.Error as err:
        flash(f"Database error: {err.msg}", "danger")
    except Exception as e:
        flash(f"An unexpected error occurred: {str(e)}", "danger")

    return redirect(url_for("patient.appointments"))

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
