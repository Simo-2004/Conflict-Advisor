"""
War Advisor - Modulo Debug (SGANCIABILE)

Modulo di sviluppo pensato per essere rimosso in blocco prima della
produzione: cancellare questa cartella e i tre agganci elencati in
README.md è sufficiente, il gioco continua a funzionare identico.

Nulla nel motore dipende da questo package.
"""

from gamecore.debug_module.api import build_debug_router

__all__ = ["build_debug_router"]
