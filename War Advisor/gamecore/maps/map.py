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
        self.grid[row][col]  → Cell
        self.positions       → {Occupation: (row, col)} posizioni correnti degli eserciti
        self.turn            → numero del turno corrente (inizia da 1)
        self.current_turn    → Occupation di chi deve muoversi (PLAYER o AI)
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
        self.positions: Dict[Occupation, Tuple[int, int]] = {}
        self.castle_positions: Dict[Occupation, Tuple[int, int]] = {}
        self.turn: int = 1
        self.current_turn: Occupation = PLAYER   # il giocatore muove per primo

        # Genera la griglia e posiziona gli eserciti
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
                Posiziona gli eserciti e i castelli sulle celle di partenza:
                    - PLAYER: castello/armata su riga rows-1 (sud), colonna cols//2
                    - AI:     castello/armata su riga 0     (nord), colonna cols//2

                I castelli partono senza guarnigioni fittizie: i presidi sono solo
                quelli realmente distaccati dalle legioni durante la partita.
        """
        player_castle_pos: Tuple[int, int] = (self.rows - 1, self.cols // 2)
        ai_castle_pos:     Tuple[int, int] = (0,             self.cols // 2)
        player_pos: Tuple[int, int] = (self.rows - 2, self.cols // 2)
        ai_pos:     Tuple[int, int] = (1,             self.cols // 2)

        # Forza la cella di partenza a Pianura (non si inizia mai su un ostacolo)
        self.grid[player_castle_pos[0]][player_castle_pos[1]].terrain = "Pianura"
        self.grid[ai_castle_pos[0]][ai_castle_pos[1]].terrain = "Pianura"
        self.grid[player_pos[0]][player_pos[1]].terrain = "Pianura"
        self.grid[ai_pos[0]][ai_pos[1]].terrain = "Pianura"

        player_castle_cell = self.grid[player_castle_pos[0]][player_castle_pos[1]]
        ai_castle_cell = self.grid[ai_castle_pos[0]][ai_castle_pos[1]]
        player_cell = self.grid[player_pos[0]][player_pos[1]]
        ai_cell = self.grid[ai_pos[0]][ai_pos[1]]

        player_castle_cell.occupation = PLAYER
        player_castle_cell.is_castle = True
        player_castle_cell.garrison_strength = 0

        ai_castle_cell.occupation = AI
        ai_castle_cell.is_castle = True
        ai_castle_cell.garrison_strength = 0

        player_cell.occupation = PLAYER
        ai_cell.occupation = AI

        self.positions[PLAYER] = player_pos
        self.positions[AI]     = ai_pos
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

    def get_neighbors(self, row: int, col: int) -> List[Cell]:
        """
        Restituisce le celle adiacenti ortogonali (su, giù, sinistra, destra).
        Non include celle fuori dalla mappa.
        """
        neighbors: List[Cell] = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            cell = self.get_cell(row + dr, col + dc)
            if cell is not None:
                neighbors.append(cell)
        return neighbors

    def is_adjacent(
        self,
        pos_a: Tuple[int, int],
        pos_b: Tuple[int, int],
    ) -> bool:
        """True se le due posizioni differiscono di esattamente 1 in una sola direzione."""
        dr = abs(pos_a[0] - pos_b[0])
        dc = abs(pos_a[1] - pos_b[1])
        return (dr == 1 and dc == 0) or (dr == 0 and dc == 1)

    def get_castle_position(self, entity: Occupation) -> Optional[Tuple[int, int]]:
        """Restituisce la posizione del castello dell'entità."""
        return self.castle_positions.get(entity)

    def is_castle_controlled_by(self, entity: Occupation) -> bool:
        """True se il castello dell'entità è ancora sotto il suo controllo."""
        castle_pos = self.castle_positions.get(entity)
        if castle_pos is None:
            return False
        cell = self.grid[castle_pos[0]][castle_pos[1]]
        return cell.occupation == entity and cell.is_castle

    # ──────────────────────────────────────────────────────────
    # TURNI E MOVIMENTO
    # ──────────────────────────────────────────────────────────

    def move(
        self,
        entity: Occupation,
        to_pos: Tuple[int, int],
        leave_garrison: bool = False,
    ) -> dict:
        """
        Esegue il movimento di un'entità verso una cella adiacente.

        Regole:
          - Il movimento è consentito solo al possessore del turno corrente.
          - La destinazione deve essere ortogonalmente adiacente.
                    - Entrare nella cella dell'armata avversaria, in una guarnigione o nel
                        castello nemico innesca una battaglia.
                    - Se `leave_garrison=True`, il giocatore lascia un distaccamento sulla
                        casella di partenza invece di abbandonarla del tutto.
                    - Il controllo territoriale della cella di partenza resta comunque
                        all'entità che si muove.

        Args:
            entity: chi si muove (PLAYER o AI)
            to_pos: (row, col) della cella di destinazione

        Returns:
            dict con i campi:
              ok               (bool)   — True se la mossa è valida
              message          (str)    — descrizione dell'esito
              captured         (bool)   — True se una cella nemica/neutrale è stata presa
              strategic_captured (bool) — True se la cella catturata è strategica
              battle           (bool)   — True se la mossa raggiunge l'esercito avversario
              terrain          (str)    — terreno della cella di destinazione
        """
        side_label = "PLAYER" if entity == PLAYER else "IA"
        turn_label = "PLAYER" if self.current_turn == PLAYER else "IA"

        if entity not in self.positions:
            return {"ok": False, "message": f"Entita '{side_label}' non trovata."}

        if entity != self.current_turn:
            return {
                "ok": False,
                "message": f"Non e il turno di '{side_label}' (turno di '{turn_label}').",
            }

        from_pos = self.positions[entity]
        to_row, to_col = to_pos

        if not self.is_adjacent(from_pos, to_pos):
            return {"ok": False, "message": "La destinazione non è adiacente alla posizione corrente."}

        if not (0 <= to_row < self.rows and 0 <= to_col < self.cols):
            return {"ok": False, "message": "Destinazione fuori dalla mappa."}

        dest_cell = self.grid[to_row][to_col]
        from_cell = self.grid[from_pos[0]][from_pos[1]]
        enemy_pos = self.positions.get(entity.opposite())
        own_castle_pos = self.castle_positions.get(entity)
        enemy_castle_pos = self.castle_positions.get(entity.opposite())

        if own_castle_pos == to_pos:
            return {"ok": False, "message": "La casella del castello è proibita al movimento."}

        encounter_type = "none"
        if enemy_pos == to_pos:
            encounter_type = "field_army"
        elif enemy_castle_pos == to_pos and dest_cell.is_castle and dest_cell.occupation == entity.opposite():
            encounter_type = "castle"
        elif dest_cell.garrison_strength > 0 and dest_cell.occupation == entity.opposite():
            encounter_type = "garrison"
        elif dest_cell.fortification_level > 0 and dest_cell.occupation == entity.opposite():
            encounter_type = "fortified"

        battle = encounter_type != "none"
        garrison_left = leave_garrison

        if garrison_left and encounter_type != "castle":
            from_cell.garrison_strength += 1

        # La cella di partenza resta sotto controllo dell'entità.
        from_cell.occupation = entity

        captured = False
        strategic_captured = False
        if encounter_type != "castle":
            # Occupa la destinazione (mai per assalto castello: tile non attraversabile)
            captured = dest_cell.occupation != entity
            strategic_captured = captured and dest_cell.is_strategic
            dest_cell.occupation = entity
            self.positions[entity] = to_pos

        msg = (
            f"[Turno {self.turn}] {side_label} -> ({to_row},{to_col}) "
            f"[{dest_cell.terrain}]"
        )
        if garrison_left and encounter_type != "castle":
            msg += " — Guarnigione lasciata alle spalle"
        if encounter_type == "field_army":
            msg += " — ⚔ Scontro tra armate!"
        elif encounter_type == "garrison":
            msg += " — 🛡 Presidio nemico intercettato!"
        elif encounter_type == "fortified":
            msg += " — 🧱 Assalto a territorio fortificato!"
        elif encounter_type == "castle":
            msg += " — 🏰 Assalto al castello (da adiacenza)!"
        elif strategic_captured:
            msg += " — ★ Punto strategico conquistato!"

        return {
            "ok":                True,
            "message":           msg,
            "captured":          captured,
            "strategic_captured": strategic_captured,
            "battle":            battle,
            "encounter_type":    encounter_type,
            "terrain":           dest_cell.terrain,
            "from_pos":          from_pos,
            "to_pos":            to_pos,
            "leave_garrison":    garrison_left,
            "destination": {
                "is_castle": dest_cell.is_castle,
                "garrison_strength": dest_cell.garrison_strength,
                "previous_controller": entity.opposite().value if captured else entity.value,
            },
        }

    def end_turn(self) -> None:
        """
        Passa il controllo all'avversario.
        Il contatore 'turn' si incrementa ogni volta che ricomincia
        il turno del PLAYER (cioè dopo che anche l'IA ha mosso).
        """
        if self.current_turn == PLAYER:
            self.current_turn = AI
        else:
            self.current_turn = PLAYER
            self.turn += 1

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

    def best_move_toward(
        self,
        entity: Occupation,
        target: Tuple[int, int],
    ) -> Optional[Tuple[int, int]]:
        """
        Suggerisce la cella adiacente che avvicina maggiormente l'entita
        al target (distanza di Manhattan), preferendo celle non gia
        controllate ma senza bloccarsi nel proprio territorio.

        Usato principalmente dall'IA per scegliere il prossimo passo.

        Args:
            entity: chi deve muoversi
            target: (row, col) della destinazione desiderata

        Returns:
            (row, col) della mossa consigliata, o None se bloccato.
        """
        from_pos = self.positions.get(entity)
        if from_pos is None:
            return None

        current_dist = abs(from_pos[0] - target[0]) + abs(from_pos[1] - target[1])
        candidates: List[Tuple[float, Tuple[int, int]]] = []

        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = from_pos[0] + dr, from_pos[1] + dc
            if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                continue
            cell = self.grid[nr][nc]
            dist = abs(nr - target[0]) + abs(nc - target[1])
            own_penalty = 0.35 if cell.occupation == entity else 0.0
            score = float(dist) + own_penalty
            candidates.append((score, (nr, nc)))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        best_score = candidates[0][0]
        best_move = candidates[0][1]

        # Se possibile, evita mosse che aumentano la distanza dal target.
        best_dist = abs(best_move[0] - target[0]) + abs(best_move[1] - target[1])
        if best_dist <= current_dist:
            return best_move

        for _, move in candidates:
            dist = abs(move[0] - target[0]) + abs(move[1] - target[1])
            if dist <= current_dist:
                return move

        return best_move

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

    def place_fortification(self, entity: Occupation, row: int, col: int) -> Cell:
        """Aumenta il livello di fortificazione su una cella controllata e idonea."""
        cell = self.get_cell(row, col)
        if cell is None:
            raise ValueError("Cella fuori dalla mappa.")
        if cell.occupation != entity:
            raise ValueError("Puoi fortificare solo celle che controlli.")
        if cell.is_castle:
            raise ValueError("Non puoi fortificare il castello centrale.")

        cell.fortification_level += 1
        return cell

    def check_battle_trigger(self) -> Optional[Occupation]:
        """
        Controlla se le due armate si trovano in celle adiacenti (condizione
        di battaglia imminente sul prossimo turno).

        Returns:
            L'Occupation dell'entità che potrebbe attaccare (quella di turno),
            oppure None se non ci sono eserciti vicini.
        """
        p_pos  = self.positions.get(PLAYER)
        ai_pos = self.positions.get(AI)
        if p_pos and ai_pos and self.is_adjacent(p_pos, ai_pos):
            return self.current_turn
        return None

    def is_game_over(self) -> Optional[Occupation]:
        """
        Controlla se la partita è terminata (un castello è stato conquistato).

        Returns:
            Il vincitore (PLAYER o AI) se la partita è finita, altrimenti None.
        """
        if not self.is_castle_controlled_by(PLAYER):
            return AI
        if not self.is_castle_controlled_by(AI):
            return PLAYER
        return None

    def eliminate(self, entity: Occupation) -> None:
        """
        Rimuove un esercito dalla mappa (chiamato dopo una sconfitta in battaglia).

        Args:
            entity: l'entità da eliminare
        """
        pos = self.positions.pop(entity, None)
        if pos:
            self.grid[pos[0]][pos[1]].occupation = NEUTRAL

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
            "current_turn": self.current_turn.value,
            "positions": {
                k.value: list(v) for k, v in self.positions.items()
            },
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
          [P] posizione giocatore        [A] posizione IA
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
        p_pos  = self.positions.get(PLAYER)
        ai_pos = self.positions.get(AI)

        lines = [
            f"  ═══ Mappa {self.rows}×{self.cols}  |  Turno {self.turn}  |  Muove: {self.current_turn.value} ═══",
            "     " + "".join(f"{c:^3}" for c in range(self.cols)),
        ]

        for r in range(self.rows):
            row_str = f"{r:2d} │ "
            for c in range(self.cols):
                cell = self.grid[r][c]
                pos  = (r, c)
                if pos == p_pos:
                    row_str += "[P]"
                elif pos == ai_pos:
                    row_str += "[A]"
                elif cell.is_castle:
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
