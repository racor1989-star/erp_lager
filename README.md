@"
# ERP Lagerverwaltung (Django)

## Setup (Windows PowerShell)

```powershell
cd C:\erp_lager
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8001