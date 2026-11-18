from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db_connection
from routes.utils import role_required, render_placeholder

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")

@patient_bp.route("/dashboard")
@role_required("patient")
def dashboard():
    return render_placeholder("Patient Dashboard")

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
