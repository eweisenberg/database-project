import mysql.connector
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from db import get_db_connection

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/login", methods=["GET", "POST"])
@auth_bp.route("/", methods=["GET", "POST"])
def login():
    if session.get("role") in ("patient", "doctor", "staff"):
        return redirect(url_for(f"{session['role']}.dashboard"))

    if request.method == "POST":
        email = request.form["email"].strip()
        password = request.form["password"]
        role = request.form["role"]  # 'patient', 'doctor', or 'staff'

        table_map = {
            "patient": ("Patient", "patient_id"),
            "doctor":  ("Doctor", "doctor_id"),
            "staff":   ("Staff", "staff_id"),
        }
        if role not in table_map:
            flash("Invalid role selected.", "danger")
            return redirect(url_for("auth.login"))

        table, id_col = table_map[role]
        conn = get_db_connection(role)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            f"SELECT {id_col} AS id, first_name, last_name, password_hash FROM {table} WHERE email = %s",
            (email,)
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["role"] = role
            session["user_name"] = f"{user['first_name']} {user['last_name']}"
            return redirect(url_for(f"{role}.dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if session.get("role"):
        return redirect(url_for(f"{session['role']}.dashboard"))

    if request.method == "POST":
        form_data = {
            "first_name": request.form.get("first_name", "").strip(),
            "last_name": request.form.get("last_name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "password": request.form.get("password", ""),
            "confirm_password": request.form.get("confirm_password", ""),
            "phone_number": request.form.get("phone_number", "").strip(),
            "gender": request.form.get("gender", "").strip(),
            "street_address": request.form.get("street_address", "").strip(),
            "city": request.form.get("city", "").strip(),
            "state": request.form.get("state", "").strip().upper(),
            "zip_code": request.form.get("zip_code", "").strip(),
            "dob": request.form.get("dob", "").strip(),
            "insurance": request.form.get("insurance", "").strip(),
            "member_id": request.form.get("member_id", "").strip(),
            "emergency_contact": request.form.get("emergency_contact", "").strip(),
        }

        required_fields = [
            ("first_name", "First name"),
            ("last_name", "Last name"),
            ("email", "Email address"),
            ("password", "Password"),
            ("phone_number", "Phone number"),
            ("gender", "Gender"),
            ("street_address", "Street address"),
            ("city", "City"),
            ("state", "State"),
            ("zip_code", "Zip code"),
            ("dob", "Date of birth"),
        ]
        missing = [label for key, label in required_fields if not form_data[key]]
        if missing:
            flash(f"Please fill in all required fields: {', '.join(missing)}.", "danger")
            return render_template("register.html", form_data=form_data)

        if form_data["password"] != form_data["confirm_password"]:
            flash("Passwords do not match.", "danger")
            return render_template("register.html", form_data=form_data)

        if len(form_data["state"]) != 2:
            flash("State must be a 2-letter abbreviation (e.g., VA).", "danger")
            return render_template("register.html", form_data=form_data)

        password_hash = generate_password_hash(form_data["password"])
        insurance = form_data["insurance"] or None
        member_id = form_data["member_id"] or None
        emergency_contact = form_data["emergency_contact"] or None

        try:
            conn = get_db_connection("patient")
            cursor = conn.cursor()

            cursor.execute(
                "INSERT IGNORE INTO ZipCode (zip_code, city, state) VALUES (%s, %s, %s)",
                (form_data["zip_code"], form_data["city"], form_data["state"])
            )

            cursor.execute(
                """
                INSERT INTO Patient (
                    first_name, last_name, phone_number, email, insurance,
                    gender, street_address, zip_code, password_hash, dob,
                    member_id, emergency_contact
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    form_data["first_name"],
                    form_data["last_name"],
                    form_data["phone_number"],
                    form_data["email"],
                    insurance,
                    form_data["gender"],
                    form_data["street_address"],
                    form_data["zip_code"],
                    password_hash,
                    form_data["dob"],
                    member_id,
                    emergency_contact,
                )
            )
            conn.commit()
            cursor.close()
            conn.close()

            flash("Account created successfully! Please sign in with your email and password.", "success")
            return redirect(url_for("auth.login"))

        except mysql.connector.Error as err:
            if err.errno == 1062:
                err_msg = str(err).lower()
                if "email" in err_msg:
                    flash("An account with this email already exists.", "danger")
                elif "phone_number" in err_msg or "phone" in err_msg:
                    flash("An account with this phone number already exists.", "danger")
                else:
                    flash("An account with this email or phone number already exists.", "danger")
            elif "prevent_past_appointments" in str(err).lower() or err.errno == 1644:
                flash(f"Constraint error: {err.msg}", "danger")
            else:
                flash(f"Database error: {err.msg}", "danger")
            return render_template("register.html", form_data=form_data)
        except Exception as e:
            flash(f"An unexpected error occurred: {str(e)}", "danger")
            return render_template("register.html", form_data=form_data)

    return render_template("register.html", form_data=None)

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
