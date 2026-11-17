# Health System Management Web App

## `.env` Setup
Create a `.env` file in the root directory with the following variables. `SECRET_KEY` can be any string and is used so Flask can make sure no one tampers with the session. All of the `DB_*_USER`s and `DB_*_PASS`s should be the username and password you use to log into the UVA CS phpMyAdmin with access to the mgf6hb_c database.

```
SECRET_KEY=random-secret-key
DB_HOST=mysql01.cs.virginia.edu
DB_PORT=3306
DB_NAME=mgf6hb_c

DB_PATIENT_USER=your_mysql_username
DB_PATIENT_PASS=your_mysql_password

DB_DOCTOR_USER=your_mysql_username
DB_DOCTOR_PASS=your_mysql_password

DB_STAFF_USER=your_mysql_username
DB_STAFF_PASS=your_mysql_password
```

## Running the App

In terminal, run `flask run` and go to `http://127.0.0.1:5000`.