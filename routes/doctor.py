from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from routes.utils import role_required, render_placeholder

doctor_bp = Blueprint("doctor", __name__, url_prefix="/doctor")

@doctor_bp.route("/dashboard")
@role_required("doctor")
def dashboard():
    return render_placeholder("Doctor Schedule")

@doctor_bp.route("/patients")
@role_required("doctor")
def patients():
    return render_placeholder("My Patients")
