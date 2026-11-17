import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from dotenv import load_dotenv
from db import get_db_connection

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

@app.route("/", methods=["GET", "POST"])
def login():
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
            return redirect(url_for("login"))

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
            return redirect(url_for(f"{role}_dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")

@app.route("/patient/dashboard")
def patient_dashboard():
    if session.get("role") != "patient":
        return redirect(url_for("login"))
    return "<h1>Patient Dashboard</h1>"

@app.route("/doctor/dashboard")
def doctor_dashboard():
    if session.get("role") != "doctor":
        return redirect(url_for("login"))
    return "<h1>Doctor Dashboard</h1>"

@app.route("/staff/dashboard")
def staff_dashboard():
    if session.get("role") != "staff":
        return redirect(url_for("login"))
    return "<h1>Front Desk Dashboard</h1>"

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)