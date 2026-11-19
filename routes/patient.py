import json
import mysql.connector
from datetime import date, time, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from routes.utils import role_required, render_placeholder

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")

def format_short_doctor(first, last):
    return f"Dr. {first} {last}".strip()

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

def calculate_next_open_date(doctor_id, fully_booked_set):
    check_date = date.today()
    for _ in range(60):
        if check_date.weekday() < 5:  # Weekdays only (Mon-Fri)
            date_key = (doctor_id, check_date.isoformat())
            if date_key not in fully_booked_set:
                return check_date.strftime("%B %d").replace(" 0", " ")
        check_date += timedelta(days=1)
    return "Check Schedule"

@patient_bp.route("/providers")
@role_required("patient")
def providers():
    search_q = request.args.get("q", "").strip()
    office_filter = request.args.get("office_id", "").strip()
    specialty_filter = request.args.get("specialty", "").strip()

    offices = []
    specialties = []
    formatted_providers = []

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

        cursor.execute("SELECT name FROM Specialty ORDER BY name ASC")
        specialties = cursor.fetchall()

        cursor.execute(
            """
            SELECT doctor_id, date
            FROM Appointment
            WHERE date >= CURRENT_DATE AND status != 'cancelled'
            GROUP BY doctor_id, date
            HAVING COUNT(*) >= 14
            """
        )
        booked_rows = cursor.fetchall()
        fully_booked_set = set()
        for br in booked_rows:
            d_val = br["date"]
            d_str = d_val.isoformat() if hasattr(d_val, "isoformat") else str(d_val)
            fully_booked_set.add((br["doctor_id"], d_str))

        where_clauses = ["1=1"]
        params = []

        if search_q:
            where_clauses.append("(d.first_name LIKE %s OR d.last_name LIKE %s OR CONCAT(d.first_name, ' ', d.last_name) LIKE %s)")
            q_like = f"%{search_q}%"
            params.extend([q_like, q_like, q_like])

        if office_filter:
            where_clauses.append("d.doctor_id IN (SELECT doctor_id FROM WorksAt WHERE office_id = %s)")
            params.append(office_filter)

        if specialty_filter:
            where_clauses.append("d.doctor_id IN (SELECT doctor_id FROM SpecializesIn WHERE specialty_name = %s)")
            params.append(specialty_filter)

        where_sql = " AND ".join(where_clauses)

        query = f"""
            SELECT d.doctor_id, d.first_name, d.last_name, d.practice,
                   s.specialty_name,
                   w.office_id, o.street_address, z.city, z.state
            FROM Doctor d
            LEFT JOIN SpecializesIn s ON d.doctor_id = s.doctor_id
            LEFT JOIN WorksAt w ON d.doctor_id = w.doctor_id
            LEFT JOIN Office o ON w.office_id = o.office_id
            LEFT JOIN ZipCode z ON o.zip_code = z.zip_code
            WHERE {where_sql}
            ORDER BY d.last_name ASC, d.first_name ASC
        """
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        cursor.close()
        conn.close()

        # Group by doctor_id so each provider appears exactly once
        doctors_map = {}
        for r in rows:
            did = r["doctor_id"]
            if did not in doctors_map:
                doctors_map[did] = {
                    "doctor_id": did,
                    "first_name": r["first_name"],
                    "last_name": r["last_name"],
                    "practice": r.get("practice"),
                    "specialties": set(),
                    "offices": [],
                    "office_ids": set()
                }

            if r.get("specialty_name"):
                doctors_map[did]["specialties"].add(r["specialty_name"])

            oid = r.get("office_id")
            if oid and oid not in doctors_map[did]["office_ids"]:
                doctors_map[did]["office_ids"].add(oid)
                doctors_map[did]["offices"].append({
                    "office_id": oid,
                    "street_address": r.get("street_address") or "",
                    "city": r.get("city") or "",
                    "state": r.get("state") or ""
                })

        for did, dinfo in doctors_map.items():
            doc_name = format_short_doctor(dinfo["first_name"], dinfo["last_name"])
            specialties_list = sorted(list(dinfo["specialties"]))
            specialty_str = ", ".join(specialties_list) if specialties_list else "General Medicine"
            next_open_str = calculate_next_open_date(did, fully_booked_set)
            primary_office_id = dinfo["offices"][0]["office_id"] if dinfo["offices"] else None

            formatted_providers.append({
                "doctor_id": did,
                "office_id": primary_office_id,
                "name_display": doc_name,
                "specialty_display": specialty_str,
                "practice": dinfo["practice"],
                "offices": dinfo["offices"],
                "next_open": next_open_str
            })

    except Exception as e:
        flash(f"Error loading providers: {str(e)}", "danger")

    return render_template(
        "patient/providers.html",
        providers=formatted_providers,
        offices=offices,
        specialties=specialties,
        current_q=search_q,
        current_office_id=office_filter,
        current_specialty=specialty_filter
    )

@patient_bp.route("/history")
@role_required("patient")
def history():
    patient_id = session.get("user_id")

    visits = []
    messages = []

    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor(dictionary=True)

        # 1. Past attended visits (from catalog query)
        cursor.execute(
            """
            SELECT a.appointment_id, a.date, a.time, a.reason, a.status,
                   a.diagnosis, a.clinical_notes,
                   d.first_name AS doctor_first, d.last_name AS doctor_last,
                   st.type AS service_type
            FROM Appointment a
            JOIN Doctor d ON a.doctor_id = d.doctor_id
            LEFT JOIN ServiceType st ON a.service_id = st.service_id
            WHERE a.patient_id = %s AND a.status = 'attended'
            ORDER BY a.date DESC, a.time DESC
            """,
            (patient_id,)
        )
        raw_visits = cursor.fetchall()

        # 2. Prescriptions for this patient's appointments
        cursor.execute(
            """
            SELECT p.prescription_id, p.medication, p.dosage, p.duration, p.appointment_id
            FROM Prescription p
            JOIN Appointment a ON p.appointment_id = a.appointment_id
            WHERE a.patient_id = %s
            """,
            (patient_id,)
        )
        raw_rx = cursor.fetchall()

        rx_by_appt = {}
        for rx in raw_rx:
            aid = rx["appointment_id"]
            if aid not in rx_by_appt:
                rx_by_appt[aid] = []
            rx_by_appt[aid].append(rx)

        for v in raw_visits:
            v_date = v["date"]
            date_display = v_date.strftime("%b %d, %Y") if hasattr(v_date, "strftime") else str(v_date)
            doc_display = format_short_doctor(v["doctor_first"], v["doctor_last"])
            aid = v["appointment_id"]

            visits.append({
                "id": aid,
                "date_display": date_display,
                "doctor": doc_display,
                "reason": v.get("reason"),
                "service_type": v.get("service_type"),
                "diagnosis": v.get("diagnosis"),
                "clinical_notes": v.get("clinical_notes"),
                "prescriptions": rx_by_appt.get(aid, [])
            })

        # 3. Outreach messages sent to this patient (from catalog query)
        cursor.execute(
            """
            SELECT m.date, m.time, m.template, s.first_name AS staff_first, s.last_name AS staff_last
            FROM Message m
            JOIN Receives r ON m.message_id = r.message_id
            JOIN Staff s ON m.staff_id = s.staff_id
            WHERE r.patient_id = %s
            ORDER BY m.date DESC, m.time DESC
            """,
            (patient_id,)
        )
        raw_messages = cursor.fetchall()

        cursor.close()
        conn.close()

        for m in raw_messages:
            m_date = m["date"]
            date_disp = m_date.strftime("%b %d, %Y") if hasattr(m_date, "strftime") else str(m_date)
            time_disp = format_time(m["time"])
            staff_last = m.get("staff_last") or ""
            staff_name = f"{m['staff_first']} {staff_last}".strip() if staff_last else m.get("staff_first", "Staff")

            messages.append({
                "date_display": date_disp,
                "time_display": time_disp,
                "template": m["template"],
                "staff_sender": staff_name
            })

    except Exception as e:
        flash(f"Error loading medical history: {str(e)}", "danger")

    return render_template(
        "patient/history.html",
        visits=visits,
        messages=messages
    )

@patient_bp.route("/profile", methods=["GET", "POST"])
@role_required("patient")
def profile():
    patient_id = session.get("user_id")

    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        email = request.form.get("email", "").strip().lower()
        dob = request.form.get("dob", "").strip()
        gender = request.form.get("gender", "").strip()
        street_address = request.form.get("street_address", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip().upper()
        zip_code = request.form.get("zip_code", "").strip()

        # Optional fields: blank out => None (NULL in DB)
        insurance = request.form.get("insurance", "").strip() or None
        member_id = request.form.get("member_id", "").strip() or None
        emergency_contact = request.form.get("emergency_contact", "").strip() or None

        required_items = [
            ("first_name", first_name),
            ("last_name", last_name),
            ("phone_number", phone_number),
            ("email", email),
            ("dob", dob),
            ("gender", gender),
            ("street_address", street_address),
            ("city", city),
            ("state", state),
            ("zip_code", zip_code),
        ]
        if any(not val for _, val in required_items):
            flash("Please fill in all required fields.", "danger")
            return redirect(url_for("patient.profile"))

        if len(state) != 2:
            flash("State must be a 2-letter abbreviation (e.g., VA).", "danger")
            return redirect(url_for("patient.profile"))

        try:
            conn = get_db_connection("patient")
            cursor = conn.cursor()

            # Ensure ZipCode exists
            cursor.execute(
                "INSERT IGNORE INTO ZipCode (zip_code, city, state) VALUES (%s, %s, %s)",
                (zip_code, city, state)
            )

            # Update Patient record
            cursor.execute(
                """
                UPDATE Patient
                SET first_name = %s,
                    last_name = %s,
                    phone_number = %s,
                    email = %s,
                    insurance = %s,
                    gender = %s,
                    street_address = %s,
                    zip_code = %s,
                    dob = %s,
                    member_id = %s,
                    emergency_contact = %s
                WHERE patient_id = %s
                """,
                (
                    first_name, last_name, phone_number, email, insurance,
                    gender, street_address, zip_code, dob, member_id, emergency_contact,
                    patient_id
                )
            )
            conn.commit()
            cursor.close()
            conn.close()

            # Update session user_name if name changed
            session["user_name"] = f"{first_name} {last_name}"
            flash("Profile updated successfully!", "success")
            return redirect(url_for("patient.profile"))

        except mysql.connector.Error as err:
            if err.errno == 1062:
                err_msg = str(err).lower()
                if "email" in err_msg:
                    flash("This email address is already in use by another account.", "danger")
                elif "phone_number" in err_msg or "phone" in err_msg:
                    flash("This phone number is already in use by another account.", "danger")
                else:
                    flash("This contact information is already in use by another account.", "danger")
            else:
                flash(f"Database error: {err.msg}", "danger")
            return redirect(url_for("patient.profile"))
        except Exception as e:
            flash(f"An unexpected error occurred: {str(e)}", "danger")
            return redirect(url_for("patient.profile"))

    # GET request: load current patient data
    patient_data = None
    try:
        conn = get_db_connection("patient")
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.patient_id, p.first_name, p.last_name, p.phone_number, p.email,
                   p.insurance, p.gender, p.street_address, p.zip_code, p.dob,
                   p.member_id, p.emergency_contact,
                   z.city, z.state
            FROM Patient p
            LEFT JOIN ZipCode z ON p.zip_code = z.zip_code
            WHERE p.patient_id = %s
            """,
            (patient_id,)
        )
        patient_data = cursor.fetchone()
        cursor.close()
        conn.close()

        if patient_data:
            dob_val = patient_data.get("dob")
            patient_data["dob_iso"] = dob_val.isoformat() if hasattr(dob_val, "isoformat") else (str(dob_val) if dob_val else "")
    except Exception as e:
        flash(f"Error loading profile: {str(e)}", "danger")

    if not patient_data:
        patient_data = {
            "first_name": session.get("user_name", "Patient").split()[0],
            "last_name": "",
            "phone_number": "",
            "email": "",
            "dob_iso": "",
            "gender": "Prefer not to say",
            "street_address": "",
            "zip_code": "",
            "city": "",
            "state": "",
            "insurance": "",
            "member_id": "",
            "emergency_contact": ""
        }

    return render_template("patient/profile.html", patient=patient_data)
