"""
War Advisor - Launcher per Eseguibile
Avvia il server FastAPI e apre automaticamente il browser
"""

import sys
import os
import webbrowser
import threading
import time


def _console_tollerante() -> None:
    """Impedisce che le emoji dei messaggi di avvio facciano cadere l'exe.

    La console di Windows usa cp1252: `print("⚔️ WAR ADVISOR")` solleva
    UnicodeEncodeError e l'applicazione muore prima ancora di avviare il
    server. Succede ogni volta che l'output non è una console vera — output
    rediretto su file, avvio da uno script, lancio da un altro programma —
    ed è esattamente come si presenta a chi riceve l'eseguibile e prova ad
    aprirlo in un modo diverso dal doppio clic.

    Si prova prima UTF-8 (output pulito); se non si può, si tiene la codifica
    di sistema sostituendo i caratteri che non entrano.
    """
    for flusso in (sys.stdout, sys.stderr):
        if flusso is None:
            continue
        try:
            flusso.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            try:
                flusso.reconfigure(errors="replace")
            except Exception:
                pass


_console_tollerante()

# Configura il path per PyInstaller
if getattr(sys, 'frozen', False):
    # Eseguito come exe (PyInstaller)
    BASE_DIR = sys._MEIPASS
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    os.chdir(BASE_DIR)
else:
    # Eseguito come script Python normale
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    os.chdir(BASE_DIR)

# Import dopo aver configurato il path
import uvicorn
from main import app

# Configurazione
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"


def open_browser():
    """Apre il browser dopo un breve delay per permettere al server di avviarsi"""
    time.sleep(1.5)
    print(f"\n🌐 Apertura browser: {URL}")
    webbrowser.open(URL)


def main():
    """Funzione principale"""
    print("=" * 50)
    print("⚔️  WAR ADVISOR - Conflict Strategy Recommender")
    print("=" * 50)
    print(f"\n🚀 Avvio server su {URL}")
    print("📁 Cartella dati:", DATA_DIR)
    print("\n⚠️  Per chiudere l'applicazione, chiudi questa finestra")
    print("    oppure premi CTRL+C\n")
    
    # Avvia il browser in un thread separato
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Avvia il server (blocca qui)
    try:
        uvicorn.run(
            app,
            host=HOST,
            port=PORT,
            log_level="warning"  # Riduce i log per l'utente finale
        )
    except KeyboardInterrupt:
        print("\n👋 Server terminato.")


if __name__ == "__main__":
    main()
