# Start the Equity Decision Engine (http://localhost:8642)
# First run: python -m venv .venv ; .venv\Scripts\pip install -r requirements.txt
Set-Location $PSScriptRoot
.venv\Scripts\python -m uvicorn app.main:app --port 8642
