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

# ══════════════════════════════════════════════════════════════════
# COMPOSIZIONE DELLA MAPPA
#
# Prima le montagne si dipingevano solo nelle prime righe, con densità 0.82:
# il castello IA nasceva dentro una catena montuosa (misurato: 76% di montagna
# sulla riga 0) e quello del giocatore in mezzo alla pianura (90%). Non era il
# seme, era una regola fissa — e regalava a un lato un muro che l'altro non
# aveva. Dalla riga 7 in giù non c'era una montagna in nessuna partita.
#
# Adesso valgono tre regole, e le manopole sono queste.
# ══════════════════════════════════════════════════════════════════

# ── Fiume ──────────────────────────────────────────────────────────
# Uno solo, orizzontale, in mezzo. Il fiume è INVALICABILE (le legioni non
# entrano nelle sue celle): senza guadi taglierebbe la mappa in due e nessuno
# raggiungerebbe più l'altro castello. I guadi sono le posizioni chiave della
# partita, ed è il motivo per cui sono pochi.
RIVER_BAND = 2                  # righe di scarto concesse dalla riga centrale
RIVER_FORDS = (2, 3)            # quanti guadi lascia aperti
RIVER_MEANDER_CHANCE = 0.30     # quanto spesso il corso si sposta di una riga
RIVER_MIN_FORD_GAP = 3          # colonne minime fra un guado e l'altro
RIVER_FORD_EDGE_MARGIN = 2      # niente guadi a ridosso dei bordi della mappa

# ── Montagne ───────────────────────────────────────────────────────
# A grappoli, più probabili al centro ma possibili ovunque: il peso dipende
# solo dalla distanza dalla riga centrale, quindi le due metà ricevono la
# stessa quantità senza doverla imporre.
MOUNTAIN_CLUSTERS = (5, 9)
MOUNTAIN_CENTER_BIAS = 1.7      # più alto = più concentrate al centro
MOUNTAIN_EDGE_FLOOR = 0.10      # probabilità residua ai bordi: mai zero
MOUNTAIN_FILL = 0.68            # quanto è pieno un grappolo

# ── Foreste e paludi ───────────────────────────────────────────────
FOREST_CLUSTERS = (7, 11)
FOREST_FILL = 0.70
SWAMP_NEAR_RIVER = 0.26         # acquitrini sulle sponde
SWAMP_CLUSTERS = (1, 3)         # e qualche pantano lontano dall'acqua
SWAMP_FILL = 0.55

# ── Castelli ───────────────────────────────────────────────────────
# L'anello attorno a ogni castello resta praticabile, uguale per i due lati:
# niente montagne che rallentano l'uscita, niente fiume che la chiude.
CASTLE_CLEAR_RADIUS = 1
CASTLE_CLEAR_TERRAINS = ("Pianura", "Foresta")


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
        """Genera la griglia.

        L'ordine conta: il fiume passa sopra le montagne, le paludi nascono
        sulle sue sponde, e le ultime due passate sono garanzie — l'anello
        libero attorno ai castelli e il controllo che i due castelli si
        raggiungano davvero.
        """
        rng = random.Random(seed)

        self.grid = [
            [Cell(row=r, col=c, terrain="Pianura") for c in range(self.cols)]
            for r in range(self.rows)
        ]

        self._paint_mountains(rng)
        river_cells = self._paint_river(rng)
        self._paint_swamps(rng, river_cells)
        self._paint_forests(rng)
        self._rebalance_terrain_distribution(rng)
        self._ensure_all_terrains_present(rng)
        self._clear_castle_rings(rng)
        self._ensure_castles_connected(rng)
        self._mark_strategic_cells(rng)

    # ──────────────────────────────────────────────────────────
    # PITTURA DEI BIOMI
    # ──────────────────────────────────────────────────────────

    def _castle_cells(self) -> List[Tuple[int, int]]:
        """Dove finiranno i due castelli.

        `_place_armies` gira dopo la generazione, quindi qui le posizioni si
        ricavano dalla stessa formula: sono fisse per costruzione.
        """
        return [(self.rows - 1, self.cols // 2), (0, self.cols // 2)]

    def _castle_ring(self) -> set:
        """Le celle da tenere praticabili: i castelli e quello che li circonda."""
        anello = set()
        for cr, cc in self._castle_cells():
            for dr in range(-CASTLE_CLEAR_RADIUS, CASTLE_CLEAR_RADIUS + 1):
                for dc in range(-CASTLE_CLEAR_RADIUS, CASTLE_CLEAR_RADIUS + 1):
                    r, c = cr + dr, cc + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        anello.add((r, c))
        return anello

    def _row_center_weights(self) -> List[float]:
        """Peso di ogni riga in funzione di quanto è centrale.

        Simmetrico per costruzione — dipende solo da |riga - centro| — quindi
        metà nord e metà sud ricevono la stessa quantità di montagna senza che
        nessuno debba imporlo.
        """
        centro = (self.rows - 1) / 2.0
        pesi = []
        for r in range(self.rows):
            distanza = abs(r - centro) / max(1e-9, centro)
            pesi.append(((1.0 - distanza) ** MOUNTAIN_CENTER_BIAS) + MOUNTAIN_EDGE_FLOOR)
        return pesi

    def _paint_mountains(self, rng: random.Random) -> None:
        """Rilievi a grappoli, più fitti verso il centro della mappa."""
        righe = list(range(self.rows))
        pesi = self._row_center_weights()
        for _ in range(rng.randint(*MOUNTAIN_CLUSTERS)):
            seed_r = rng.choices(righe, weights=pesi, k=1)[0]
            seed_c = rng.randrange(self.cols)
            raggio_r = rng.randint(1, 2)
            raggio_c = rng.randint(1, 3)
            for dr in range(-raggio_r, raggio_r + 1):
                for dc in range(-raggio_c, raggio_c + 1):
                    r, c = seed_r + dr, seed_c + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        if rng.random() < MOUNTAIN_FILL:
                            self.grid[r][c].terrain = "Montagna"

    def _scegli_guadi(self, rng: random.Random) -> set:
        """Le colonne in cui il fiume si interrompe, distanziate fra loro.

        Mai a ridosso del bordo: un guado in penultima colonna lascerebbe
        l'ultima cella d'acqua staccata dal resto — una pozza, non un fiume —
        e regalerebbe un passaggio di lato che nessuno nota.
        """
        primo = min(RIVER_FORD_EDGE_MARGIN, max(0, (self.cols - 1) // 2))
        ultimo = max(primo, self.cols - 1 - RIVER_FORD_EDGE_MARGIN)
        quanti = rng.randint(*RIVER_FORDS)
        guadi: List[int] = []
        for _ in range(quanti * 20):
            if len(guadi) >= quanti:
                break
            colonna = rng.randint(primo, ultimo)
            if all(abs(colonna - g) >= RIVER_MIN_FORD_GAP for g in guadi):
                guadi.append(colonna)
        if not guadi:                       # sorteggio sfortunato: uno serve
            guadi.append(rng.randint(primo, ultimo))
        return set(guadi)

    def _paint_river(self, rng: random.Random) -> List[Tuple[int, int]]:
        """Un fiume solo: orizzontale, in mezzo, con due o tre guadi.

        Serpeggia di una riga alla volta restando nella fascia centrale, così
        è riconoscibile a colpo d'occhio senza essere una linea dritta.
        """
        # Con un numero pari di righe il centro cade fra due: si sorteggia
        # quale delle due, se no il fiume nasce sempre mezza riga più vicino
        # a un castello che all'altro.
        centro_alto = (self.rows - 1) // 2
        centro_basso = self.rows // 2
        riga = rng.choice((centro_alto, centro_basso)) + rng.randint(-1, 1)
        banda_min = centro_alto - RIVER_BAND
        banda_max = centro_basso + RIVER_BAND
        guadi = self._scegli_guadi(rng)
        celle: List[Tuple[int, int]] = []

        for c in range(self.cols):
            riga = min(banda_max, max(banda_min, riga))
            if c not in guadi:
                self.grid[riga][c].terrain = "Fiume"
                celle.append((riga, c))
            if rng.random() < RIVER_MEANDER_CHANCE:
                riga += rng.choice([-1, 1])

        return self._asciuga_pozze(celle)

    def _asciuga_pozze(self, celle: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
        """Toglie le celle d'acqua rimaste sole: sono pozze, non fiume.

        Rete di sicurezza per qualunque combinazione di guadi e meandri lasci
        un frammento staccato dal corso principale.
        """
        rimaste = set(celle)
        cambiato = True
        while cambiato:
            cambiato = False
            for r, c in list(rimaste):
                vicine = {
                    (r + dr, c + dc)
                    for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                    if (dr, dc) != (0, 0)
                }
                if not (vicine & rimaste):
                    rimaste.discard((r, c))
                    self.grid[r][c].terrain = "Pianura"
                    cambiato = True
        return sorted(rimaste)

    def _paint_swamps(self, rng: random.Random, river_cells: List[Tuple[int, int]]) -> None:
        """Acquitrini sulle sponde, e qualche pantano anche lontano dall'acqua."""
        for rr, cc in river_cells:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    r, c = rr + dr, cc + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        cella = self.grid[r][c]
                        if cella.terrain == "Pianura" and rng.random() < SWAMP_NEAR_RIVER:
                            cella.terrain = "Palude"

        for _ in range(rng.randint(*SWAMP_CLUSTERS)):
            seed_r = rng.randrange(self.rows)
            seed_c = rng.randrange(self.cols)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    r, c = seed_r + dr, seed_c + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        cella = self.grid[r][c]
                        if cella.terrain == "Pianura" and rng.random() < SWAMP_FILL:
                            cella.terrain = "Palude"

    def _paint_forests(self, rng: random.Random) -> None:
        """Boschi a grappoli, su tutta la mappa.

        Prima stavano solo nella fascia centrale: era un'altra regola fissa
        che rendeva le due metà diverse.
        """
        for _ in range(rng.randint(*FOREST_CLUSTERS)):
            seed_r = rng.randrange(self.rows)
            seed_c = rng.randrange(self.cols)
            raggio_r = rng.randint(1, 2)
            raggio_c = rng.randint(1, 3)
            for dr in range(-raggio_r, raggio_r + 1):
                for dc in range(-raggio_c, raggio_c + 1):
                    r, c = seed_r + dr, seed_c + dc
                    if 0 <= r < self.rows and 0 <= c < self.cols:
                        cella = self.grid[r][c]
                        if cella.terrain == "Pianura" and rng.random() < FOREST_FILL:
                            cella.terrain = "Foresta"

    # ──────────────────────────────────────────────────────────
    # GARANZIE
    # ──────────────────────────────────────────────────────────

    def _clear_castle_rings(self, rng: random.Random) -> None:
        """Attorno ai due castelli solo terreno praticabile, alle stesse condizioni.

        È la regola che impedisce il ritorno del vecchio squilibrio: nessuno
        dei due si sveglia con una catena montuosa in cortile e l'altro no.
        """
        for r, c in self._castle_ring():
            cella = self.grid[r][c]
            if cella.terrain in CASTLE_CLEAR_TERRAINS:
                continue
            cella.terrain = "Foresta" if rng.random() < 0.25 else "Pianura"

    def _percorso_esiste(self, partenza: Tuple[int, int], arrivo: Tuple[int, int]) -> bool:
        """Si va da una cella all'altra senza attraversare il fiume?"""
        if partenza == arrivo:
            return True
        visitate = {partenza}
        coda = [partenza]
        while coda:
            r, c = coda.pop()
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                nr, nc = r + dr, c + dc
                if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                    continue
                if (nr, nc) in visitate:
                    continue
                if self.grid[nr][nc].terrain == "Fiume":
                    continue
                if (nr, nc) == arrivo:
                    return True
                visitate.add((nr, nc))
                coda.append((nr, nc))
        return False

    def _ensure_castles_connected(self, rng: random.Random) -> None:
        """Se il fiume ha chiuso la mappa, apre un varco.

        Il fiume è invalicabile: un sorteggio sfortunato — o una passata di
        ribilanciamento — potrebbe sigillare il corso e rendere la partita
        ingiocabile. Qui si controlla e, se serve, si toglie l'acqua da una
        colonna intera.
        """
        sud, nord = self._castle_cells()
        if self._percorso_esiste(sud, nord):
            return

        colonne = list(range(self.cols))
        rng.shuffle(colonne)
        for colonna in colonne:
            tolte = [
                (r, colonna) for r in range(self.rows)
                if self.grid[r][colonna].terrain == "Fiume"
            ]
            for r, c in tolte:
                self.grid[r][c].terrain = "Pianura"
            if self._percorso_esiste(sud, nord):
                return

    def _count_terrains(self) -> Dict[str, int]:
        counts = {terrain: 0 for terrain in TERRAIN_TYPES}
        for row in self.grid:
            for cell in row:
                counts[cell.terrain] += 1
        return counts

    def _random_cells_of_terrain(
        self,
        terrain: str,
        rng: random.Random,
        escluse: Optional[set] = None,
    ) -> List[Tuple[int, int]]:
        """Celle di quel terreno, mescolate. `escluse` protegge chi non va toccato."""
        vietate = escluse or set()
        coords = [
            (cell.row, cell.col)
            for row in self.grid
            for cell in row
            if cell.terrain == terrain
            and not cell.is_castle
            and (cell.row, cell.col) not in vietate
        ]
        rng.shuffle(coords)
        return coords

    def _rebalance_terrain_distribution(self, rng: random.Random) -> None:
        """Ribilancia i biomi per evitare mappe estreme e mantenere varietà.

        Il Fiume resta fuori da questa passata: è disegnato una volta sola,
        orizzontale e con i suoi guadi, e spostarne le celle a caso avrebbe
        rimesso pozze d'acqua sparse in giro. Le sue soglie sono larghe apposta,
        così né il taglio né il riempimento lo toccano mai.
        """
        total = self.rows * self.cols
        min_ratio = {
            "Pianura": 0.22,
            "Foresta": 0.11,
            "Montagna": 0.09,
            "Fiume": 0.03,
            "Palude": 0.06,
        }
        max_ratio = {
            "Pianura": 0.62,
            "Foresta": 0.34,
            "Montagna": 0.30,
            "Fiume": 0.16,
            "Palude": 0.20,
        }
        protette = self._castle_ring()

        min_counts = {k: max(1, int(total * v)) for k, v in min_ratio.items()}
        max_counts = {k: max(min_counts[k], int(total * v)) for k, v in max_ratio.items()}

        counts = self._count_terrains()

        # Riduci eccessi riconvertendo in Pianura
        for terrain in ("Palude", "Montagna", "Foresta"):
            while counts[terrain] > max_counts[terrain]:
                candidates = self._random_cells_of_terrain(terrain, rng, protette)
                if not candidates:
                    break
                r, c = candidates[0]
                self.grid[r][c].terrain = "Pianura"
                counts[terrain] -= 1
                counts["Pianura"] += 1

        # Colma carenze attingendo da Pianura (o Foresta come fallback)
        for terrain in ("Montagna", "Foresta", "Palude"):
            while counts[terrain] < min_counts[terrain]:
                donors = self._random_cells_of_terrain("Pianura", rng, protette)
                if not donors:
                    donors = self._random_cells_of_terrain("Foresta", rng, protette)
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
                    donors.extend(self._random_cells_of_terrain(terrain, rng, protette))
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

            protette = self._castle_ring()
            donors = self._random_cells_of_terrain("Pianura", rng, protette)
            if not donors:
                donors = [
                    (cell.row, cell.col)
                    for row in self.grid
                    for cell in row
                    if not cell.is_castle and (cell.row, cell.col) not in protette
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

    def mine_terrains(self, entity: Occupation) -> List[str]:
        """Terreno di ogni miniera controllata dall'entità.

        Serve all'economia: una miniera non vale l'altra, dipende da dove è
        scavata. L'ordine è quello di scansione della griglia, non quello di
        costruzione: chi legge questa lista non deve farci conto.
        """
        return [
            self.grid[r][c].terrain
            for r in range(self.rows)
            for c in range(self.cols)
            if self.grid[r][c].occupation == entity and self.grid[r][c].is_mine
        ]

    def count_mines(self, entity: Occupation) -> int:
        """Numero di miniere controllate dall'entità."""
        return len(self.mine_terrains(entity))

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
