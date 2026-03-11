# setup.ps1 - Crea e configura il venv per War Advisor

$VenvDir = ".venv"

# Crea il venv se non esiste
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creazione virtual environment..." -ForegroundColor Cyan
    python -m venv $VenvDir
} else {
    Write-Host "Virtual environment gia' esistente." -ForegroundColor Yellow
}

# Attiva il venv
Write-Host "Attivazione virtual environment..." -ForegroundColor Cyan
& "$VenvDir\Scripts\Activate.ps1"

# Aggiorna pip
Write-Host "Aggiornamento pip..." -ForegroundColor Cyan
python -m pip install --upgrade pip

# Installa le dipendenze
Write-Host "Installazione dipendenze da requirements.txt..." -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host ""
Write-Host "Setup completato! Il venv e' attivo." -ForegroundColor Green
Write-Host "Per avviare l'app: python run_app.py" -ForegroundColor Green
