import os
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

def get_db_connection(role="patient"):
    creds = {
        "patient": (os.getenv("DB_PATIENT_USER"), os.getenv("DB_PATIENT_PASS")),
        "doctor":  (os.getenv("DB_DOCTOR_USER"),  os.getenv("DB_DOCTOR_PASS")),
        "staff":   (os.getenv("DB_STAFF_USER"),   os.getenv("DB_STAFF_PASS")),
    }
    user, password = creds.get(role, creds["patient"])
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 3306)),
        user=user,
        password=password,
        database=os.getenv("DB_NAME"),
    )