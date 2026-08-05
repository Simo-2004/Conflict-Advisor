"""
gamecore.maps — Logica della mappa di gioco per War Advisor.

Esporta:
    Cell        — dataclass singola cella (terreno + occupazione)
    Occupation  — enum NEUTRAL / PLAYER / AI
    TERRAIN_TYPES — lista dei tipi di terreno disponibili
    GameMap     — classe principale della mappa a turni
    score_terrain_for_army — funzione di scoring terreno/esercito
"""

from .cell import Cell, Occupation, TERRAIN_TYPES
from .map  import GameMap, score_terrain_for_army

__all__ = [
    "Cell",
    "Occupation",
    "TERRAIN_TYPES",
    "GameMap",
    "score_terrain_for_army",
]
