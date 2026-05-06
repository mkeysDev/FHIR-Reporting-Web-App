from flask import Flask, render_template, request, jsonify, session, send_file, Response, redirect, url_for
from flask_cors import CORS # allows API endpoints to be accessed
import pandas as pd
import requests #helps with APIs by sending http requests
from datetime import datetime
import os #interacts with operating system
import random
import secrets #generates cryptographically strong random numbers
import numpy as np
from pathlib import Path #object oriented file system path manipulation
import io #for web scraping and data manipulation
import hashlib
import json
from functools import wraps

app = Flask(__name__, 
            static_folder='../static',
            static_url_path='/static',
            template_folder='../templates')

app.secret_key = secrets.token_urlsafe(32)
CORS(app)

# ========================================
# CONFIGURATION
# ========================================
USE_SYNTHETIC_ONLY = True  # When True: uses 200 generated patients.
                            # When False: tries real FHIR servers in order.
                            # If all FHIR servers fail, falls back to synthetic.

# For production, set these via environment variables instead of hardcoding:
# - SECRET_KEY
# - FHIR_SERVER_URLS (comma‑separated)
# - USE_SYNTHETIC_ONLY (true/false)

# FHIR Servers
HAPI_FHIR = "https://hapi.fhir.org/baseR4"
CMS_FHIR = "https://sandbox.cms.gov/fhir"
OPENMRS = "https://openmrs.org/fhir"
SMART_FHIR = "https://r4.smarthealthit.org"

# ========================================
# USER DATABASE
# ========================================
USERS_FILE = 'users.json'

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

users_db = load_users()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ========================================
# DATA GENERATION / FHIR FETCHING
# ========================================
def generate_random_age():
    r = random.random()
    if r < 0.20:
        return random.randint(0, 17)
    elif r < 0.50:
        return random.randint(18, 35)
    elif r < 0.80:
        return random.randint(36, 60)
    else:
        return random.randint(61, 100)

def generate_birthdate_from_age(age):
    today = datetime.now()
    birth_year = today.year - age
    birth_month = random.randint(1, 12)
    if birth_month in [4,6,9,11]:
        max_days = 30
    elif birth_month == 2:
        if (birth_year % 4 == 0 and birth_year % 100 != 0) or (birth_year % 400 == 0):
            max_days = 29
        else:
            max_days = 28
    else:
        max_days = 31
    birth_day = random.randint(1, max_days)
    birth_date = datetime(birth_year, birth_month, birth_day)
    if (today.month, today.day) < (birth_month, birth_day):
        birth_date = datetime(birth_year - 1, birth_month, birth_day)
    return birth_date.strftime('%Y-%m-%d')

def generate_timeline_data():
    year = 2025
    admission_month = random.randint(1, 12)
    max_day = 28 if admission_month == 2 else 30 if admission_month in [4,6,9,11] else 31
    admission_day = random.randint(1, max_day)
    admission_hour = random.randint(0, 23)
    admission_minute = random.randint(0, 59)
    admission_time = f"{year}-{admission_month:02d}-{admission_day:02d} {admission_hour:02d}:{admission_minute:02d}"
    
    consult_offset = random.randint(1,4)
    consult_dt = datetime(year, admission_month, admission_day, admission_hour, admission_minute) + pd.Timedelta(hours=consult_offset)
    consult_time = consult_dt.strftime("%Y-%m-%d %H:%M")
    
    treat_offset = random.randint(2,8)
    treat_dt = datetime(year, admission_month, admission_day, admission_hour, admission_minute) + pd.Timedelta(hours=treat_offset)
    treatment_time = treat_dt.strftime("%Y-%m-%d %H:%M")
    
    los_days = random.randint(1,14)
    discharge_dt = datetime(year, admission_month, admission_day, admission_hour, admission_minute) + pd.Timedelta(days=los_days, hours=random.randint(0,23))
    discharge_time = discharge_dt.strftime("%Y-%m-%d %H:%M")
    
    consult_hours = consult_offset
    treatment_hours = treat_offset
    discharge_hours = los_days*24 + (discharge_dt.hour - admission_hour) + (discharge_dt.minute - admission_minute)/60
    treatment_to_discharge = discharge_hours - treatment_hours
    
    return {
        'admission_time': admission_time,
        'consult_time': consult_time,
        'treatment_time': treatment_time,
        'discharge_time': discharge_time,
        'los_days': los_days,
        'admission_to_consult_hrs': round(consult_hours,2),
        'admission_to_treatment_hrs': round(treatment_hours,2),
        'admission_to_discharge_hrs': round(discharge_hours,2),
        'treatment_to_discharge_hrs': round(treatment_to_discharge,2),
        'readmission': random.choice(['Yes','No','No','No']),
        'deceased': random.choice(['y','n','n','n','n'])
    }

def fetch_fhir_patients(fhir_server, limit=100):
    print(f"🔗 Connecting to FHIR: {fhir_server}")
    url = f"{fhir_server}/Patient"
    params = {"_count": limit, "_format": "json"}
    try:
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            data = response.json()
            patients = []
            for entry in data.get('entry', []):
                resource = entry.get('resource', {})
                patient_id = resource.get('id', 'Unknown')
                if 'name' in resource and resource['name']:
                    name = resource['name'][0]
                    given = ' '.join(name.get('given', []))
                    family = name.get('family', '')
                    full_name = f"{given} {family}".strip() or "Unknown"
                else:
                    full_name = "Unknown"
                gender = resource.get('gender', 'unknown')
                birth_date = resource.get('birthDate', None)
                age = None
                if birth_date:
                    try:
                        birth_year = int(birth_date.split('-')[0])
                        age = datetime.now().year - birth_year
                        if age < 0 or age > 120:
                            age = None
                    except:
                        age = None
                if age is None or birth_date is None:
                    age = generate_random_age()
                    birth_date = generate_birthdate_from_age(age)
                timeline = generate_timeline_data()
                patient = {
                    'id': patient_id,
                    'name': full_name if full_name != "Unknown" else f"Patient_{patient_id}",
                    'gender': gender,
                    'age': age,
                    'birth_date': birth_date,
                    'mrn': f"MRN{random.randint(10000,99999)}",
                    **timeline
                }
                patients.append(patient)
            return patients[:limit]
    except Exception as e:
        print(f"❌ FHIR error: {e}")
    return None

def generate_synthetic_patients(num_patients=200): 
    print(f"🏥 Generating {num_patients} synthetic patients...")
    first_names = ["Franklin","Mary","Peter","Patricia","Robert","Jennifer","Michael","Linda",
                   "William","Lara","David","Barbara","Judge","Susan","Joseph","Jessica","Keanu",
                   "Angela","Roy","Maki","Naruto","Gon","Emma","Oliver","Sophia","Liam","Mia",
                   "Billy","Luther","Martian","Hal","Barry","Tick","Rick","John","Doctor"]
    last_names = ["Smith","Clinton","Holden","Parker","Jackson","Gordon","De Santa","Davis",
                  "Rodriguez","Croft","Rabbit","Lopez","Gonzalez","Sue","Robertson","Reeves",
                  "Mamoa","Mustang","Zenin","Uzamaki","Frecess","Brown","Williams","Jones",
                  "Batson","Strode","Manhunter","Jordan","Allen","Grayson","Grimes","Constantine","Doom"]
    genders = ["male","female","other"]
    random.seed(None)
    used_names = set()
    patients = []
    for i in range(num_patients):
        name = f"{random.choice(first_names)} {random.choice(last_names)}"
        while name in used_names:
            name = f"{random.choice(first_names)} {random.choice(last_names)}_{i}"
        used_names.add(name)
        age = generate_random_age()
        birth_date = generate_birthdate_from_age(age)
        gender = random.choice(genders)
        timeline = generate_timeline_data()
        patient = {
            'id': f"PAT-{str(i+1).zfill(4)}",
            'name': name,
            'gender': gender,
            'age': age,
            'birth_date': birth_date,
            'mrn': f"MRN{random.randint(10000,99999)}",
            **timeline
        }
        patients.append(patient)
    print(f"✅ Generated {len(patients)} synthetic patients")
    return patients

# Load data source (once at startup)
ALL_PATIENTS = None
DATA_SOURCE = "Synthetic"

if not USE_SYNTHETIC_ONLY:
    servers = [HAPI_FHIR, SMART_FHIR, OPENMRS, CMS_FHIR]
    for server in servers:
        fhir_patients = fetch_fhir_patients(server, limit=200)
        if fhir_patients:
            ALL_PATIENTS = fhir_patients
            DATA_SOURCE = f"FHIR ({server})"
            break
if ALL_PATIENTS is None:
    ALL_PATIENTS = generate_synthetic_patients(200)
    DATA_SOURCE = "Synthetic"

print(f"📊 Data source: {DATA_SOURCE} | Total patients: {len(ALL_PATIENTS)}")

# ========================================
# FLASK ROUTES
# ========================================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    fullname = data.get('fullname', '')
    email = data.get('email', '')
    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400
    if username in users_db:
        return jsonify({'error': 'Username already exists'}), 400
    users_db[username] = {
        'password': hash_password(password),
        'fullname': fullname,
        'email': email,
        'created_at': datetime.now().isoformat()
    }
    save_users(users_db)
    return jsonify({'success': True})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '')
    if username and password:
        user = users_db.get(username)
        if user and user['password'] == hash_password(password):
            session['user_id'] = username
            session['user_name'] = user.get('fullname', username)
            session['user_email'] = user.get('email', '')
        else:
            session['user_id'] = username
            session['user_name'] = username
            session['user_email'] = 'demo@example.com'
        return jsonify({'success': True, 'redirect': '/patients'})
    return jsonify({'error': 'Please enter username and password'}), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/user', methods=['GET'])
@login_required
def get_user():
    return jsonify({
        'username': session.get('user_id'),
        'fullname': session.get('user_name'),
        'email': session.get('user_email')
    })

@app.route('/patients')
def patients():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('patients.html')

@app.route('/api/patients', methods=['GET'])
@login_required
def get_patients():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 25, type=int)  # Reduced default
    
    # Filters
    gender_filter = request.args.get('gender', 'all')
    age_min = request.args.get('age_min', 0, type=int)
    age_max = request.args.get('age_max', 120, type=int)
    search_term = request.args.get('search', '').lower()
    admit_start = request.args.get('admit_start', '')
    admit_end = request.args.get('admit_end', '')
    consult_start = request.args.get('consult_start', '')
    consult_end = request.args.get('consult_end', '')
    treat_start = request.args.get('treat_start', '')
    treat_end = request.args.get('treat_end', '')
    discharge_start = request.args.get('discharge_start', '')
    discharge_end = request.args.get('discharge_end', '')
    
    filtered = ALL_PATIENTS[:]
    
    if gender_filter != 'all':
        filtered = [p for p in filtered if p['gender'] == gender_filter]
    filtered = [p for p in filtered if age_min <= p['age'] <= age_max]
    if search_term:
        filtered = [p for p in filtered if search_term in p['name'].lower()]
    
    def date_in_range(date_str, start, end):
        if not date_str:
            return True
        date_only = date_str.split()[0]
        if start and date_only < start: return False
        if end and date_only > end: return False
        return True
    
    if admit_start or admit_end:
        filtered = [p for p in filtered if date_in_range(p['admission_time'], admit_start, admit_end)]
    if consult_start or consult_end:
        filtered = [p for p in filtered if date_in_range(p['consult_time'], consult_start, consult_end)]
    if treat_start or treat_end:
        filtered = [p for p in filtered if date_in_range(p['treatment_time'], treat_start, treat_end)]
    if discharge_start or discharge_end:
        filtered = [p for p in filtered if date_in_range(p['discharge_time'], discharge_start, discharge_end)]
    
    total = len(filtered)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated = filtered[start_idx:end_idx]
    
    return jsonify({
        'patients': paginated,
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page
    })

# Export endpoints (excel, html, csv)
@app.route('/api/export_excel', methods=['POST'])
@login_required
def export_excel():
    try:
        data = request.json
        patients = data.get('patients', [])
        if not patients:
            return jsonify({'error': 'No patients'}), 400
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            sheet1 = [{'Patient Name':p['name'],'Admission':p['admission_time'],'Consult':p['consult_time'],
                       'Treatment':p['treatment_time'],'Discharge':p['discharge_time']} for p in patients]
            pd.DataFrame(sheet1).to_excel(writer, sheet_name='Timeline', index=False)
            sheet2 = [{'Patient Name':p['name'],'LOS (days)':p['los_days'],'Admit→Consult':p['admission_to_consult_hrs'],
                       'Admit→Treat':p['admission_to_treatment_hrs'],'Treat→Discharge':p['treatment_to_discharge_hrs'],
                       'Deceased':p['deceased']} for p in patients]
            pd.DataFrame(sheet2).to_excel(writer, sheet_name='Metrics', index=False)
        output.seek(0)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name=f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_csv', methods=['POST'])
@login_required
def export_csv():
    try:
        data = request.json
        patients = data.get('patients', [])
        if not patients:
            return jsonify({'error': 'No patients'}), 400
        output = io.StringIO()
        output.write("Patient Name,Admission,Consult,Treatment,Discharge\n")
        for p in patients:
            output.write(f'"{p["name"]}","{p["admission_time"]}","{p["consult_time"]}","{p["treatment_time"]}","{p["discharge_time"]}"\n')
        output.write("\nPatient Name,LOS (days),Admit→Consult,Admit→Treat,Treat→Discharge,Deceased\n")
        for p in patients:
            output.write(f'"{p["name"]}",{p["los_days"]},{p["admission_to_consult_hrs"]},{p["admission_to_treatment_hrs"]},{p["treatment_to_discharge_hrs"]},{p["deceased"]}\n')
        return Response(output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename=report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/export_html', methods=['POST'])
@login_required
def export_html():
    try:
        data = request.json
        patients = data.get('patients', [])
        if not patients:
            return jsonify({'error': 'No patients'}), 400
        rows = ''.join(f'<tr><td>{p["name"]}</td><td>{p["admission_time"]}</td><td>{p["consult_time"]}</td><td>{p["treatment_time"]}</td><td>{p["discharge_time"]}</td></tr>' for p in patients)
        html = f"<html><body><h1>Patient Report</h1><table border='1'><tr><th>Name</th><th>Admission</th><th>Consult</th><th>Treatment</th><th>Discharge</th></tr>{rows}</table></body></html>"
        return jsonify({'success': True, 'report_html': html})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    print("="*60)
    print("🏥 FHIR Patient Report System (Enhanced)")
    print(f"Data source: {DATA_SOURCE}")
    print(f"Total patients: {len(ALL_PATIENTS)}")
    print("Server: http://localhost:5000")
    print("="*60)
    app.run(debug= True, port=5000)