"""
gamecore — Modulo di gioco per War Advisor.
Contiene la logica della mappa e delle meccaniche di gioco a turni.
"""

from .maps import GameMap, Cell, Occupation, TERRAIN_TYPES, score_terrain_for_army

__all__ = [
    "GameMap",
    "Cell",
    "Occupation",
    "TERRAIN_TYPES",
    "score_terrain_for_army",
]
