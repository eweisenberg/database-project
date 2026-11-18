from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from routes.utils import role_required, render_placeholder

staff_bp = Blueprint("staff", __name__, url_prefix="/staff")

@staff_bp.route("/dashboard")
@role_required("staff")
def dashboard():
    return render_placeholder("Front Desk Dashboard")

@staff_bp.route("/patients")
@role_required("staff")
def patients():
    return render_placeholder("Patient Roster")

@staff_bp.route("/appointments")
@role_required("staff")
def appointments():
    return render_placeholder("Appointments Calendar")

@staff_bp.route("/practice")
@role_required("staff")
def practice():
    return render_placeholder("Practice Management")
