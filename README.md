# FHIR Patient Report System

## Features
- Login with any credentials (demo) or sign up for a persistent account
- View patients with pagination + infinite scroll (25/50/100 per page)
- Filter by gender, age, name, admission/consult/treatment/discharge dates
- Select individual patients or all on current page
- Export selected patients to Excel (two sheets), CSV, or HTML

## Setup
1. Install dependencies:
   `pip install flask flask-cors pandas requests openpyxl numpy`
2. Run the app:
   `python index.py`
3. Open `http://localhost:5000`

## Files
- `index.py` – main Flask application
- `templates/` – HTML frontend
- `users.json` – persistent user database (auto‑created)

## Data Source
- Synthetic: generates 200 random patients with realistic timeline data.
- Real FHIR: set `USE_SYNTHETIC_ONLY = False` to try HAPI, SMART, OpenMRS, CMS servers.

## API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/patients` | GET | Filtered, paginated patient list |
| `/api/export_excel` | POST | Download Excel report of selected patients |
| `/api/export_csv` | POST | Download CSV report |
| `/api/export_html` | POST | Download HTML report |
| `/api/login`, `/api/register` | POST | Authentication |
| `/api/user` | GET | Current user info |
| `/api/logout` | POST | End session |
