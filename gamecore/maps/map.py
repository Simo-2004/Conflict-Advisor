"""
War Advisor - GameMap
Gestisce la mappa di gioco a griglia 2D, il movimento a turni e la logica strategica.

Regole di gioco:
  - La mappa è una griglia rows × cols di celle (Cell).
  - Ogni cella ha un tipo di terreno e uno stato di occupazione.
  - Il GIOCATORE parte dal centro-basso (riga rows-1, colonna cols//2).
  - L'IA parte dal centro-alto (riga 0, colonna cols//2).
  - Ci si sposta di una casella alla volta (ortogonalmente: su/giù/sinistra/destra).
  - Entrare nella cella avversaria innesca una battaglia.
  - Obiettivo intermedio: occupare celle strategiche dove il proprio esercito è più efficace.
  - Obiettivo finale: eliminare l'esercito avversario (vincere la battaglia finale).

Terreni disponibili (da data/modifiers.json):
  Pianura, Foresta, Montagna, Fiume, Palude
"""

import random
from typing import Dict, List, Optional, Tuple

from .cell import Cell, Occupation, TERRAIN_TYPES

# Aliases comodi per i valori Occupation
PLAYER  = Occupation.PLAYER
AI      = Occupation.AI
NEUTRAL = Occupation.NEUTRAL

# Dimensioni di default della mappa
DEFAULT_ROWS: int = 14
DEFAULT_COLS: int = 16


# ──────────────────────────────────────────────────────────
# FUNZIONE DI SCORING (indipendente dalla classe)
# ──────────────────────────────────────────────────────────

def score_terrain_for_army(
    terrain: str,
    army_vector: Dict[str, float],
    terrain_modifiers: Dict[str, dict],
) -> float:
    """
    Calcola quanto un terreno è vantaggioso per un dato esercito.

    Applica i modificatori del terreno al vettore dell'esercito
    (compresi i CRITICAL) e restituisce la somma degli attributi
    risultante come punteggio di forza complessiva.

    Args:
        terrain:           nome del terreno (es. "Foresta")
        army_vector:       dict {attributo: valore float} dell'esercito
        terrain_modifiers: dict dei modificatori di terreno caricati da modifiers.json
                           (chiave = nome terreno, valore = dict attributo→modificatore)

    Returns:
        float — punteggio di forza effettiva (più alto = terreno più favorevole)
    """
    mods = terrain_modifiers.get(terrain, {})
    modified = army_vector.copy()
    for attr, modifier in mods.items():
        if attr not in modified:
            continue
        if modifier == "CRITICAL":
            # Se l'attributo è sotto soglia, penalità massiva
            if modified[attr] < 0.5:
                modified[attr] *= 0.5
        else:
            modified[attr] = min(1.0, max(0.0, modified[attr] * modifier))
    return sum(modified.values())


# ──────────────────────────────────────────────────────────
# GAME MAP
# ──────────────────────────────────────────────────────────

class GameMap:
    """
    Mappa di gioco a turni su griglia 2D.

    Struttura:
        self.grid[row][col]      → Cell
        self.castle_positions    → {Occupation: (row, col)} dove sta ogni castello
        self.turn                → numero del turno corrente (inizia da 1)

    Le armate non stanno qui: sul campo ci sono le legioni, e ognuna si porta
    dietro la propria posizione. La mappa tiene il terreno, i castelli e quello
    che ci viene costruito sopra.
    """

    def __init__(
        self,
        rows: int = DEFAULT_ROWS,
        cols: int = DEFAULT_COLS,
        seed: Optional[int] = None,
    ) -> None:
        """
        Args:
            rows: numero di righe della griglia (asse nord-sud)
            cols: numero di colonne della griglia (asse est-ovest)
            seed: seme opzionale per la generazione procedurale
                  (None = casuale; stesso seed → stessa mappa)
        """
        if rows < 4 or cols < 4:
            raise ValueError("La mappa deve essere almeno 4×4 celle.")

        self.rows: int = rows
        self.cols: int = cols
        self.seed: Optional[int] = seed

        self.grid: List[List[Cell]] = []
        self.castle_positions: Dict[Occupation, Tuple[int, int]] = {}
        self.turn: int = 1

        # Genera la griglia e posiziona i castelli
        self._generate_map(seed)
        self._place_armies()

    # ──────────────────────────────────────────────────────────
    # GENERAZIONE PROCEDURALE
    # ──────────────────────────────────────────────────────────

    def _generate_map(self, seed: Optional[int]) -> None:
        """
                Genera la griglia con distribuzione procedurale bilanciata:

                    - Pattern principali casuali (fiumi/foreste) per evitare mappe ripetitive.
                    - Distribuzione con limiti min/max per ciascun bioma.
                    - Garanzia presenza di tutti i terreni disponibili.
                    - Nessuna mappa mono-bioma o quasi tutta Fiume.
        """
        rng = random.Random(seed)

        # 1. Inizializza tutto a Pianura
        self.grid = [
            [Cell(row=r, col=c, terrain="Pianura") for c in range(self.cols)]
            for r in range(self.rows)
        ]

        self._paint_mountain_bands(rng)
        river_cells = self._paint_river_pattern(rng)
        self._paint_swamps_near_rivers(rng, river_cells)
        self._paint_forest_clusters(rng)
        self._rebalance_terrain_distribution(rng)
        self._ensure_all_terrains_present(rng)

        # 6. Marchia le celle strategiche
        self._mark_strategic_cells(rng)

    def _paint_mountain_bands(self, rng: random.Random) -> None:
        """Crea catene montuose principali a nord e rilievi laterali sparsi."""
        north_depth = max(2, self.rows // 4)
        for r in range(north_depth):
            density = 0.82 - (r * 0.16)
            for c in range(self.cols):
                if rng.random() < density:
                    self.grid[r][c].terrain = "Montagna"

        for r in range(north_depth, max(north_depth + 1, self.rows // 2)):
            for c in [0, 1, self.cols - 2, self.cols - 1]:
                if 0 <= c < self.cols and rng.random() < 0.26:
                    self.grid[r][c].terrain = "Montagna"

    def _paint_river_pattern(self, rng: random.Random) -> List[Tuple[int, int]]:
        """Disegna fiumi con pattern variabili ma controllati."""
        pattern = rng.choice(["double_horizontal", "meander", "broken_vertical"])
        river_cells: set[Tuple[int, int]] = set()

        def add_river_cell(row: int, col: int) -> None:
            if 0 <= row < self.rows and 0 <= col < self.cols:
                self.grid[row][col].terrain = "Fiume"
                river_cells.add((row, col))

        if pattern == "double_horizontal":
            rows = [self.rows // 3, (self.rows * 2) // 3]
            for base_row in rows:
                wobble = rng.randint(-1, 1)
                rr = min(self.rows - 2, max(1, base_row + wobble))
                for c in range(self.cols):
                    if rng.random() < 0.88:
                        add_river_cell(rr, c)
                for _ in range(max(2, self.cols // 8)):
                    add_river_cell(rr + rng.choice([-1, 1]), rng.randrange(self.cols))

        elif pattern == "meander":
            row = self.rows // 2 + rng.randint(-1, 1)
            for col in range(self.cols):
                add_river_cell(row, col)
                if rng.random() < 0.34:
                    row += rng.choice([-1, 1])
                row = min(self.rows - 2, max(1, row))
                if rng.random() < 0.22:
                    add_river_cell(row + rng.choice([-1, 1]), col)

            # secondo corso ridotto per evitare mono-pattern
            row2 = (self.rows // 3) if row > self.rows // 2 else (self.rows * 2) // 3
            for col in range(0, self.cols, 2):
                if rng.random() < 0.75:
                    add_river_cell(min(self.rows - 2, max(1, row2 + rng.randint(-1, 1))), col)

        else:  # broken_vertical
            base_col = self.cols // 2 + rng.randint(-2, 2)
            for row in range(self.rows):
                current_col = min(self.cols - 2, max(1, base_col + rng.randint(-2, 2)))
                if rng.random() < 0.82:
                    add_river_cell(row, current_col)
                if rng.random() < 0.45:
                    add_river_cell(row, current_col + rng.choice([-1, 1]))

            # ramo trasversale centrale
            branch_row = self.rows // 2 + rng.randint(-1, 1)
            for col in range(self.cols):
                if rng.random() < 0.48:
                    add_river_cell(branch_row, col)

        # Evita eccesso fiumi: massimo 22% della mappa
        max_river_cells = int(self.rows * self.cols * 0.22)
        if len(river_cells) > max_river_cells:
            to_remove = rng.sample(list(river_cells), len(river_cells) - max_river_cells)
            for r, c in to_remove:
                self.grid[r][c].terrain = "Pianura"
                river_cells.discard((r, c))

        return list(river_cells)

    def _paint_swamps_near_rivers(self, rng: random.Random, river_cells: List[Tuple[int, int]]) -> None:
        """Genera paludi in prossimità dei fiumi con densità moderata."""
        for rr, cc in river_cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    r, c = rr + dr, cc + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        cell = self.grid[r][c]
                        if cell.terrain == "Pianura" and rng.random() < 0.24:
                            cell.terrain = "Palude"

    def _paint_forest_clusters(self, rng: random.Random) -> None:
        """Crea cluster forestali in zone centrali e diagonali per varietà tattica."""
        clusters = rng.randint(7, 11)
        center_min = self.rows // 5
        center_max = (self.rows * 4) // 5

        for _ in range(clusters):
            seed_r = rng.randint(center_min, center_max)
            seed_c = rng.randint(1, self.cols - 2)
            radius_r = rng.randint(1, 2)
            radius_c = rng.randint(1, 3)
            for dr in range(-radius_r, radius_r + 1):
                for dc in range(-radius_c, radius_c + 1):
                    r, c = seed_r + dr, seed_c + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        cell = self.grid[r][c]
                        if cell.terrain == "Pianura" and rng.random() < 0.72:
                            cell.terrain = "Foresta"

    def _count_terrains(self) -> Dict[str, int]:
        counts = {terrain: 0 for terrain in TERRAIN_TYPES}
        for row in self.grid:
            for cell in row:
                counts[cell.terrain] += 1
        return counts

    def _random_cells_of_terrain(self, terrain: str, rng: random.Random) -> List[Tuple[int, int]]:
        coords = [
            (cell.row, cell.col)
            for row in self.grid
            for cell in row
            if cell.terrain == terrain and not cell.is_castle
        ]
        rng.shuffle(coords)
        return coords

    def _rebalance_terrain_distribution(self, rng: random.Random) -> None:
        """Ribilancia i biomi per evitare mappe estreme e mantenere varietà."""
        total = self.rows * self.cols
        min_ratio = {
            "Pianura": 0.22,
            "Foresta": 0.11,
            "Montagna": 0.09,
            "Fiume": 0.06,
            "Palude": 0.06,
        }
        max_ratio = {
            "Pianura": 0.62,
            "Foresta": 0.34,
            "Montagna": 0.30,
            "Fiume": 0.22,
            "Palude": 0.20,
        }

        min_counts = {k: max(1, int(total * v)) for k, v in min_ratio.items()}
        max_counts = {k: max(min_counts[k], int(total * v)) for k, v in max_ratio.items()}

        counts = self._count_terrains()

        # Riduci eccessi riconvertendo in Pianura
        for terrain in ("Fiume", "Palude", "Montagna", "Foresta"):
            while counts[terrain] > max_counts[terrain]:
                candidates = self._random_cells_of_terrain(terrain, rng)
                if not candidates:
                    break
                r, c = candidates[0]
                self.grid[r][c].terrain = "Pianura"
                counts[terrain] -= 1
                counts["Pianura"] += 1

        # Colma carenze attingendo da Pianura (o Foresta come fallback)
        for terrain in ("Montagna", "Foresta", "Fiume", "Palude"):
            while counts[terrain] < min_counts[terrain]:
                donors = self._random_cells_of_terrain("Pianura", rng)
                if not donors:
                    donors = self._random_cells_of_terrain("Foresta", rng)
                if not donors:
                    break
                r, c = donors[0]
                donor_terrain = self.grid[r][c].terrain
                self.grid[r][c].terrain = terrain
                counts[terrain] += 1
                counts[donor_terrain] -= 1

        # Garantisce che la Pianura non scenda troppo
        while counts["Pianura"] < min_counts["Pianura"]:
            donors = []
            for terrain in ("Foresta", "Palude", "Montagna"):
                if counts[terrain] > min_counts[terrain]:
                    donors.extend(self._random_cells_of_terrain(terrain, rng))
            if not donors:
                break
            r, c = donors[0]
            donor_terrain = self.grid[r][c].terrain
            self.grid[r][c].terrain = "Pianura"
            counts["Pianura"] += 1
            counts[donor_terrain] -= 1

    def _ensure_all_terrains_present(self, rng: random.Random) -> None:
        """Assicura almeno una cella per ogni terreno disponibile."""
        counts = self._count_terrains()
        for terrain in TERRAIN_TYPES:
            if counts.get(terrain, 0) > 0:
                continue

            donors = self._random_cells_of_terrain("Pianura", rng)
            if not donors:
                donors = [
                    (cell.row, cell.col)
                    for row in self.grid
                    for cell in row
                    if not cell.is_castle
                ]
                rng.shuffle(donors)
            if not donors:
                continue

            r, c = donors[0]
            self.grid[r][c].terrain = terrain

    def _mark_strategic_cells(self, rng: random.Random) -> None:
        """
        Colloca le celle strategiche sulla mappa.

        Criteri:
          - Una cella strategica "di terreno" per ogni tipo speciale
            (Montagna, Foresta, Fiume, Palude), scelta tra quelle nella
            fascia centrale della mappa (lontano dalle basi).
          - Una cella strategica "di Pianura" al centro esatto della mappa
            (controllo del campo aperto).
          - Nessun tipo di terreno viene omesso né aggiunto.
        """
        center_r = self.rows // 2
        center_c = self.cols // 2

        # Zona centrale: escludiamo le 2 righe più a nord e più a sud
        zone_r_min = 2
        zone_r_max = self.rows - 3

        strategic_terrains = {"Montagna", "Foresta", "Fiume", "Palude"}
        already_marked: set = set()

        for terrain in strategic_terrains:
            best_cell: Optional[Cell] = None
            best_dist = float("inf")
            for r in range(zone_r_min, zone_r_max + 1):
                for c in range(self.cols):
                    cell = self.grid[r][c]
                    if cell.terrain == terrain:
                        dist = abs(r - center_r) + abs(c - center_c)
                        if dist < best_dist:
                            best_dist = dist
                            best_cell = cell

            if best_cell is None:
                for r in range(self.rows):
                    for c in range(self.cols):
                        cell = self.grid[r][c]
                        if cell.terrain != terrain:
                            continue
                        dist = abs(r - center_r) + abs(c - center_c)
                        if dist < best_dist:
                            best_dist = dist
                            best_cell = cell

            if best_cell:
                best_cell.is_strategic = True
                already_marked.add(terrain)

        # Pianura mediana (centro della mappa)
        for dc in range(0, self.cols):
            c_try = (center_c + dc) % self.cols
            cell = self.grid[center_r][c_try]
            if cell.terrain == "Pianura":
                cell.is_strategic = True
                break

    def _place_armies(self) -> None:
        """
        Posiziona i castelli sulle celle di partenza:
            - PLAYER: castello su riga rows-1 (sud), colonna cols//2
            - AI:     castello su riga 0     (nord), colonna cols//2
        Le legioni verranno spawnate successivamente dal gioco.
        """
        player_castle_pos: Tuple[int, int] = (self.rows - 1, self.cols // 2)
        ai_castle_pos:     Tuple[int, int] = (0,             self.cols // 2)

        # Forza la cella di partenza a Pianura
        self.grid[player_castle_pos[0]][player_castle_pos[1]].terrain = "Pianura"
        self.grid[ai_castle_pos[0]][ai_castle_pos[1]].terrain = "Pianura"

        player_castle_cell = self.grid[player_castle_pos[0]][player_castle_pos[1]]
        ai_castle_cell = self.grid[ai_castle_pos[0]][ai_castle_pos[1]]

        player_castle_cell.occupation = PLAYER
        player_castle_cell.is_castle = True
        player_castle_cell.garrison_strength = 0

        ai_castle_cell.occupation = AI
        ai_castle_cell.is_castle = True
        ai_castle_cell.garrison_strength = 0

        self.castle_positions[PLAYER] = player_castle_pos
        self.castle_positions[AI] = ai_castle_pos

    # ──────────────────────────────────────────────────────────
    # ACCESSO ALLA GRIGLIA
    # ──────────────────────────────────────────────────────────

    def get_cell(self, row: int, col: int) -> Optional[Cell]:
        """Restituisce la cella in (row, col), o None se fuori dalla mappa."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.grid[row][col]
        return None

    # ──────────────────────────────────────────────────────────
    # LOGICA STRATEGICA
    # ──────────────────────────────────────────────────────────

    def get_strategic_targets(
        self,
        entity: Occupation,
        army_vector: Dict[str, float],
        terrain_modifiers: Dict[str, dict],
    ) -> List[Tuple[float, Cell]]:
        """
        Restituisce le celle strategiche NON già occupate dall'entità,
        ordinate per punteggio decrescente (le più vantaggiose per l'esercito).

        La funzione usa `score_terrain_for_army` (definita a livello modulo)
        per calcolare quanto ogni terreno amplifica la forza dell'esercito.

        Args:
            entity:            chi sta cercando obiettivi (PLAYER o AI)
            army_vector:       dict {attributo: valore float} dell'esercito
            terrain_modifiers: sezione "terrain" di modifiers.json già caricata

        Returns:
            Lista ordinata di (score: float, cell: Cell) — la prima è la priorità massima.
        """
        targets: List[Tuple[float, Cell]] = []
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self.grid[r][c]
                if cell.is_strategic and cell.occupation != entity:
                    score = score_terrain_for_army(
                        cell.terrain, army_vector, terrain_modifiers
                    )
                    targets.append((score, cell))
        targets.sort(key=lambda x: x[0], reverse=True)
        return targets

    # ──────────────────────────────────────────────────────────
    # STATO PARTITA
    # ──────────────────────────────────────────────────────────

    def count_occupied(self, entity: Occupation) -> int:
        """Numero totale di celle occupate dall'entità."""
        return sum(
            1 for r in range(self.rows) for c in range(self.cols)
            if self.grid[r][c].occupation == entity
        )

    def count_strategic_occupied(self, entity: Occupation) -> int:
        """Numero di celle strategiche occupate dall'entità."""
        return sum(
            1 for r in range(self.rows) for c in range(self.cols)
            if self.grid[r][c].occupation == entity and self.grid[r][c].is_strategic
        )

    def count_strategic_total(self) -> int:
        """Numero totale di celle strategiche presenti sulla mappa."""
        return sum(
            1 for r in range(self.rows) for c in range(self.cols)
            if self.grid[r][c].is_strategic
        )

    def count_garrisons(self, entity: Occupation) -> int:
        """Numero totale di distaccamenti lasciati sul campo dall'entità."""
        return sum(
            self.grid[r][c].garrison_strength
            for r in range(self.rows)
            for c in range(self.cols)
            if self.grid[r][c].occupation == entity
        )

    def count_mines(self, entity: Occupation) -> int:
        """Numero di miniere controllate dall'entità."""
        return sum(
            1
            for r in range(self.rows)
            for c in range(self.cols)
            if self.grid[r][c].occupation == entity and self.grid[r][c].is_mine
        )

    def count_fortification_levels(self, entity: Occupation) -> int:
        """Somma dei livelli di fortificazione sulle celle controllate dall'entità."""
        return sum(
            self.grid[r][c].fortification_level
            for r in range(self.rows)
            for c in range(self.cols)
            if self.grid[r][c].occupation == entity
        )

    def count_fortified_cells(self, entity: Occupation) -> int:
        """Numero di celle controllate con almeno una fortificazione."""
        return sum(
            1
            for r in range(self.rows)
            for c in range(self.cols)
            if self.grid[r][c].occupation == entity and self.grid[r][c].fortification_level > 0
        )

    def place_mine(self, entity: Occupation, row: int, col: int) -> Cell:
        """Piazza una miniera su una cella controllata e idonea."""
        cell = self.get_cell(row, col)
        if cell is None:
            raise ValueError("Cella fuori dalla mappa.")
        if cell.occupation != entity:
            raise ValueError("Puoi piazzare miniere solo su celle che controlli.")
        if cell.is_castle:
            raise ValueError("Non puoi costruire una miniera sul castello.")
        if cell.is_mine:
            raise ValueError("Su questa cella esiste già una miniera.")
        if cell.terrain == "Fiume":
            raise ValueError("Non puoi piazzare una miniera sul fiume.")

        cell.is_mine = True
        return cell

    #: Tetto di fortificazione delle celle normali. Oltre il quarto livello il
    #: bonus difensivo cresce di pochissimo mentre il costo continua a salire:
    #: senza tetto era una trappola economica, non una scelta.
    MAX_FORTIFICATION_LEVEL = 4

    def place_fortification(
        self,
        entity: Occupation,
        row: int,
        col: int,
        max_level: Optional[int] = None,
    ) -> Cell:
        """Aumenta il livello di fortificazione su una cella controllata e idonea.

        `max_level` permette al castello di imporre il proprio tetto dedicato;
        se non viene passato vale quello generale delle celle normali.
        """
        cell = self.get_cell(row, col)
        if cell is None:
            raise ValueError("Cella fuori dalla mappa.")
        if cell.occupation != entity:
            raise ValueError("Puoi fortificare solo celle che controlli.")

        cap = self.MAX_FORTIFICATION_LEVEL if max_level is None else max_level
        if cell.fortification_level >= cap:
            raise ValueError(
                f"Fortificazione già al livello massimo ({cap}) su questa cella."
            )

        cell.fortification_level += 1
        return cell

    # ──────────────────────────────────────────────────────────
    # SERIALIZZAZIONE
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """
        Serializza l'intero stato della mappa in un dizionario JSON-compatibile,
        adatto per essere inviato al frontend o salvato come checkpoint.
        """
        return {
            "rows":         self.rows,
            "cols":         self.cols,
            "seed":         self.seed,
            "turn":         self.turn,
            "castles": {
                k.value: list(v) for k, v in self.castle_positions.items()
            },
            "grid": [
                [cell.to_dict() for cell in row]
                for row in self.grid
            ],
            "stats": {
                "player_cells":     self.count_occupied(PLAYER),
                "ai_cells":         self.count_occupied(AI),
                "player_strategic": self.count_strategic_occupied(PLAYER),
                "ai_strategic":     self.count_strategic_occupied(AI),
                "player_garrisons": self.count_garrisons(PLAYER),
                "ai_garrisons":     self.count_garrisons(AI),
                "player_mines":     self.count_mines(PLAYER),
                "ai_mines":         self.count_mines(AI),
                "player_fortification_levels": self.count_fortification_levels(PLAYER),
                "ai_fortification_levels": self.count_fortification_levels(AI),
                "player_fortified_cells": self.count_fortified_cells(PLAYER),
                "ai_fortified_cells": self.count_fortified_cells(AI),
                "total_strategic":  self.count_strategic_total(),
            },
        }

    # ──────────────────────────────────────────────────────────
    # DEBUG / STAMPA
    # ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        """
        Rappresentazione ASCII della mappa (utile per debug da terminale).

        Legenda:
          .  Pianura      F  Foresta     M  Montagna
          ~  Fiume        P  Palude
                    *  cella strategica (cell.is_strategic)
                    C  castello
          p  cella occupata dal giocatore
          a  cella occupata dall'IA
        """
        t_icons = {
            "Pianura":  ".",
            "Foresta":  "F",
            "Montagna": "M",
            "Fiume":    "~",
            "Palude":   "P",
        }
        lines = [
            f"  ═══ Mappa {self.rows}×{self.cols}  |  Turno {self.turn} ═══",
            "     " + "".join(f"{c:^3}" for c in range(self.cols)),
        ]

        for r in range(self.rows):
            row_str = f"{r:2d} │ "
            for c in range(self.cols):
                cell = self.grid[r][c]
                if cell.is_castle:
                    row_str += " C "
                elif cell.is_strategic:
                    row_str += f"*{t_icons[cell.terrain]}*"
                else:
                    t = t_icons[cell.terrain]
                    if cell.occupation == NEUTRAL:
                        row_str += f" {t} "
                    elif cell.occupation == PLAYER:
                        row_str += f"p{t}p"
                    else:
                        row_str += f"a{t}a"
            lines.append(row_str)

        lines.append(
            f"  Stats → P:{self.count_occupied(PLAYER)} celle "
            f"({self.count_strategic_occupied(PLAYER)} strat.)  |  "
            f"AI:{self.count_occupied(AI)} celle "
            f"({self.count_strategic_occupied(AI)} strat.)  |  "
            f"Strat. totali: {self.count_strategic_total()}"
        )
        return "\n".join(lines)
