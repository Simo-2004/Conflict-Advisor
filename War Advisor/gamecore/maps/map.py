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
DEFAULT_ROWS: int = 12
DEFAULT_COLS: int = 10


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
        Genera la griglia con distribuzione procedurale realistica:

          - Montagne: bordo nord e angoli laterali nord (zona IA)
          - Fiumi:    due strisce orizzontali attraverso la mappa,
                      con "guadi" casuali (celle di Pianura nella riga del Fiume)
          - Paludi:   adiacenti ai fiumi (rive)
          - Foreste:  cluster nella zona centrale
          - Pianura:  tutto il resto

        Le montagne forniscono vantaggio difensivo all'IA, le foreste e
        le paludi sono zone strategiche per unità stealth/mobilità.
        """
        rng = random.Random(seed)

        # 1. Inizializza tutto a Pianura
        self.grid = [
            [Cell(row=r, col=c, terrain="Pianura") for c in range(self.cols)]
            for r in range(self.rows)
        ]

        # 2. Montagne — bordo nord (righe 0..nord_depth) e angoli nord-est/ovest
        nord_depth = max(1, self.rows // 5)        # es. righe 0-1 su mappa 12×10
        for r in range(nord_depth):
            for c in range(self.cols):
                if rng.random() > 0.35:
                    self.grid[r][c].terrain = "Montagna"
        # Propagazione montagne sulle colonne laterali nel terzo superiore
        for r in range(nord_depth, self.rows // 3):
            for c in [0, self.cols - 1]:
                if rng.random() > 0.55:
                    self.grid[r][c].terrain = "Montagna"

        # 3. Fiumi — due strisce orizzontali (1/3 e 2/3 dell'altezza)
        river_rows: List[int] = [self.rows // 3, (self.rows * 2) // 3]
        ford_cols: List[List[int]] = []    # colonne dei guadi per ogni fiume
        for rr in river_rows:
            # 1-3 guadi per fiume (celle che rimangono Pianura)
            n_fords = rng.randint(1, 3)
            fords = set(rng.sample(range(self.cols), min(n_fords, self.cols)))
            ford_cols.append(sorted(fords))
            for c in range(self.cols):
                if c not in fords:
                    self.grid[rr][c].terrain = "Fiume"

        # 4. Paludi — adiacenti ai fiumi (celle a nord/sud della riga Fiume)
        for rr in river_rows:
            for c in range(self.cols):
                for dr in [-1, 1]:
                    r = rr + dr
                    if 0 <= r < self.rows and self.grid[r][c].terrain == "Pianura":
                        if rng.random() > 0.55:
                            self.grid[r][c].terrain = "Palude"

        # 5. Foreste — 4-6 cluster nella zona centrale
        center_start_r = self.rows // 4
        center_end_r   = (self.rows * 3) // 4
        n_clusters = rng.randint(4, 6)
        for _ in range(n_clusters):
            seed_r = rng.randint(center_start_r, center_end_r)
            seed_c = rng.randint(1, self.cols - 2)
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    r, c = seed_r + dr, seed_c + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        if self.grid[r][c].terrain == "Pianura" and rng.random() > 0.40:
                            self.grid[r][c].terrain = "Foresta"

        # 6. Marchia le celle strategiche
        self._mark_strategic_cells(rng)

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
        Posiziona gli eserciti sulle celle di partenza:
          - PLAYER: riga rows-1 (sud), colonna cols//2
          - AI:     riga 0     (nord), colonna cols//2
        Le celle di partenza vengono forzate a Pianura per garantire
        che siano sempre raggiungibili.
        """
        player_pos: Tuple[int, int] = (self.rows - 1, self.cols // 2)
        ai_pos:     Tuple[int, int] = (0,             self.cols // 2)

        # Forza la cella di partenza a Pianura (non si inizia mai su un ostacolo)
        self.grid[player_pos[0]][player_pos[1]].terrain = "Pianura"
        self.grid[ai_pos[0]][ai_pos[1]].terrain = "Pianura"

        self.grid[player_pos[0]][player_pos[1]].occupation = PLAYER
        self.grid[ai_pos[0]][ai_pos[1]].occupation = AI

        self.positions[PLAYER] = player_pos
        self.positions[AI]     = ai_pos

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

    # ──────────────────────────────────────────────────────────
    # TURNI E MOVIMENTO
    # ──────────────────────────────────────────────────────────

    def move(
        self,
        entity: Occupation,
        to_pos: Tuple[int, int],
    ) -> dict:
        """
        Esegue il movimento di un'entità verso una cella adiacente.

        Regole:
          - Il movimento è consentito solo al possessore del turno corrente.
          - La destinazione deve essere ortogonalmente adiacente.
          - Entrare nella cella occupata dall'avversario innesca una battaglia
            (segnalato nel campo 'battle' del risultato): è compito del
            chiamante risolvere lo scontro tramite engine.py.
          - Se la destinazione è libera o occupata dal neutrale, viene catturata.
          - La cella di partenza torna NEUTRAL dopo la mossa.

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
        if entity not in self.positions:
            return {"ok": False, "message": f"Entità '{entity.value}' non trovata."}

        if entity != self.current_turn:
            return {
                "ok": False,
                "message": f"Non è il turno di '{entity.value}' (turno di '{self.current_turn.value}').",
            }

        from_pos = self.positions[entity]
        to_row, to_col = to_pos

        if not self.is_adjacent(from_pos, to_pos):
            return {"ok": False, "message": "La destinazione non è adiacente alla posizione corrente."}

        if not (0 <= to_row < self.rows and 0 <= to_col < self.cols):
            return {"ok": False, "message": "Destinazione fuori dalla mappa."}

        dest_cell = self.grid[to_row][to_col]

        # Controlla se è uno scontro diretto
        battle = (dest_cell.occupation == entity.opposite())

        # Libera la cella di partenza
        old_cell = self.grid[from_pos[0]][from_pos[1]]
        old_cell.occupation = NEUTRAL

        # Occupa la destinazione
        captured           = dest_cell.occupation != entity
        strategic_captured = captured and dest_cell.is_strategic
        dest_cell.occupation = entity
        self.positions[entity] = to_pos

        msg = (
            f"[Turno {self.turn}] {entity.value} → ({to_row},{to_col}) "
            f"[{dest_cell.terrain}]"
        )
        if battle:
            msg += " — ⚔ BATTAGLIA!"
        elif strategic_captured:
            msg += " — ★ Punto strategico conquistato!"

        return {
            "ok":                True,
            "message":           msg,
            "captured":          captured,
            "strategic_captured": strategic_captured,
            "battle":            battle,
            "terrain":           dest_cell.terrain,
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
        Suggerisce la cella adiacente che avvicina maggiormente l'entità
        al target (distanza di Manhattan), senza spostare verso celle
        già controllate dalla stessa entità (salvo che non ci siano
        alternative).

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
        candidates: List[Tuple[int, Tuple[int, int]]] = []

        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = from_pos[0] + dr, from_pos[1] + dc
            if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                continue
            cell = self.grid[nr][nc]
            dist = abs(nr - target[0]) + abs(nc - target[1])
            if dist < current_dist and cell.occupation != entity:
                candidates.append((dist, (nr, nc)))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

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
        Controlla se la partita è terminata (un esercito è stato eliminato).

        La battaglia viene risolta esternamente (via engine.py); quando un
        esercito perde, la sua posizione viene rimossa da `self.positions`.

        Returns:
            Il vincitore (PLAYER o AI) se la partita è finita, altrimenti None.
        """
        if PLAYER not in self.positions:
            return AI
        if AI not in self.positions:
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
            "grid": [
                [cell.to_dict() for cell in row]
                for row in self.grid
            ],
            "stats": {
                "player_cells":     self.count_occupied(PLAYER),
                "ai_cells":         self.count_occupied(AI),
                "player_strategic": self.count_strategic_occupied(PLAYER),
                "ai_strategic":     self.count_strategic_occupied(AI),
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
