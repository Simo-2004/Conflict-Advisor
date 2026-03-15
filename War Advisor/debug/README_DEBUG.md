# DEBUG TEMPORANEO

Questa cartella contiene solo codice di debug temporaneo.

- Modulo: `strength_debug.py`
- Output log: `strength_debug.log` (JSON Lines)
- Tag eventi: `DEBUG_TEMP_REMOVE_ME`

Quando non serve più, puoi eliminare l'intera cartella `debug/`.
Il resto del progetto continua a funzionare grazie al fallback no-op in `gamecore/session/session.py`.
