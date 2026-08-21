"""
War Advisor - GameSession

Gestisce una partita dove l'obiettivo è conquistare il castello avversario.
Le armate sul campo possono lasciare guarnigioni per rallentare l'assalto e,
quando perdono uno scontro, si ritirano al proprio castello invece di sparire.
"""

import random
import time
from enum import Enum
from collections import Counter, deque
from typing import Any, Dict, List, Optional, Tuple

from engine import aggregate_army, apply_modifiers, compute_ranking, euclidean_distance
from gamecore.economy import (
    MINE_TILES_PER_SLOT,
    MINE_YIELD_PER_ROUND,
    STARTING_GRUX,
    available_mine_slots,
    get_unit_costs,
)
from gamecore.maps import GameMap, Occupation
from gamecore.session import abilities as ab
from gamecore.session.abilities import DOMAIN_ENGINEERING_ID, build_default_ability_states
from gamecore.session.black_market import BlackMarketState
from gamecore.session.ai_core.ai_builder import (
    build_ai_army,
    build_ai_policy,
    get_ai_difficulty_labels,
    normalize_ai_difficulty,
)
from gamecore.session.ai_core.ai_easy_difficulty import AI_EASY_ID
from gamecore.session.ai_core import ai_doctrine
from gamecore.session.in_game_advisor import build_in_game_advisor_payload
from gamecore.session.movement_points import MovementPointsSystem
from gamecore.session import troop_condition as tc
from gamecore.session import weather_cycle as wc

# [BALANCE-LAYER] Correzioni di bilanciamento truppe (ruolo d'assedio
# dell'artiglieria, guaritori che assorbono perdite). Se il file non c'è, il
# gioco gira con i numeri grezzi del motore: ogni uso è protetto da un
# controllo su `balance`.
try:
    from gamecore import troop_balance as balance
except ImportError:                                           # layer rimosso
    balance = None

try:
    from debug.strength_debug import log_strength_debug
except Exception:
    def log_strength_debug(event: str, payload: Dict[str, Any]) -> None:
        return

try:
    from debug.battle_log_capture import create_battle_log_capture
except Exception:
    def create_battle_log_capture(session: Any = None) -> List[str]:
        return []

PLAYER = Occupation.PLAYER
AI = Occupation.AI

AI_LEGION_NAMES = [
    "Falange Nera",
    "Corvo di Ferro",
    "Lupi Scarlatti",
    "Ariete d'Acciaio",
    "Ombre del Nord",
    "Legione del Drago",
    "Spade Vermiglie",
    "Guardia Ferrea",
    "Orda Grigia",
    "Legione della Tempesta",
    "Artigli Neri",
    "Falce Cremisi",
    "Legione Spezzata",
    "Vento di Guerra",
    "Fauci d'Acciaio",
]

PLAYER_CONTROL_MODE_OPTIONS = ["orders", "manual"]
PLAYER_CONTROL_MODES = set(PLAYER_CONTROL_MODE_OPTIONS)
PLAYER_MOVEMENT_ORDER_OPTIONS = [
    "advance_castle",
    "engage_ai",
    "expand_front",
    "defend_castle",
    "hold",
]
PLAYER_MOVEMENT_ORDERS = set(PLAYER_MOVEMENT_ORDER_OPTIONS)
PLAYER_BUILD_ORDER_OPTIONS = [
    "balanced",
    "economy",
    "fortify",
    "garrison",
    "none",
]
PLAYER_BUILD_ORDERS = set(PLAYER_BUILD_ORDER_OPTIONS)

CASTLE_BASE_HP = 220
CASTLE_HP_PER_UNIT = 8

# ── Difesa del castello ────────────────────────────────────────────
# Blocco isolato apposta: è la manopola unica per bilanciare gli assedi,
# pensata per essere rivista senza toccare il resto del motore.
#
# Il castello si difende in due modi indipendenti, entrambi con un tetto:
#   1. PRESIDI sulla cella → al massimo 4, altrimenti bastava impilare truppe
#      per rendere il castello imprendibile;
#   2. FORTIFICAZIONI sul castello → al massimo 4 livelli, ognuno taglia i
#      danni in percentuale.
# Le legioni ferme sul castello NON contano come difesa: erano cumulabili
# senza limite e rendevano l'assedio impossibile.
#
# La fortificazione del castello è una meccanica a sé: sulle celle normali
# le fortificazioni continuano a funzionare come prima (nessun tetto, bonus
# calcolato in `_legion_battle_strength`).
CASTLE_MAX_FORTIFICATION_LEVEL = 4        # tetto di costruzioni sul castello
CASTLE_FORT_DAMAGE_REDUCTION_PER_LEVEL = 0.10   # -10% danni per livello (max -40%)
CASTLE_MAX_GARRISON_UNITS = 4             # tetto di presidi sulla cella del castello
CASTLE_DEFENDER_WEIGHT = 0.50             # quanto vale in difesa una truppa di presidio
CASTLE_DEFENSE_BASE = 44.0                # difesa di un castello completamente sguarnito
# La riserva non difende: finché contava, formare una legione toglieva difesa
# al castello e il gioco puniva chi giocava invece di accumulare truppe.

# Danno da assedio: dipende dal RAPPORTO forza/difesa, non dalla differenza.
# Con la differenza, oltre le ~10 unità l'assalto saturava sempre il tetto e
# da lì in poi né l'esercito attaccante né la difesa cambiavano più nulla.
CASTLE_DAMAGE_MAX = 65.0                  # danno massimo per assalto
CASTLE_DAMAGE_MIN = 8                     # pavimento: garantisce che il castello cada sempre
CASTLE_DAMAGE_HALF_RATIO = 15.0           # rapporto forza/difesa a metà del danno massimo

# ── Presidi e legioni sulle celle normali ──────────────────────────
# I presidi non si impilano più senza freno: quanti ne regge una cella
# dipende da quanto è fortificata. Serve a due cose insieme — toglie il
# muro di truppe su una casella qualsiasi e dà alle fortificazioni uno
# scopo oltre al bonus difensivo, creando un ordine di costruzione.
CELL_GARRISON_BASE_CAPACITY = 1           # presidi ospitabili senza fortificazioni
CELL_GARRISON_PER_FORT_LEVEL = 1          # presidi in più per ogni livello costruito
CELL_MAX_GARRISON_UNITS = 4               # tetto assoluto, fortificazioni comprese

# Tetto al numero di legioni contemporanee. Senza, si creavano decine di
# legioni da una unità: conquista a sciame e legioni accatastate sulla
# stessa cella. L'IA ha già il proprio limite nei file di difficoltà.
MAX_LEGIONS_PER_SIDE = 4

# Unità minime perché una legione IA in più sia un reparto e non un drappello.
# Misurato: spezzare l'esercito in quattro gruppetti da tre rende l'IA più
# debole, non più minacciosa — contro le mura ognuno fa il danno minimo.
# L'accerchiamento vale solo con reparti veri dietro.
AI_MIN_UNITS_PER_LEGION = 6

# Sotto questo esercito l'IA non mette da parte un grux per la ricerca: prima
# due reparti pieni, poi la tecnologia. Vedi `_ai_research_savings`.
AI_RESEARCH_MIN_ARMY = 2 * AI_MIN_UNITS_PER_LEGION

# Caselle massime in un ordine di cattura d'area. Non è un limite tecnico: una
# legione che deve prendere mezza mappa non torna più indietro, e l'ordine
# diventa impossibile da leggere sulla carta.
CAPTURE_AREA_MAX_CELLS = 40

# ── Peso degli attributi nel valore di combattimento ───────────────
# Erano scritti a mano dentro `_unit_battle_value`. Stanno qui perché li usa
# anche il calcolo dell'effetto meteo sulla singola unità: i due conti devono
# per forza pesare gli attributi allo stesso modo, altrimenti il fattore meteo
# non corrisponderebbe allo scarto reale sul valore.
UNIT_BATTLE_WEIGHTS: Dict[str, float] = {
    "U1_attack": 24.0,
    "U2_defense": 20.0,
    "U3_mobility": 12.0,
    "U4_stealth": 10.0,
    "U5_discipline": 14.0,
    "U6_terrain_adapt": 10.0,
    "U7_range_power": 8.0,
    "U8_support": 6.0,
}

LEGION_TYPE_ARMY = "army"
LEGION_TYPE_MINING = "mining"
LEGION_TYPE_CONSTRUCTION = "construction"
LEGION_TYPES = (LEGION_TYPE_ARMY, LEGION_TYPE_MINING, LEGION_TYPE_CONSTRUCTION)
LEGION_TYPE_LABELS = {
    LEGION_TYPE_ARMY: "Esercito",
    LEGION_TYPE_MINING: "Mineraria",
    LEGION_TYPE_CONSTRUCTION: "Costruzione",
}


class SessionState(str, Enum):
    ACTIVE    = "active"
    GAME_OVER = "game_over"


class GameSession:
    """
    Sessione di gioco completa.

    Attributi principali:
        player_units        — ID unità del giocatore
        player_strategy_id  — ID strategia confermata
        player_army         — vettore raw del giocatore
        player_modified     — vettore modificato per il terreno iniziale
        player_troop_status — stato truppe del giocatore

        ai_units            — ID unità dell'IA (scelte da ai_builder)
        ai_strategy_id/name — strategia ottimale dell'IA
        ai_army             — vettore raw dell'IA
        ai_modified         — vettore modificato per il terreno IA
        ai_troop_status     — stato truppe IA (sempre "Fresche" all'inizio)

        weather             — condizione meteo globale (opzionale)
        game_map            — istanza GameMap
        state               — SessionState corrente
        winner              — "player" | "ai" | None
        battle_log          — registro cronologico degli scontri
    """

    def __init__(
        self,
        *,
        # Player
        player_units: List[str],
        player_strategy_id: str,
        player_army: Dict[str, float],
        player_modified: Dict[str, float],
        player_troop_status: Optional[str],
        player_budget: int,
        player_army_cost: int,
        # AI (output di ai_builder.build_ai_army)
        ai_data: Dict[str, Any],
        # Ambiente
        weather: Optional[str],
        # Dati engine
        data: Dict[str, Any],
        player_home_terrain: str,
        # Mappa
        map_seed: Optional[int] = None,
        ai_difficulty: str = AI_EASY_ID,
    ) -> None:
        # Mappa meteo arricchita con le combinazioni ciclo × meteo. È una copia:
        # registrarle nel dizionario globale le farebbe comparire nel selettore
        # meteo della schermata iniziale, che deve restare con le sue 4 voci.
        self.data = wc.data_with_combined_weather(data)
        self.units_map = {unit["id"]: unit for unit in self.data["units"]}
        self.strategies_map = {strategy["id"]: strategy for strategy in self.data["strategies"]}
        self.unit_costs = get_unit_costs(self.data["units"])
        self.player_home_terrain = player_home_terrain
        self.ai_home_terrain = "Montagna"

        # --- Giocatore ---
        self.player_units         = player_units
        self.player_strategy_id   = player_strategy_id
        self.player_army          = player_army
        self.player_modified      = player_modified
        self.player_troop_status  = player_troop_status
        self.player_army_cost     = player_army_cost

        # --- IA ---
        self.ai_units         = ai_data["units"]
        self.ai_strategy_id   = ai_data["strategy"]["id"]
        self.ai_strategy_name = ai_data["strategy"]["name"]
        self.ai_army          = ai_data["army_vector"]
        self.ai_modified      = ai_data["modified_vector"]
        self.ai_troop_status  = ai_data["troop_status"]
        self.ai_army_cost     = ai_data.get("army_cost", 0)

        # Condizione della riserva nel castello. Le legioni la ereditano alla
        # nascita e ci rifondono la propria quando vengono richiamate: senza,
        # richiamare e riformare una legione sarebbe un azzeramento gratuito
        # della stanchezza. Parte dallo stato scelto nella schermata iniziale,
        # così quella scelta continua a contare anche in partita.
        self.reserve_condition: Dict[Occupation, Dict[str, Any]] = {
            PLAYER: tc.new_condition(player_troop_status),
            AI: tc.new_condition(self.ai_troop_status),
        }

        # --- Ambiente ---
        # Due assi che si sommano: ciclo (Giorno/Notte) e meteo (Sereno/Pioggia/
        # Nebbia). `self.weather` resta la chiave passata all'engine, ora composta,
        # così ogni punto che la usava continua a funzionare senza modifiche.
        self.day_cycle, self.weather_base = wc.split_key(weather)
        self.weather = wc.combined_key(self.day_cycle, self.weather_base)
        self.weather_rng = random.Random((map_seed or 0) * 977 + 13)
        self.turns_to_weather_change = wc.next_change_delay(self.weather_rng)

        # --- Legioni (Nuovo Sistema) ---
        self.player_legions: Dict[str, Dict[str, Any]] = {}
        self.ai_legions: Dict[str, Dict[str, Any]] = {}
        self.next_legion_id: int = 1
        self.ai_legion_respawn_delay_turns: int = 2
        self.ai_last_legion_loss_turn: Optional[int] = None

        # --- Mappa ---
        self.game_map: GameMap = GameMap(seed=map_seed)

        # --- Stato ---
        self.state:      SessionState  = SessionState.ACTIVE
        self.winner:     Optional[str] = None
        self.battle_log: List[str]     = create_battle_log_capture(self)
        # [ENDGAME-STATS] Due numeri che il gioco non teneva da nessuna parte
        # e che non si possono ricostruire a posteriori: quando è cominciata
        # la partita e quante truppe ha perso ciascuno. Servono alla
        # schermata di fine partita; li legge solo `to_dict`, nessuna
        # formula di gioco li guarda. Rimozione: grep ENDGAME-STATS.
        self.started_at: float = time.time()
        self.troops_lost: Dict[Occupation, int] = {PLAYER: 0, AI: 0}
        self.grux_balance: Dict[Occupation, int] = {
            PLAYER: player_budget,
            AI: ai_data.get("remaining_grux", STARTING_GRUX - self.ai_army_cost),
        }
        self.base_fortification_cost: int = 45
        # Le ricerche dell'IA scorrono più in fretta man mano che la difficoltà
        # sale: le partite dure durano meno turni, e a tempi pieni l'IA forte
        # finirebbe con meno abilità di quella debole.
        _ai_difficulty = normalize_ai_difficulty(ai_difficulty)
        self.ability_states: Dict[Occupation, Dict[str, Any]] = {
            PLAYER: build_default_ability_states(),
            AI: build_default_ability_states(ab.ai_research_scale(_ai_difficulty)),
        }
        # Il banco del Mercato Nero esiste da subito ma resta chiuso finché
        # l'abilità non è sbloccata: nessuna offerta viene generata prima.
        self.black_market: Dict[Occupation, BlackMarketState] = {
            PLAYER: BlackMarketState(),
            AI: BlackMarketState(),
        }
        self.black_market_rng = random.Random((map_seed or 0) + 7717)
        self.recruit_cooldown_turns: int = 2
        self.last_recruit_turn: Dict[Occupation, Optional[int]] = {
            PLAYER: None,
            AI: None,
        }
        # [DEBUG-MODULE] Flag del kill switch IA, pilotato da gamecore/debug_module.
        # Senza il modulo resta False per sempre e il gioco si comporta come se
        # non esistesse. Rimozione: gamecore/debug_module/README.md
        self.debug_ai_kill_switch: bool = False
        self.ai_difficulty: str = normalize_ai_difficulty(ai_difficulty)
        self.ai_policy = build_ai_policy(self.ai_difficulty, seed=map_seed)
        self.ai_policy_seed = map_seed
        # La dottrina è il "come manovra", separata dal "cosa vuole" dei profili
        # di difficoltà: corsie, aggiramenti, giri larghi e attese.
        self.ai_doctrine = ai_doctrine.for_difficulty(self.ai_difficulty, seed=map_seed)
        self.movement_system = MovementPointsSystem()
        self.player_control_mode: str = "manual"
        self.player_orders: Dict[str, str] = {
            "movement_order": "advance_castle",
            "build_order": "balanced",
        }
        self.player_order_memory: Dict[str, Any] = {
            "last_direction": None,
            "straight_streak": 0,
        }
        self.player_auto_recruit: Dict[str, Any] = {
            "enabled": False,
            "unit_id": None,
            "unit_name": None,
            "turns_total": 0,
            "turns_remaining": 0,
            "attempted_turns": 0,
            "successful_recruits": 0,
            "last_result": "inactive",
        }
        # Rimosso il vecchio sistema a ordini. Il turno avanza con execute_turn() e muove le legioni.
        self.castle_hp_max: Dict[Occupation, int] = self._build_castle_hp_pool()
        self.castle_hp: Dict[Occupation, int] = dict(self.castle_hp_max)

    def _build_castle_hp_pool(self) -> Dict[Occupation, int]:
        player_max = CASTLE_BASE_HP + (len(self.player_units) * CASTLE_HP_PER_UNIT)
        ai_max = CASTLE_BASE_HP + (len(self.ai_units) * CASTLE_HP_PER_UNIT)
        return {
            PLAYER: player_max,
            AI: ai_max,
        }

    def _ai_mine_income_multiplier(self) -> float:
        """Moltiplicatore sul rendimento delle miniere IA (vantaggio di difficoltà)."""
        getter = getattr(self.ai_policy, "mine_income_multiplier", None)
        if callable(getter):
            return max(1.0, float(getter()))
        return 1.0

    def _mine_income_for_count(self, mine_count: int, entity: Occupation = PLAYER) -> int:
        """Rendimento miniere a bande: pieno early, decrescente in late game."""
        if mine_count <= 0:
            return 0

        tier_1 = min(mine_count, 4)
        tier_2 = min(max(0, mine_count - 4), 4)
        tier_3 = min(max(0, mine_count - 8), 4)
        tier_4 = max(0, mine_count - 12)

        income = (
            (tier_1 * MINE_YIELD_PER_ROUND)
            + (tier_2 * int(round(MINE_YIELD_PER_ROUND * 0.8)))
            + (tier_3 * int(round(MINE_YIELD_PER_ROUND * 0.6)))
            + (tier_4 * int(round(MINE_YIELD_PER_ROUND * 0.4)))
        )

        if entity == AI:
            income = int(round(income * self._ai_mine_income_multiplier()))

        # [ABILITY-EFFECTS] Linee di Rifornimento: meno perdite per strada.
        supply = self._ability_economy_factor(entity, ab.ECO_MINE_INCOME)
        if supply != 1.0:
            income = int(round(income * supply))
        return income

    def _compute_castle_damage(self, attacker_strength: float, defender_score: float) -> int:
        """Danno inflitto al castello, in funzione del rapporto forza/difesa.

        Curva satura: più truppe porti all'assalto, più danno fai, ma con
        rendimenti decrescenti; più difesa c'è, meno ne fai. Il tetto e il
        pavimento restano gli estremi, non il caso normale.
        """
        # [BALANCE-LAYER] Curva d'assedio del layer: la versione qui sotto
        # premiava troppo poco chi porta un esercito d'assedio vero.
        if balance is not None:
            return balance.castle_damage(attacker_strength, defender_score, CASTLE_DAMAGE_MIN)

        ratio = attacker_strength / max(1.0, defender_score)
        intensity = ratio / (ratio + CASTLE_DAMAGE_HALF_RATIO)
        raw_damage = CASTLE_DAMAGE_MAX * intensity
        return max(CASTLE_DAMAGE_MIN, min(int(CASTLE_DAMAGE_MAX), int(round(raw_damage))))

    # ──────────────────────────────────────────────────────────
    # LEGIONI
    # ──────────────────────────────────────────────────────────

    def _get_free_spawn_cell(self, entity: Occupation, start_pos: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """Trova una cella adiacente libera per spawnare una legione (o il castello stesso se vuoto)."""
        r, c = start_pos
        cell = self.game_map.get_cell(r, c)

        own_legions = self.player_legions if entity == PLAYER else self.ai_legions
        castle_has_legion = any(tuple(leg.get("pos", ())) == (r, c) for leg in own_legions.values())
        if not castle_has_legion and cell and cell.terrain != "Fiume":
            return (r, c)

        # Cerca adiacenti liberi
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            adj = self.game_map.get_cell(nr, nc)
            if adj and adj.terrain != "Fiume":
                if not any(tuple(leg.get("pos", ())) == (nr, nc) for leg in own_legions.values()):
                    return (nr, nc)

        # Castello e adiacenti tutti presi: allarga la ricerca invece di
        # accettare una sovrapposizione, che è proprio ciò che vogliamo evitare.
        return self._free_cell_for(entity, (r, c))

    def _normalize_capture_area(
        self,
        cells: Optional[List[Any]],
    ) -> List[Tuple[int, int]]:
        """Valida l'area di cattura e la riduce a celle sensate.

        Si buttano via i doppioni, le celle fuori mappa e quelle già nostre:
        un ordine di cattura su roba che possediamo già è solo tempo perso.
        """
        if not cells:
            return []

        pulite: List[Tuple[int, int]] = []
        viste = set()
        for raw in cells:
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                raise ValueError("Area di cattura non valida: servono coppie [riga, colonna].")
            pos = (int(raw[0]), int(raw[1]))
            if pos in viste:
                continue
            cell = self.game_map.get_cell(*pos)
            if cell is None:
                raise ValueError(f"La cella {pos} è fuori dalla mappa.")
            viste.add(pos)
            if cell.occupation == PLAYER:
                continue
            pulite.append(pos)

        if len(pulite) > CAPTURE_AREA_MAX_CELLS:
            raise ValueError(
                f"Area troppo grande: {len(pulite)} caselle da conquistare, "
                f"il massimo è {CAPTURE_AREA_MAX_CELLS}."
            )
        return pulite

    def create_player_legion(
        self,
        name: str,
        units_dict: Dict[str, int],
        target: Optional[Tuple[int, int]],
        legion_type: str = LEGION_TYPE_ARMY,
        capture_area: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        if legion_type not in LEGION_TYPES:
            raise ValueError(f"Tipo legione non valido: {legion_type}")

        # O una destinazione o un'area, mai le due cose insieme: sono due ordini
        # diversi e la legione ne può eseguire uno solo.
        area = self._normalize_capture_area(capture_area)
        if area and target is not None:
            raise ValueError(
                "Scegli una destinazione oppure un'area da catturare, non entrambe."
            )
        if capture_area and not area:
            raise ValueError("Nell'area selezionata non c'è niente da conquistare: è già tua.")

        if len(self.player_legions) >= MAX_LEGIONS_PER_SIDE:
            raise ValueError(
                f"Hai già {MAX_LEGIONS_PER_SIDE} legioni in campo, il massimo consentito: "
                f"richiamane una prima di formarne un'altra."
            )

        # Verifica disponibilità truppe nella riserva
        from collections import Counter
        reserve_counts = Counter(self.player_units)
        
        for uid, qty in units_dict.items():
            if reserve_counts.get(uid, 0) < qty:
                raise ValueError(f"Non hai abbastanza unità di tipo {uid} nel castello.")
                
        # Rimuovi le truppe dalla riserva
        legion_units = []
        for uid, qty in units_dict.items():
            for _ in range(qty):
                self.player_units.remove(uid)
                legion_units.append(uid)
                
        # Spawn position
        castle_pos = self.game_map.castle_positions[PLAYER]
        spawn_pos = self._get_free_spawn_cell(PLAYER, castle_pos) or castle_pos
            
        legion_id = f"L_{self.next_legion_id}"
        self.next_legion_id += 1
        
        # Con un'area assegnata la prima meta è la casella più vicina da prendere:
        # da lì in poi ci pensa `_refresh_capture_area` a passare alla successiva.
        if area:
            target = min(area, key=lambda pos: self._order_distance(spawn_pos, pos))

        self.player_legions[legion_id] = {
            "id": legion_id,
            "name": name,
            "units": legion_units,
            "pos": spawn_pos,
            "target": target,
            "capture_area": [list(pos) for pos in area],
            "legion_type": legion_type,
            # Nasce con la strategia generale, poi la si cambia per legione.
            "strategy_id": self.player_strategy_id,
            # Eredita la condizione della riserva da cui è stata formata.
            "condition": tc.new_condition(
                fatigue=self.reserve_condition[PLAYER]["fatigue"],
                morale=self.reserve_condition[PLAYER]["morale"],
                veteran=self.reserve_condition[PLAYER]["veteran"],
                victories=self.reserve_condition[PLAYER].get("victories", 0),
            ),
            "path": [],
            "path_step": 0,
            "movement": self.movement_system.export_legion_state(
                self._legion_movement_key(PLAYER, legion_id)
            ),
        }

        type_label = LEGION_TYPE_LABELS[legion_type]
        self.battle_log.append(
            f"⚔️ PLAYER addestra la legione '{name}' ({type_label}) e la invia verso "
            f"{target if target else 'attesa'}."
        )
        
        # Aggiorna controllo mappa
        cell = self.game_map.get_cell(*spawn_pos)
        if cell and cell.occupation != PLAYER:
            cell.occupation = PLAYER
            
        return {
            "ok": True,
            "message": f"Legione {name} creata",
            "session": self.to_dict()
        }

    def recall_player_legion(self, legion_id: str) -> Dict[str, Any]:
        """Richiama una legione PLAYER: le sue unità tornano istantaneamente in riserva."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        legion = self.player_legions.get(legion_id)
        if legion is None:
            raise ValueError(f"Legione non trovata: {legion_id}")

        name = legion.get("name", legion_id)
        legion_units = legion.get("units", [])
        # La condizione va fusa PRIMA di versare le truppe in riserva, così la
        # media pesa sulla riserva com'era: le truppe stanche che rientrano
        # stancano la riserva, e riformare la legione non azzera nulla.
        stato = self._legion_troop_status(PLAYER, legion)
        self._merge_legion_into_reserve(PLAYER, legion)
        self.player_units.extend(legion_units)
        del self.player_legions[legion_id]

        log_entry = (
            f"[Turno {self.game_map.turn}] 🏳 PLAYER: Legione '{name}' richiamata "
            f"— {len(legion_units)} unità ({stato}) tornano in riserva."
        )
        self.battle_log.append(log_entry)

        return {
            "ok": True,
            "message": log_entry,
            "session": self.to_dict()
        }

    def retarget_player_legion(self, legion_id: str, target: Tuple[int, int]) -> Dict[str, Any]:
        """Assegna una nuova destinazione a una legione PLAYER già in campo."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        legion = self.player_legions.get(legion_id)
        if legion is None:
            raise ValueError(f"Legione non trovata: {legion_id}")

        target = (int(target[0]), int(target[1]))
        if self.game_map.get_cell(*target) is None:
            raise ValueError("Cella di destinazione fuori dai limiti della mappa.")

        legion["target"] = target
        # Una destinazione annulla l'ordine di cattura: sono due ordini diversi
        # e la legione ne esegue uno solo, anche a legione già in campo.
        area_annullata = len(legion.get("capture_area") or [])
        legion["capture_area"] = []
        name = legion.get("name", legion_id)

        log_entry = (
            f"[Turno {self.game_map.turn}] 🧭 PLAYER: Legione '{name}' ridiretta verso {target}."
        )
        if area_annullata:
            log_entry += f" Ordine di cattura annullato ({area_annullata} caselle)."
        self.battle_log.append(log_entry)

        return {
            "ok": True,
            "message": log_entry,
            "session": self.to_dict()
        }

    def set_legion_capture_area(self, legion_id: str, cells: List[Any]) -> Dict[str, Any]:
        """Assegna un nuovo ordine di cattura d'area a una legione già in campo."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        legion = self.player_legions.get(legion_id)
        if legion is None:
            raise ValueError(f"Legione non trovata: {legion_id}")

        area = self._normalize_capture_area(cells)
        if not area:
            raise ValueError("Nell'area selezionata non c'è niente da conquistare: è già tua.")

        current_pos = tuple(legion.get("pos", ()))
        legion["capture_area"] = [list(pos) for pos in area]
        # La prima meta è la più vicina: l'ordine parte da dove si trova adesso.
        if len(current_pos) == 2:
            legion["target"] = list(min(area, key=lambda pos: self._order_distance(current_pos, pos)))

        name = legion.get("name", legion_id)
        log_entry = (
            f"[Turno {self.game_map.turn}] 🗺 PLAYER: Legione '{name}' riceve l'ordine di "
            f"catturare {len(area)} caselle."
        )
        self.battle_log.append(log_entry)

        return {"ok": True, "message": log_entry, "session": self.to_dict()}

    def _ai_desired_legion_count(self) -> int:
        """Quante legioni l'IA vuole in campo adesso (profilo di difficoltà + situazione)."""
        max_getter = getattr(self.ai_policy, "max_legions", None)
        max_legions = max(1, int(max_getter())) if callable(max_getter) else 1
        # Stesso tetto del player: i profili di difficoltà stanno già sotto,
        # ma la regola non deve dipendere da come sono tarati.
        # La manovra può volerne più della difesa: con una legione sola non si
        # accerchia nessuno, e l'accerchiamento è ciò che distingue i profili
        # alti. Il tetto di gioco resta comunque l'ultima parola.
        doctrine_wanted = self.ai_doctrine.offensive_legions(self.game_map.turn)
        max_legions = min(MAX_LEGIONS_PER_SIDE, max(max_legions, doctrine_wanted))
        if max_legions < 2:
            return 1

        min_getter = getattr(self.ai_policy, "second_legion_min_units", None)
        min_units = max(2, int(min_getter())) if callable(min_getter) else 6

        # Risposta difensiva: seconda legione se c'è un'incursione in corso e
        # l'esercito regge la divisione.
        defensive = 2 if (self._ai_intruder_legions() and len(self.ai_units) >= min_units) else 1

        # Manovra: quante ne vuole la dottrina, purché ognuna resti un reparto
        # vero e non un pugno di uomini sparso per la mappa.
        maneuver = min(doctrine_wanted, len(self.ai_units) // AI_MIN_UNITS_PER_LEGION)

        return max(1, min(max_legions, max(defensive, maneuver)))

    def _ensure_ai_legions_initialized(self) -> None:
        """Mantiene in campo il numero di legioni IA voluto, con cooldown dopo annientamento."""
        if not self.ai_units:
            return

        if self.debug_ai_kill_switch:
            return

        if len(self.ai_legions) >= self._ai_desired_legion_count():
            return

        # Il cooldown vale solo per il ritorno in campo dopo l'annientamento totale,
        # non per l'aggiunta di una legione difensiva a fianco di una già viva.
        if not self.ai_legions and self.ai_last_legion_loss_turn is not None:
            turns_since_loss = self.game_map.turn - self.ai_last_legion_loss_turn
            if turns_since_loss < self.ai_legion_respawn_delay_turns:
                return

        castle_pos = self.game_map.castle_positions[AI]
        spawn_pos = self._get_free_spawn_cell(AI, castle_pos) or castle_pos

        legion_id = f"AI_{self.next_legion_id}"
        self.next_legion_id += 1

        used_names = {legion.get("name") for legion in self.ai_legions.values()}
        free_names = [name for name in AI_LEGION_NAMES if name not in used_names]
        legion_name = random.choice(free_names or AI_LEGION_NAMES)

        self.ai_legions[legion_id] = {
            "id": legion_id,
            "name": legion_name,
            # Le truppe le assegna la ripartizione qui sotto: con due legioni
            # copiare l'intero esercito in ciascuna lo duplicherebbe.
            "units": [],
            "pos": spawn_pos,
            "target": None,
            "legion_type": LEGION_TYPE_ARMY,
            "path": [],
            "path_step": 0,
            # Come per il player: eredita la condizione della riserva IA.
            "condition": tc.new_condition(
                fatigue=self.reserve_condition[AI]["fatigue"],
                morale=self.reserve_condition[AI]["morale"],
                veteran=self.reserve_condition[AI]["veteran"],
                victories=self.reserve_condition[AI].get("victories", 0),
            ),
            "movement": self.movement_system.export_legion_state(
                self._legion_movement_key(AI, legion_id)
            ),
        }

        self._sync_ai_legion_units()

        cell = self.game_map.get_cell(*spawn_pos)
        if cell is not None:
            cell.occupation = AI

    def _legion_movement_key(self, entity: Occupation, legion_id: str) -> str:
        """Chiave dello stato movimento di una legione."""
        return self.movement_system.legion_key(entity, legion_id)

    def _legion_is_movement_blocked(
        self,
        entity: Occupation,
        legion_id: str,
        legion: Dict[str, Any],
        logs: List[str],
    ) -> bool:
        """Consuma un turno di attraversamento: True se la legione non può muoversi ora.

        Riusa il sistema punti-movimento già esistente (100 punti/turno, terreni
        più difficili costano di più e il surplus diventa turni di attesa),
        applicandolo però alla singola legione invece che all'intera armata.
        """
        key = self._legion_movement_key(entity, legion_id)
        block = self.movement_system.consume_legion_block_if_any(key)
        legion["movement"] = self.movement_system.export_legion_state(key)
        if not block["blocked"]:
            return False

        # Anche restare impantanati a metà guado costa: senza questo un terreno
        # duro sarebbe MENO faticoso di uno facile, perché blocca la legione per
        # più turni e i turni fermi verrebbero contati come riposo.
        legion["traversing_terrain"] = block["last_terrain"]

        icon = "⚔️" if entity == PLAYER else "🤖"
        remaining = int(block["remaining_blocked_turns"]) + 1
        logs.append(
            f"{icon} La legione {entity.value.upper()} '{legion.get('name', legion_id)}' "
            f"attraversa {str(block['last_terrain']).lower()} "
            f"(costo {block['last_cost']} punti): ancora {remaining} turno/i di marcia."
        )
        return True

    def _register_legion_move_cost(
        self,
        entity: Occupation,
        legion_id: str,
        legion: Dict[str, Any],
        from_pos: Tuple[int, int],
        to_pos: Tuple[int, int],
    ) -> Dict[str, Any]:
        """Registra il costo del terreno appena raggiunto dalla legione."""
        key = self._legion_movement_key(entity, legion_id)
        cell = self.game_map.get_cell(*to_pos)
        terrain = cell.terrain if cell is not None else "Pianura"
        info = self.movement_system.register_legion_move(key, terrain, from_pos, to_pos)
        legion["movement"] = self.movement_system.export_legion_state(key)
        return info

    def _prune_legion_movement_states(self) -> None:
        """Scarta lo stato movimento delle legioni non più in campo."""
        active = {self._legion_movement_key(PLAYER, lid) for lid in self.player_legions}
        active |= {self._legion_movement_key(AI, lid) for lid in self.ai_legions}
        self.movement_system.prune_legions(active)

    def _sync_ai_legion_units(self) -> bool:
        """Ripartisce l'esercito IA (`self.ai_units`) fra le legioni in campo.

        A differenza del player — dove `player_units` è una riserva e creare una
        legione ne sottrae le unità — per l'IA `ai_units` resta l'esercito
        autoritativo e le legioni ne sono una vista. Senza questo riallineamento
        le reclute non arriverebbero mai al fronte e le perdite non
        ridurrebbero le legioni.

        Con una sola legione è un mirror; con due (difesa ad alveare) le unità
        vengono distribuite alternandole per valore, così nessuna delle due
        eredita solo gli scarti.

        Returns:
            True se qualcosa è stato effettivamente modificato.
        """
        if not self.ai_legions:
            return False

        if not self.ai_units:
            # Esercito azzerato: sciogli le legioni invece di lasciarne di vuote in
            # campo (varrebbero forza 1 negli scontri e bloccherebbero il respawn).
            self.ai_legions.clear()
            self.ai_last_legion_loss_turn = self.game_map.turn
            return True

        legion_ids = sorted(self.ai_legions.keys())
        if len(legion_ids) == 1:
            legion = self.ai_legions[legion_ids[0]]
            if legion.get("units", []) == self.ai_units:
                return False
            legion["units"] = list(self.ai_units)
            return True

        # Distribuzione a serpentina sul valore in combattimento: le legioni
        # restano equilibrate anche con unità di qualità molto diversa.
        ordered = sorted(self.ai_units, key=lambda uid: self._unit_battle_value(uid), reverse=True)
        buckets: Dict[str, List[str]] = {lid: [] for lid in legion_ids}
        for index, unit_id in enumerate(ordered):
            slot = index % len(legion_ids)
            if (index // len(legion_ids)) % 2 == 1:
                slot = len(legion_ids) - 1 - slot
            buckets[legion_ids[slot]].append(unit_id)

        changed = False
        for legion_id in legion_ids:
            legion = self.ai_legions[legion_id]
            if legion.get("units", []) != buckets[legion_id]:
                legion["units"] = buckets[legion_id]
                changed = True

        # Una legione rimasta senza truppe va sciolta, non lasciata a vuoto.
        for legion_id in legion_ids:
            if not self.ai_legions[legion_id].get("units"):
                del self.ai_legions[legion_id]
                changed = True

        return changed

    def _ai_intruder_legions(self) -> List[Tuple[int, int]]:
        """Posizioni delle legioni player che hanno superato la metà campo.

        La metà è calcolata fra i due castelli, così la regola resta valida
        qualunque sia l'orientamento della mappa.
        """
        ai_castle = self.game_map.castle_positions.get(AI)
        player_castle = self.game_map.castle_positions.get(PLAYER)
        if ai_castle is None or player_castle is None or not self.player_legions:
            return []

        midline = (ai_castle[0] + player_castle[0]) / 2.0
        ai_is_north = ai_castle[0] < player_castle[0]

        intruders: List[Tuple[int, int]] = []
        for legion in self.player_legions.values():
            pos = tuple(legion.get("pos", ()))
            if len(pos) != 2:
                continue
            row = int(pos[0])
            crossed = row <= midline if ai_is_north else row >= midline
            if crossed:
                intruders.append((row, int(pos[1])))
        return intruders

    def _find_legion_at(self, entity: Occupation, pos: Tuple[int, int]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Restituisce (id, legione) se l'entità ha una legione sulla posizione richiesta."""
        source = self.player_legions if entity == PLAYER else self.ai_legions
        for legion_id, legion in source.items():
            if tuple(legion.get("pos", ())) == pos:
                return legion_id, legion
        return None

    def _active_legion_positions(self, entity: Occupation) -> List[Tuple[int, int]]:
        """Posizioni correnti delle legioni attive di una entità (fallback: posizione armata legacy)."""
        source = self.player_legions if entity == PLAYER else self.ai_legions
        positions: List[Tuple[int, int]] = []
        for legion in source.values():
            pos = tuple(legion.get("pos", ()))
            if len(pos) == 2:
                positions.append((int(pos[0]), int(pos[1])))

        if positions:
            # Evita duplicati conservando ordine.
            seen: set[Tuple[int, int]] = set()
            unique_positions: List[Tuple[int, int]] = []
            for pos in positions:
                if pos in seen:
                    continue
                seen.add(pos)
                unique_positions.append(pos)
            return unique_positions

        fallback = self.game_map.positions.get(entity)
        if fallback is not None:
            return [fallback]
        return []

    def _ai_expansion_allows(self, pos: Tuple[int, int]) -> bool:
        """True se l'IA può espandersi su questa cella nella fase corrente.

        In fase difensiva alcuni profili restano nella propria metà campo:
        senza il vincolo l'espansione punta il miglior obiettivo ovunque sia e
        degenera in una marcia dentro il territorio nemico.
        """
        confine = getattr(self.ai_policy, "confine_expansion_to_own_half", None)
        if not callable(confine) or not confine():
            return True

        ai_castle = self.game_map.castle_positions.get(AI)
        player_castle = self.game_map.castle_positions.get(PLAYER)
        if ai_castle is None or player_castle is None:
            return True

        midline = (ai_castle[0] + player_castle[0]) / 2.0
        if ai_castle[0] < player_castle[0]:
            return pos[0] <= midline
        return pos[0] >= midline

    def _ai_expansion_distance_penalty(self) -> float:
        """Peso della distanza nella scelta degli obiettivi economici dell'IA."""
        getter = getattr(self.ai_policy, "expansion_distance_penalty", None)
        if callable(getter):
            return max(0.0, float(getter()))
        return 0.18

    def _collect_ai_economic_targets(self, ai_pos: Tuple[int, int]) -> List[Tuple[int, int]]:
        """Target economici/territoriali per l'IA (miniere, territori utili, espansione)."""
        distance_penalty = self._ai_expansion_distance_penalty()
        scored: List[Tuple[float, Tuple[int, int]]] = []
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation == AI or cell.is_castle or cell.terrain == "Fiume":
                    continue

                pos = (cell.row, cell.col)
                if not self._ai_expansion_allows(pos):
                    continue

                distance = self._order_distance(ai_pos, pos)

                score = 0.0
                if cell.is_mine:
                    score += 4.2
                if cell.is_strategic:
                    score += 2.1
                if cell.terrain in {"Pianura", "Montagna"}:
                    score += 1.2
                if cell.occupation == PLAYER:
                    score += 0.5

                score -= distance * distance_penalty
                scored.append((score, pos))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [pos for _, pos in scored[:8]]

    def _step_toward(self, current_pos: Tuple[int, int], target_pos: Tuple[int, int]) -> Tuple[int, int]:
        """Calcola un passo ortogonale verso il target."""
        row, col = current_pos
        target_row, target_col = target_pos
        if row < target_row:
            row += 1
        elif row > target_row:
            row -= 1
        elif col < target_col:
            col += 1
        elif col > target_col:
            col -= 1
        return row, col

    def _own_legion_positions_map(
        self,
        entity: Occupation,
        exclude_id: Optional[str] = None,
    ) -> Dict[Tuple[int, int], str]:
        """Celle occupate dalle legioni di `entity`, mappate al nome della legione.

        È la base della regola del muro: una legione occupa la sua cella in
        esclusiva verso gli alleati. Senza, due legioni finivano sovrapposte e
        negli scontri ne combatteva una sola mentre l'altra restava illesa
        sulla stessa casella.
        """
        source = self.player_legions if entity == PLAYER else self.ai_legions
        occupied: Dict[Tuple[int, int], str] = {}
        for legion_id, legion in source.items():
            if exclude_id is not None and legion_id == exclude_id:
                continue
            pos = tuple(legion.get("pos", ()))
            if len(pos) == 2:
                occupied[pos] = legion.get("name", legion_id)
        return occupied

    def _free_cell_for(
        self,
        entity: Occupation,
        preferred: Tuple[int, int],
        exclude_id: Optional[str] = None,
    ) -> Optional[Tuple[int, int]]:
        """Cella libera da legioni alleate, partendo da `preferred` e allargandosi.

        Serve ai ripiegamenti: mandare un perdente sul proprio castello quando
        lì c'è già una legione ricreerebbe la sovrapposizione che stiamo togliendo.
        """
        preferred = tuple(preferred)
        occupied = self._own_legion_positions_map(entity, exclude_id=exclude_id)

        visited = {preferred}
        queue = deque([preferred])
        while queue:
            pos = queue.popleft()
            cell = self.game_map.get_cell(*pos)
            if cell is not None and cell.terrain != "Fiume" and pos not in occupied:
                return pos
            r, c = pos
            for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if neighbor in visited:
                    continue
                if self.game_map.get_cell(*neighbor) is None:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        return None

    def _nearest_reachable_cell_to(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        blocked: set,
    ) -> Optional[Tuple[int, int]]:
        """Cella raggiungibile da `start` più vicina a `goal`, aggirando `blocked`.

        È il ripiego quando la destinazione voluta è occupata o irraggiungibile:
        invece di piantarsi, la legione punta al punto utile più vicino. A parità
        di distanza dall'obiettivo vince quello che costa meno strada.
        """
        start = tuple(start)
        goal = tuple(goal)
        best: Optional[Tuple[int, int]] = None
        best_key: Optional[Tuple[int, int]] = None

        visited = {start}
        queue = deque([(start, 0)])
        while queue:
            pos, dist = queue.popleft()
            key = (abs(pos[0] - goal[0]) + abs(pos[1] - goal[1]), dist)
            if best_key is None or key < best_key:
                best_key, best = key, pos

            r, c = pos
            for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if neighbor in visited or neighbor in blocked:
                    continue
                if self.game_map.get_cell(*neighbor) is None:
                    continue
                visited.add(neighbor)
                queue.append((neighbor, dist + 1))
        return best

    def _step_preference(
        self,
        current: Tuple[int, int],
        start: Tuple[int, int],
        goal: Tuple[int, int],
        lane_col: Optional[int],
    ) -> List[Tuple[int, int]]:
        """I quattro vicini, ordinati da 'più sensato' a 'meno sensato'.

        Serve al BFS: fra tutti i cammini minimi ne esistono tantissimi, e
        quale esce dipende SOLO da quale vicino si guarda per primo. Con
        l'ordine fisso (su, giù, sinistra, destra) vinceva sempre il cammino
        che va prima in verticale: ogni legione scendeva lungo la colonna del
        castello e girava soltanto alla fine. Da fuori sembrava che il gioco
        costringesse tutti a passare dal centro — ed era esattamente così.

        L'ordine qui è:
          1. passi che avvicinano all'obiettivo (garantisce il cammino minimo);
          2. a parità, chi si tiene sulla corsia assegnata;
          3. a parità, chi resta più vicino alla retta partenza-obiettivo.

        Il terzo criterio è quello che raddrizza la marcia: invece di scendere
        tutto e poi girare, si va in diagonale. La lunghezza non cambia — il
        BFS resta ottimo — cambia quale dei cammini minimi viene scelto.

        Nota sul secondo criterio: può solo scegliere fra cammini di pari
        lunghezza. Se partenza e arrivo stanno sulla stessa colonna il cammino
        minimo è uno solo e nessuna corsia può piegarlo: per aggirare davvero
        serve un obiettivo intermedio, ed è quello che assegna la dottrina.
        """
        r, c = current
        goal_r, goal_c = goal
        delta_r = goal_r - start[0]
        delta_c = goal_c - start[1]

        def chiave(neighbor: Tuple[int, int]) -> Tuple[int, int, int]:
            nr, nc = neighbor
            avvicina = abs(goal_r - nr) + abs(goal_c - nc)
            corsia = abs(nc - lane_col) if lane_col is not None else 0
            # Distanza dalla retta partenza→obiettivo (prodotto vettoriale).
            scostamento = abs(delta_r * (nc - start[1]) - delta_c * (nr - start[0]))
            return (avvicina, corsia, scostamento)

        return sorted(((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)), key=chiave)

    def _bfs_next_step(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        blocked: set,
        lane_col: Optional[int] = None,
        origin: Optional[Tuple[int, int]] = None,
    ) -> Optional[Tuple[int, int]]:
        """Primo passo del percorso più breve start->goal, evitando le celle in `blocked`.

        Il conto si fa AL CONTRARIO, partendo dal traguardo: si misura quanto
        dista ogni cella dall'obiettivo, poi si sceglie fra i passi che
        accorciano davvero la strada. Prima invece si seguivano i "padri"
        lasciati da un BFS in avanti, e lì la forma del cammino non era
        governabile: il padre lo assegna chi scopre per primo, non chi sarebbe
        la scelta migliore. Ecco perché tutte le legioni scendevano lungo la
        colonna del castello.

        Fra i passi buoni — tutti ugualmente brevi — vince chi si tiene sulla
        corsia `lane_col`, e a parità chi resta vicino alla retta
        partenza-obiettivo. Il percorso resta minimo: cambia solo la sua forma.
        """
        start = tuple(start)
        goal = tuple(goal)
        if start == goal:
            return start

        distance = self._distance_map_from(goal, blocked)
        here = distance.get(start)
        if here is None:
            return None

        candidates = [
            neighbor
            for neighbor in self._step_preference(start, origin or start, goal, lane_col)
            if distance.get(neighbor) == here - 1
        ]
        return candidates[0] if candidates else None

    def _distance_map_from(
        self,
        goal: Tuple[int, int],
        blocked: set,
    ) -> Dict[Tuple[int, int], int]:
        """Distanza in caselle di ogni cella raggiungibile dall'obiettivo.

        Le celle bloccate non si attraversano; il traguardo invece è sempre
        raggiungibile, anche se occupato — chi ci arriva ci combatte.
        """
        rows, cols = self.game_map.rows, self.game_map.cols
        distance: Dict[Tuple[int, int], int] = {goal: 0}
        queue = deque([goal])
        while queue:
            r, c = queue.popleft()
            step = distance[(r, c)] + 1
            for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                nr, nc = neighbor
                if not (0 <= nr < rows and 0 <= nc < cols):
                    continue
                if neighbor in distance or neighbor in blocked:
                    continue
                distance[neighbor] = step
                queue.append(neighbor)
        return distance

    def _next_legion_step(
        self,
        current_pos: Tuple[int, int],
        target_pos: Tuple[int, int],
        mover: Occupation,
        legion_id: Optional[str] = None,
        lane_col: Optional[int] = None,
        origin: Optional[Tuple[int, int]] = None,
    ) -> Tuple[Tuple[int, int], Dict[str, Any]]:
        """Passo verso il target, aggirando gli ostacoli e ripiegando se serve.

        Sono ostacoli il castello nemico (a meno che sia la destinazione scelta,
        cioè un assalto esplicito) e le legioni alleate, che fanno da muro:
        una cella ne ospita una sola. Contro le legioni nemiche invece si va
        addosso: quello è uno scontro, non un ostacolo.

        Se l'obiettivo è occupato da un'alleata o non c'è un varco per arrivarci,
        la legione non si pianta: punta alla cella libera più vicina possibile
        all'obiettivo. Chi arriva primo prende la casella, gli altri si
        sistemano intorno.

        Returns:
            (prossima posizione, esito) dove l'esito riporta `blocked_by` — il
            nome dell'alleata sull'obiettivo — e `fallback`, la destinazione di
            ripiego scelta. Servono al log, per rendere visibile la decisione.
        """
        current_pos = tuple(current_pos)
        target_pos = tuple(target_pos)
        # Da dove è partita questa marcia. Serve a tenere la rotta dritta: senza
        # memoria del punto di partenza, "il passo più diretto" è sempre quello
        # sull'asse più lungo, e la legione scende tutta dritta prima di girare.
        origin = tuple(origin) if origin and len(origin) == 2 else current_pos
        resolution: Dict[str, Any] = {"blocked_by": None, "fallback": None}
        if current_pos == target_pos:
            return current_pos, resolution

        defender_castle = self.game_map.castle_positions.get(mover.opposite())
        allies = self._own_legion_positions_map(mover, exclude_id=legion_id)

        blocked: set = set(allies)
        if defender_castle is not None and tuple(defender_castle) != target_pos:
            blocked.add(tuple(defender_castle))

        # 1. Rotta diretta: il BFS aggira già le alleate lungo il percorso.
        if target_pos not in allies:
            next_step = self._bfs_next_step(current_pos, target_pos, blocked, lane_col, origin)
            # Il BFS concede sempre la cella d'arrivo, anche se bloccata: qui la
            # regola del muro deve valere pure per l'ultimo passo.
            if next_step is not None and next_step not in allies:
                return next_step, resolution

        # 2. Obiettivo occupato o senza varco: ripiego sul punto utile più vicino.
        resolution["blocked_by"] = allies.get(target_pos)
        fallback = self._nearest_reachable_cell_to(current_pos, target_pos, blocked)
        if fallback is None:
            return current_pos, resolution

        resolution["fallback"] = fallback
        if fallback == current_pos:
            return current_pos, resolution

        next_step = self._bfs_next_step(current_pos, fallback, blocked, lane_col, origin)
        if next_step is None or next_step in allies:
            return current_pos, resolution
        return next_step, resolution

    def _refresh_capture_area(self, legion: Dict[str, Any], logs: List[str]) -> None:
        """Tiene aggiornato l'ordine di cattura d'area di una legione.

        Toglie dalla coda le caselle ormai nostre — prese da questa legione, da
        un'altra o da un presidio, non importa — e punta la legione sulla più
        vicina di quelle che restano. Quando la coda si svuota l'ordine è
        eseguito e la legione si ferma lì: non torna a casa da sola, resta a
        presidiare quello che ha appena preso.
        """
        area = legion.get("capture_area")
        if not area:
            return

        current_pos = tuple(legion.get("pos", ()))
        rimaste = []
        for raw in area:
            pos = (int(raw[0]), int(raw[1]))
            cell = self.game_map.get_cell(*pos)
            if cell is not None and cell.occupation != PLAYER:
                rimaste.append(pos)

        if not rimaste:
            legion["capture_area"] = []
            legion["target"] = list(current_pos) if len(current_pos) == 2 else None
            logs.append(
                f"🗺 La legione PLAYER '{legion.get('name')}' ha completato la cattura dell'area."
            )
            return

        legion["capture_area"] = [list(pos) for pos in rimaste]
        if len(current_pos) == 2:
            prossima = min(rimaste, key=lambda pos: self._order_distance(current_pos, pos))
            legion["target"] = list(prossima)

    def _march_origin(
        self,
        legion: Dict[str, Any],
        current_pos: Tuple[int, int],
        target_pos: Tuple[int, int],
    ) -> Tuple[int, int]:
        """Punto da cui è cominciata la marcia verso l'obiettivo corrente.

        Si aggiorna solo quando l'obiettivo cambia. È la memoria che tiene
        dritta la rotta: valutando ogni passo a partire da dove la legione si
        trova adesso, la scelta più diretta è sempre quella sull'asse più
        lungo, e viene fuori una L — tutto dritto e poi la svolta.
        """
        memorizzato = legion.get("march_target")
        if tuple(memorizzato or ()) != tuple(target_pos):
            legion["march_target"] = list(target_pos)
            legion["march_origin"] = list(current_pos)

        origin = legion.get("march_origin")
        if isinstance(origin, (list, tuple)) and len(origin) == 2:
            return (int(origin[0]), int(origin[1]))
        return current_pos

    def _log_legion_fallback(
        self,
        legion: Dict[str, Any],
        etichetta: str,
        target_pos: Tuple[int, int],
        next_pos: Tuple[int, int],
        resolution: Dict[str, Any],
        logs: List[str],
    ) -> None:
        """Annota il ripiego quando la legione si sistema al posto dell'obiettivo.

        Scrive solo all'arrivo sulla cella di ripiego e una volta sola: senza
        memoria, una legione ferma riscriverebbe la stessa riga a ogni turno.
        """
        fallback = resolution.get("fallback")
        if fallback is None:
            legion.pop("fallback_note", None)
            return
        if tuple(next_pos) != tuple(fallback) or legion.get("fallback_note") == fallback:
            return

        legion["fallback_note"] = fallback
        blocked_by = resolution.get("blocked_by")
        motivo = (
            f"la legione '{blocked_by}' è arrivata prima"
            if blocked_by else "non c'è un varco libero"
        )
        logs.append(
            f"🧭 La legione {etichetta} '{legion['name']}' non può occupare {tuple(target_pos)}: "
            f"{motivo}. Si sistema in {tuple(fallback)}, la cella libera più vicina all'obiettivo."
        )

    def _pick_ai_legion_target(self, ai_legion: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        """Target IA: insegui legioni player, altrimenti espandi su obiettivi strategici e solo poi castello."""
        ai_pos = tuple(ai_legion.get("pos", ()))
        if len(ai_pos) != 2:
            return None

        player_pos: Optional[Tuple[int, int]] = None
        if self.player_legions:
            nearest = min(
                self.player_legions.values(),
                key=lambda legion: self._order_distance(ai_pos, tuple(legion.get("pos", ai_pos))),
            )
            nearest_pos = tuple(nearest.get("pos", ()))
            if len(nearest_pos) == 2:
                player_pos = nearest_pos

        own_castle = self.game_map.castle_positions.get(AI)
        enemy_castle = self.game_map.castle_positions.get(PLAYER)
        player_threatens_own_castle = False
        if player_pos is not None and own_castle is not None:
            player_threatens_own_castle = self._order_distance(player_pos, own_castle) <= 3
        player_distance = self._order_distance(ai_pos, player_pos) if player_pos is not None else None

        strategic_targets = self.game_map.get_strategic_targets(
            entity=AI,
            army_vector=self.ai_army,
            terrain_modifiers=self.data["terrain"],
        )
        # `get_strategic_targets` ordina solo per resa del terreno, senza guardare
        # la distanza: da sola porterebbe l'IA dall'altra parte della mappa.
        strategic_targets = [
            item for item in strategic_targets
            if self._ai_expansion_allows((item[1].row, item[1].col))
        ]
        economic_targets = self._collect_ai_economic_targets(ai_pos)

        # Incursione oltre metà campo: l'IA molla l'espansione e converge
        # sull'intruso più vicino. Sostituisce anche un eventuale assalto in corso.
        intruders = self._ai_intruder_legions()
        if intruders:
            focus = getattr(self.ai_policy, "should_focus_intruder", None)
            if callable(focus) and focus(turn=self.game_map.turn, intruder_count=len(intruders)):
                ai_legion["castle_commit"] = False
                return min(intruders, key=lambda p: self._order_distance(ai_pos, p))

        # Un assalto già deciso non va abbandonato a metà strada: il target viene
        # ri-scelto ogni 2-3 turni, ma il castello nemico dista 13 caselle, quindi
        # senza impegno persistente l'IA non arriva mai sotto le mura.
        if ai_legion.get("castle_commit") and enemy_castle is not None:
            if player_threatens_own_castle:
                ai_legion["castle_commit"] = False  # difendere casa ha priorità
            else:
                return enemy_castle

        policy_target = self.ai_policy.choose_target(
            ai_pos=ai_pos,
            player_pos=player_pos,
            own_castle=own_castle,
            enemy_castle=enemy_castle,
            strategic_targets=strategic_targets,
            economic_targets=economic_targets,
            turn=self.game_map.turn,
            legion_size=len(ai_legion.get("units", [])),
        )
        if policy_target is not None:
            chosen = tuple(policy_target)

            # Il castello nemico è un obiettivo strategico, non un inseguimento:
            # va valutato prima del filtro sotto, altrimenti quando il player
            # presidia il proprio castello (player_pos == enemy_castle) l'assalto
            # verrebbe scambiato per una caccia alla legione e deviato.
            if enemy_castle is not None and chosen == tuple(enemy_castle):
                ai_legion["castle_commit"] = True
                return chosen

            if (
                player_pos is not None
                and chosen == player_pos
                and not player_threatens_own_castle
                and player_distance is not None
                and player_distance > 3
                and economic_targets
            ):
                return economic_targets[0]
            return chosen

        if economic_targets:
            return economic_targets[0]

        if strategic_targets:
            # Evita corsa cieca al castello: preferisci tra i migliori target quello più vicino.
            top_candidates = strategic_targets[: min(5, len(strategic_targets))]
            _, best_cell = min(
                top_candidates,
                key=lambda item: self._order_distance(ai_pos, (item[1].row, item[1].col)),
            )
            return best_cell.row, best_cell.col

        # Ripiego: se il profilo è in postura difensiva non deve finire in
        # trasferta per mancanza di alternative — si stringe attorno a casa.
        if enemy_castle is not None and not self._ai_expansion_allows(tuple(enemy_castle)):
            return own_castle or player_pos

        return enemy_castle or player_pos

    def _ai_doctrine_plan(
        self,
        legion: Dict[str, Any],
        legion_index: int,
        current_pos: Tuple[int, int],
        base_target: Tuple[int, int],
        under_threat: bool,
    ) -> Any:
        """Passa l'obiettivo grezzo alla dottrina e ne ricava la manovra.

        Il profilo di difficoltà ha già deciso *dove* andare; qui si decide
        *come*: su quale corsia, se conviene aggirare, se è il caso di fermarsi.
        """
        def percorribile(pos: Tuple[int, int]) -> bool:
            cell = self.game_map.get_cell(*pos)
            return cell is not None and cell.terrain != "Fiume"

        return self.ai_doctrine.plan(
            legion=legion,
            legion_index=legion_index,
            ai_pos=current_pos,
            base_target=base_target,
            enemy_castle=self.game_map.castle_positions.get(PLAYER),
            rows=self.game_map.rows,
            cols=self.game_map.cols,
            turn=self.game_map.turn,
            under_threat=under_threat,
            is_walkable=percorribile,
        )

    def _ai_legion_target_lock_turns(self) -> int:
        """Numero turni minimi prima del retarget IA per evitare zig-zag e inseguimenti artificiali.

        Il valore appartiene al profilo di difficoltà: ogni file lo dichiara.
        """
        getter = getattr(self.ai_policy, "target_lock_turns", None)
        if callable(getter):
            return max(1, int(getter()))
        return 3

    def _castle_defense(self, defender: Occupation, castle_pos: Tuple[int, int]) -> Dict[str, Any]:
        """Difesa del castello: presidi (max 4) e fortificazioni.

        Le legioni ferme sulla cella non contano: erano accumulabili senza
        limite e bastavano a rendere il castello imprendibile. Chi vuole
        difendere il castello deve *distaccare* presidi, che sono contati e
        limitati a `CASTLE_MAX_GARRISON_UNITS`.

        Nemmeno la riserva conta: finché contava, formare una legione
        *sottraeva* difesa al castello, cioè giocare puniva.

        Returns:
            score              — punteggio difensivo da confrontare con l'attaccante
            damage_multiplier  — riduzione danni delle fortificazioni (1.0 = nessuna)
            defenders          — presidi che difendono la cella
            fortification_level— livelli di fortificazione sul castello
        """
        cell = self.game_map.get_cell(*castle_pos)

        # 1. Solo i presidi difendono la cella, e non oltre il tetto.
        defender_units: List[str] = []
        if cell is not None:
            defender_units = list(cell.garrison_unit_ids)[:CASTLE_MAX_GARRISON_UNITS]

        # 2. Ogni presidio vale una frazione del suo valore in battaglia.
        # [ABILITY-EFFECTS] Chi difende porta con sé i bonus difensivi sbloccati.
        defense_value_of = self._ability_value_of(defender, ab.CTX_DEFENSE)
        troop_score = sum(
            defense_value_of(uid) * CASTLE_DEFENDER_WEIGHT for uid in defender_units
        )

        # 3. Fortificazioni: solo quelle sul castello, e con tetto dedicato.
        fortification_level = 0
        if cell is not None:
            fortification_level = min(int(cell.fortification_level), CASTLE_MAX_FORTIFICATION_LEVEL)
        reduction = fortification_level * CASTLE_FORT_DAMAGE_REDUCTION_PER_LEVEL

        # [ABILITY-EFFECTS] Dottrina Fortezza: mura rinforzate ai punti deboli.
        damage_multiplier = max(0.0, 1.0 - reduction)
        damage_multiplier *= self._ability_economy_factor(defender, ab.ECO_CASTLE_DAMAGE_TAKEN)

        return {
            "score": CASTLE_DEFENSE_BASE + troop_score,
            "damage_multiplier": max(0.0, damage_multiplier),
            "defenders": len(defender_units),
            "fortification_level": fortification_level,
        }

    def _apply_legion_castle_assault(
        self,
        attacker: Occupation,
        legion: Dict[str, Any],
        from_pos: Tuple[int, int],
        to_pos: Tuple[int, int],
        logs: List[str],
    ) -> None:
        """Assedio castello nel sistema legioni: usa HP castello, niente conquista istantanea."""
        defender = attacker.opposite()
        defender_castle = self.game_map.castle_positions.get(defender)
        if defender_castle != to_pos:
            return

        hp_before = self.castle_hp.get(defender, self.castle_hp_max.get(defender, CASTLE_BASE_HP))
        legion_unit_ids = legion.get("units", [])
        # [ABILITY-EFFECTS] Il valore d'assedio passa dai bonus dello stile di
        # gioco dell'attaccante (la Scuola d'Assedio si sente qui).
        siege_value_of = self._ability_value_of(attacker, ab.CTX_SIEGE)
        # [BALANCE-LAYER] Contro le mura l'artiglieria pesa più che in campo
        # aperto. Senza layer resta la somma nuda dei valori, come prima.
        if balance is not None:
            raw_strength = balance.siege_strength(legion_unit_ids, siege_value_of)
        else:
            raw_strength = sum(siege_value_of(uid) for uid in legion_unit_ids)
        attacker_strength = max(20.0, raw_strength)

        defense = self._castle_defense(defender, to_pos)
        damage = self._compute_castle_damage(attacker_strength, defense["score"])
        # Le fortificazioni del castello tagliano i danni in percentuale, DOPO il
        # calcolo base: così l'effetto è leggibile ("con 4 livelli incasso il 60%").
        damage = max(8, int(round(damage * defense["damage_multiplier"])))
        hp_after = max(0, hp_before - damage)
        self.castle_hp[defender] = hp_after

        # L'assedio logora comunque: costa fatica e, se respinto, morale — ma
        # in proporzione a quanto poco ha ottenuto.
        status_before = tc.resolve_status(self._legion_condition(attacker, legion))
        castle_max = max(1, self.castle_hp_max.get(defender, CASTLE_BASE_HP))
        tc.apply_siege(
            self._legion_condition(attacker, legion),
            breached=hp_after <= 0,
            damage_ratio=damage / castle_max,
        )
        legion["acted_this_turn"] = True

        castle_cell = self.game_map.get_cell(*to_pos)
        if hp_after <= 0:
            if castle_cell is not None:
                castle_cell.occupation = attacker
            self.state = SessionState.GAME_OVER
            self.winner = attacker.value
            logs.append(
                f"🏰 {attacker.value.upper()} abbatte il castello ({to_pos}) "
                f"con {damage} danni (HP {hp_before}->{hp_after})."
            )
            return

        self._log_condition_change(attacker, legion, status_before, logs)

        # Castello non distrutto: assalto respinto, le truppe rientrano subito al castello d'origine
        # (niente spam di assalti: il target viene azzerato, serve un nuovo ordine del giocatore/IA).
        own_castle = self.game_map.castle_positions.get(attacker)
        if own_castle is not None:
            # Come nei ripiegamenti dopo uno scontro: se il castello è occupato
            # da un'altra legione si rientra di fianco, mai sopra.
            legion["pos"] = self._free_cell_for(
                attacker, own_castle, exclude_id=legion.get("id")
            ) or own_castle
        else:
            legion["pos"] = from_pos
        legion["target"] = None
        # Assalto concluso: l'impegno va sciolto, la prossima offensiva si ridecide.
        legion["castle_commit"] = False
        if castle_cell is not None:
            castle_cell.occupation = defender
        from_cell = self.game_map.get_cell(*from_pos)
        if from_cell is not None:
            from_cell.occupation = attacker

        logs.append(
            f"🏰 Assalto respinto: {attacker.value.upper()} infligge {damage} danni "
            f"al castello (HP {hp_before}->{hp_after}) e le truppe rientrano al castello d'origine."
        )

    def _legion_battle_strength(
        self,
        entity: Occupation,
        legion: Dict[str, Any],
        terrain: str,
        *,
        defending: bool,
        cell: Optional[Any],
        enemy_strength: float = 0.0,
        movement_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Forza di combattimento di una singola legione sulla cella dello scontro.

        Riusa le stesse regole del resto del motore: valore unità modulato dal
        terreno, bonus stack, fattore strategia/contesto e — solo per chi
        difende la propria cella — fortificazioni, presidi e vantaggio del
        terreno difensivo.
        """
        unit_ids = list(legion.get("units", []))
        empty = {
            "strength": 0.0,
            "units": 0,
            "fortification_level": 0,
            "garrison_strength": 0,
            "strategy_factor": 0.0,
            "defense_bonus": 0.0,
            "movement_factor": 1.0,
        }
        if not unit_ids:
            return empty

        # 1. Valore delle unità modulato dal terreno (stessa regola dei presidi).
        # [ABILITY-EFFECTS] Lo stile di gioco pesa qui: in attacco o in difesa
        # a seconda del ruolo che la legione ha in questo scontro.
        context = ab.CTX_DEFENSE if defending else ab.CTX_ATTACK
        unlocked = self._unlocked_abilities(entity)
        if ab.has_unit_effects(unlocked, context):
            base_total = sum(
                self._garrison_unit_defense_value(uid, terrain)
                * ab.unit_factor(unlocked, uid, context)
                for uid in unit_ids
            )
        else:
            base_total = sum(self._garrison_unit_defense_value(uid, terrain) for uid in unit_ids)

        # [BALANCE-LAYER] Chi assalta una cella fortificata guadagna il surplus
        # d'assedio (oggi: solo l'artiglieria). È un'aggiunta al valore già
        # calcolato: togliendo il layer resta esattamente il numero di prima.
        if balance is not None and not defending and cell is not None:
            base_total += balance.fortification_surplus(
                unit_ids, self._ability_value_of(entity, ab.CTX_SIEGE), int(cell.fortification_level)
            )

        # 2. Bonus stack per unità dello stesso tipo (coerente con _strength_breakdown).
        stack_bonus = 0.0
        for unit_id, count in Counter(unit_ids).items():
            if count <= 1:
                continue
            value = self._unit_battle_value(unit_id)
            bonus = value * 0.22 * ((count - 1) ** 1.08)
            stack_bonus += min(bonus, value * count * 0.55)

        # 3. Strategia ed effetti ambientali sul terreno dello scontro.
        #    Si valuta la composizione DI QUESTA legione, non l'esercito globale:
        #    è ciò che rende sensata una strategia per legione (la cavalleria
        #    manovra, la fanteria tiene) invece di una sola per tutto il campo.
        #    Lo stato truppe è quello DI QUESTA legione: la stessa scala della
        #    schermata iniziale, applicata dal solito `apply_modifiers`.
        troop_status = self._legion_troop_status(entity, legion)
        modified, _ = apply_modifiers(
            army_vector=aggregate_army(unit_ids, self.data["units"]),
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=troop_status,
            modifiers_data=self.data,
        )
        strategy_factor = self._strategy_factor(
            entity, terrain, modified, self._legion_strategy_id(entity, legion)
        )
        context_factor = max(0.75, min(1.25, (sum(modified.values()) / 4.6)))

        strength = (base_total + stack_bonus) * strategy_factor * context_factor

        # 4. Vantaggi difensivi: valgono solo per la legione già presente sulla cella.
        fortification_level = 0
        garrison_strength = 0
        defense_bonus = 0.0
        if defending and cell is not None:
            fortification_level = int(cell.fortification_level)
            garrison_strength = int(cell.garrison_strength)

            if fortification_level > 0:
                # Come nella difesa statica: parte fissa + parte che scala
                # sull'intensità dell'assalto, altrimenti contro legioni grandi
                # un bonus piatto diventa irrilevante.
                defense_bonus += (fortification_level * 18.0) + (max(0, fortification_level - 1) * 16.0)
                defense_bonus += enemy_strength * min(0.32, 0.12 + (fortification_level * 0.05))
            if garrison_strength > 0:
                defense_bonus += garrison_strength * 18.0
                defense_bonus += enemy_strength * min(0.22, garrison_strength * 0.025)
            if cell.garrison_unit_ids:
                # [ABILITY-EFFECTS] Anche i presidi della cella difendono con
                # i bonus difensivi di chi li ha piazzati.
                garrison_factor = ab.unit_factor if ab.has_unit_effects(unlocked, ab.CTX_DEFENSE) else None
                defense_bonus += sum(
                    self._garrison_unit_defense_value(uid, terrain)
                    * (garrison_factor(unlocked, uid, ab.CTX_DEFENSE) if garrison_factor else 1.0)
                    for uid in cell.garrison_unit_ids
                ) * 2.0
            if fortification_level > 0 and garrison_strength > 0:
                # Sinergia presidio-dentro-fortificazione, come nella difesa statica.
                defense_bonus += fortification_level * garrison_strength * 7.0
            defense_bonus += 8.0 if terrain in {"Foresta", "Montagna", "Palude"} else 5.0

        # 5. Malus da marcia incompleta: una legione sorpresa mentre attraversa
        #    un terreno difficile combatte peggio (regola già del sistema movimento).
        movement_factor = 1.0
        if movement_key is not None:
            movement_factor = float(
                self.movement_system.get_legion_defense_modifier(movement_key)["factor"]
            )

        return {
            "strength": (strength + defense_bonus) * movement_factor,
            "units": len(unit_ids),
            "fortification_level": fortification_level,
            "garrison_strength": garrison_strength,
            "strategy_factor": strategy_factor,
            "defense_bonus": defense_bonus,
            "movement_factor": movement_factor,
        }

    def _apply_legion_losses(
        self,
        entity: Occupation,
        legion_id: str,
        legion: Dict[str, Any],
        losses: int,
    ) -> Tuple[int, str, bool]:
        """Applica le perdite a una legione. Ritorna (perdite, testo, sopravvissuta)."""
        unit_ids = list(legion.get("units", []))
        source = self.player_legions if entity == PLAYER else self.ai_legions

        if losses <= 0 or not unit_ids:
            return 0, "", bool(unit_ids)

        losses = min(losses, len(unit_ids))

        # [BALANCE-LAYER] I guaritori presenti nella legione assorbono parte
        # delle perdite. Non sono al riparo: cadono per prime le unità di minor
        # valore, loro comprese, quindi il tampone si consuma da sé.
        saved = 0
        if balance is not None:
            losses, saved = balance.reduced_losses(unit_ids, losses)

        # Cadono per prime le unità di minor valore.
        removed = sorted(unit_ids, key=lambda uid: self._unit_battle_value(uid))[:losses]

        remaining = list(unit_ids)
        for unit_id in removed:
            remaining.remove(unit_id)
        self.troops_lost[entity] += len(removed)  # [ENDGAME-STATS]

        if entity == AI:
            # `ai_units` è l'esercito autoritativo dell'IA: senza rimuoverle anche
            # da lì, _sync_ai_legion_units rimetterebbe in campo le unità perse.
            for unit_id in removed:
                if unit_id in self.ai_units:
                    self.ai_units.remove(unit_id)
            self._recompute_entity_army_state(AI)
            # La ripartizione può riassegnare le truppe fra le legioni superstiti,
            # quindi la sopravvivenza va letta dopo il sync, non da `remaining`.
            self._sync_ai_legion_units()
            survived = bool(source.get(legion_id, {}).get("units"))
            if not self.ai_legions:
                self.ai_last_legion_loss_turn = self.game_map.turn
        else:
            legion["units"] = remaining
            survived = bool(remaining)
            if not survived and legion_id in source:
                del source[legion_id]

        counts = Counter(removed)
        text = ", ".join(
            f"{count} {self.units_map.get(unit_id, {}).get('name', unit_id)}"
            for unit_id, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        )

        # [BALANCE-LAYER] L'intervento dei guaritori va scritto nel log, se no
        # è un effetto che il giocatore paga 90 grux e non vede mai.
        if saved and balance is not None:
            nota = balance.losses_note(saved)
            if nota:
                text = f"{text} — {nota}" if text else nota

        return losses, text, survived

    def _resolve_legion_clash_if_any(
        self,
        pos: Tuple[int, int],
        logs: List[str],
        attacker: Optional[Occupation] = None,
    ) -> None:
        """Scontro legione-vs-legione: attrito reale con terreno, strategia e difese."""
        player_entry = self._find_legion_at(PLAYER, pos)
        ai_entry = self._find_legion_at(AI, pos)
        if player_entry is None or ai_entry is None:
            return

        cell = self.game_map.get_cell(*pos)
        terrain = cell.terrain if cell is not None else self.player_home_terrain

        # Chi ha appena mosso attacca; l'altra legione difende la cella su cui già si trovava.
        if attacker is None:
            attacker = AI
        defender = attacker.opposite()

        entries = {PLAYER: player_entry, AI: ai_entry}
        atk_id, atk_legion = entries[attacker]
        def_id, def_legion = entries[defender]

        atk = self._legion_battle_strength(
            attacker, atk_legion, terrain, defending=False, cell=cell,
            movement_key=self._legion_movement_key(attacker, atk_id),
        )
        # Le difese della cella scalano sull'intensità dell'assalto: serve prima la forza attaccante.
        dfn = self._legion_battle_strength(
            defender, def_legion, terrain, defending=True, cell=cell,
            enemy_strength=atk["strength"],
            movement_key=self._legion_movement_key(defender, def_id),
        )

        # Le difese della cella aumentano anche l'attrito subito dall'attaccante.
        atk_losses = self._calculate_losses_for_battle(
            atk["units"],
            atk["strength"],
            dfn["strength"],
            fortification_level=dfn["fortification_level"],
            garrison_strength=dfn["garrison_strength"],
        )
        def_losses = self._calculate_losses_for_battle(
            dfn["units"],
            dfn["strength"],
            atk["strength"],
        )

        atk_n, atk_text, atk_alive = self._apply_legion_losses(attacker, atk_id, atk_legion, atk_losses)
        def_n, def_text, def_alive = self._apply_legion_losses(defender, def_id, def_legion, def_losses)

        atk_name = atk_legion.get("name", atk_id)
        def_name = def_legion.get("name", def_id)

        # Stato prima dello scontro: serve per annotare gli eventuali passaggi
        # (una legione può uscire dalla battaglia demoralizzata o promossa).
        atk_status_before = tc.resolve_status(self._legion_condition(attacker, atk_legion))
        def_status_before = tc.resolve_status(self._legion_condition(defender, def_legion))

        def registra_esito(vincitrice: Optional[Dict[str, Any]], perdente: Optional[Dict[str, Any]]) -> None:
            """Applica fatica, morale e vittorie alle legioni sopravvissute."""
            for legione, entita, vinto, prima in (
                (vincitrice, attacker if vincitrice is atk_legion else defender, True,
                 atk_status_before if vincitrice is atk_legion else def_status_before),
                (perdente, attacker if perdente is atk_legion else defender, False,
                 atk_status_before if perdente is atk_legion else def_status_before),
            ):
                if legione is None:
                    continue
                tc.apply_battle(self._legion_condition(entita, legione), won=vinto)
                legione["acted_this_turn"] = True
                self._log_condition_change(entita, legione, prima, logs)

        header = (
            f"{self._format_battle_location(terrain)} su {pos}: "
            f"{attacker.value.upper()} '{atk_name}' ({int(atk['strength'])}) contro "
            f"{defender.value.upper()} '{def_name}' ({int(dfn['strength'])})"
        )
        if dfn["defense_bonus"] > 0:
            header += (
                f" — difese: fort. {dfn['fortification_level']}, presidio {dfn['garrison_strength']}"
            )
        logs.append(header + ".")

        if atk_n or def_n:
            logs.append(
                f"   Perdite: {attacker.value.upper()} -{atk_n}"
                f"{f' ({atk_text})' if atk_text else ''} · "
                f"{defender.value.upper()} -{def_n}"
                f"{f' ({def_text})' if def_text else ''}."
            )

        # Entrambe annientate: la cella resta contesa.
        if not atk_alive and not def_alive:
            if cell is not None and not cell.is_castle:
                cell.occupation = Occupation.NEUTRAL
            logs.append(f"   Esito: annientamento reciproco su {pos}.")
            return

        if not def_alive:
            if cell is not None:
                cell.occupation = attacker
            logs.append(
                f"   Esito: vince {attacker.value.upper()} — legione '{def_name}' distrutta."
            )
            registra_esito(atk_legion, None)
            return

        if not atk_alive:
            if cell is not None:
                cell.occupation = defender
            logs.append(
                f"   Esito: assalto respinto — legione '{atk_name}' distrutta."
            )
            registra_esito(def_legion, None)
            return

        # Entrambe sopravvivono: decide la forza, chi perde ripiega al proprio castello.
        if atk["strength"] > dfn["strength"]:
            winner, loser_entity = attacker, defender
            winner_legion, loser_legion = atk_legion, def_legion
            loser_name = def_name
        else:
            winner, loser_entity = defender, attacker
            winner_legion, loser_legion = def_legion, atk_legion
            loser_name = atk_name

        if cell is not None:
            cell.occupation = winner

        own_castle = self.game_map.castle_positions.get(loser_entity)
        if own_castle is not None:
            # Se il castello è già presidiato da un'altra legione ripiega di fianco:
            # il ripiegamento non deve ricreare la sovrapposizione.
            loser_id = def_id if loser_entity == defender else atk_id
            loser_legion["pos"] = (
                self._free_cell_for(loser_entity, own_castle, exclude_id=loser_id) or own_castle
            )
        loser_legion["target"] = None

        logs.append(
            f"   Esito: vince {winner.value.upper()} — la legione '{loser_name}' "
            f"ripiega al proprio castello."
        )
        registra_esito(winner_legion, loser_legion)

    # ──────────────────────────────────────────────────────────
    # MOSSA GIOCATORE (entry-point principale)
    # ──────────────────────────────────────────────────────────

    def player_move(
        self,
        to_row: int,
        to_col: int,
        leave_garrison: bool = False,
        garrison_unit_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Esegue la mossa del giocatore verso (to_row, to_col).

        Dopo la mossa del giocatore:
          - Se scatta battaglia, la risolve immediatamente.
          - Passa il turno all'IA e la fa muovere (con possibile secondo scontro).

        Returns:
            dict con:
                ok              — True se la mossa è valida
                message         — descrizione testuale
                battle_result   — risultato battaglia (se avvenuta), oppure None
                ai_move_result  — esito mossa IA (oppure None se partita finita)
                game_over       — True se la partita è terminata
                winner          — "player" | "ai" | None
                state           — stato sessione corrente
                map             — stato mappa serializzato
        """
        if self.state != SessionState.ACTIVE:
            return {
                "ok": False,
                "message": "La partita è già terminata.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        if leave_garrison and self._available_garrisons(PLAYER) <= 0:
            return {
                "ok": False,
                "message": "Non hai unità sufficienti: devi mantenere almeno una legione attiva con l'armata.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }
        if leave_garrison and garrison_unit_id and garrison_unit_id not in self.player_units:
            return {
                "ok": False,
                "message": "La truppa selezionata non è disponibile nell'armata attiva.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        block = self.movement_system.consume_block_if_any(PLAYER)
        if block.get("blocked"):
            blocked_message = self._build_movement_block_message(PLAYER, block)
            self.battle_log.append(blocked_message)

            self.game_map.end_turn()
            ai_result = self._ai_turn()

            if self.state == SessionState.ACTIVE:
                economy_logs = self._advance_round_economy()
                if economy_logs:
                    self.battle_log.extend(economy_logs)

            return {
                "ok": True,
                "skipped": True,
                "message": blocked_message,
                "battle_result": None,
                "ai_move_result": ai_result,
                "game_over": self.state == SessionState.GAME_OVER,
                "winner": self.winner,
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        # Con armata vuota il player può comunque riposizionarsi sul campo,
        # ma non può attaccare né conquistare territori.
        if len(self.player_units) == 0:
            relocation_result = self._move_player_without_troops(to_row, to_col)
            if not relocation_result["ok"]:
                return {
                    "ok": False,
                    "message": relocation_result["message"],
                    "state": self.state.value,
                    "map": self.game_map.to_dict(),
                }

            move_cost_info = self.movement_system.register_move(
                PLAYER,
                relocation_result["terrain"],
                from_pos=tuple(relocation_result["from_pos"]),
                to_pos=tuple(relocation_result["to_pos"]),
            )
            relocation_result["message"] += self._format_movement_cost_suffix(move_cost_info)
            self.battle_log.append(relocation_result["message"])

            # Passa il turno all'IA anche in modalità riposizionamento.
            self.game_map.end_turn()
            ai_result = self._ai_turn()

            if self.state == SessionState.ACTIVE:
                economy_logs = self._advance_round_economy()
                if economy_logs:
                    self.battle_log.extend(economy_logs)

            return {
                "ok": True,
                "message": relocation_result["message"],
                "battle_result": None,
                "ai_move_result": ai_result,
                "game_over": self.state == SessionState.GAME_OVER,
                "winner": self.winner,
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        move_result = self.game_map.move(PLAYER, (to_row, to_col), leave_garrison=leave_garrison)
        if not move_result["ok"]:
            return {
                "ok": False,
                "message": move_result["message"],
                "state": self.state.value,
                "map": self.game_map.to_dict(),
            }

        # Log persistente della mossa player per debug cronologico completo.
        move_cost_info = self.movement_system.register_move(
            PLAYER,
            move_result["terrain"],
            from_pos=tuple(move_result["from_pos"]),
            to_pos=tuple(move_result["to_pos"]),
        )
        move_result["message"] += self._format_movement_cost_suffix(move_cost_info)
        self.battle_log.append(move_result["message"])

        if leave_garrison and move_result.get("leave_garrison"):
            detach_result = self._detach_unit_to_garrison(
                entity=PLAYER,
                cell_pos=tuple(move_result["from_pos"]),
                unit_id=garrison_unit_id,
                auto=False,
            )
            move_result["message"] += f" — Distaccata: {detach_result['unit_name']}"
            self.battle_log[-1] = move_result["message"]

        battle_result: Optional[Dict] = None
        if move_result["battle"]:
            battle_result = self._resolve_encounter(
                move_result=move_result,
                attacker=PLAYER,
            )
            if self.state == SessionState.GAME_OVER:
                return {
                    "ok": True,
                    "message": move_result["message"],
                    "battle_result": battle_result,
                    "ai_move_result": None,
                    "game_over": True,
                    "winner": self.winner,
                    "state": self.state.value,
                    "map": self.game_map.to_dict(),
                }

        # Passa il turno all'IA
        self.game_map.end_turn()
        ai_result = self._ai_turn()

        if self.state == SessionState.ACTIVE:
            economy_logs = self._advance_round_economy()
            if economy_logs:
                self.battle_log.extend(economy_logs)

        return {
            "ok": True,
            "message": move_result["message"],
            "battle_result": battle_result,
            "ai_move_result": ai_result,
            "game_over": self.state == SessionState.GAME_OVER,
            "winner": self.winner,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
        }

    def _move_player_without_troops(self, to_row: int, to_col: int) -> Dict[str, Any]:
        """Permette il riposizionamento del player senza truppe, senza combattimento né conquista."""
        from_pos = self.game_map.positions.get(PLAYER)
        if from_pos is None:
            return {"ok": False, "message": "Posizione PLAYER non disponibile."}

        to_pos = (to_row, to_col)
        if not self.game_map.is_adjacent(from_pos, to_pos):
            return {"ok": False, "message": "La destinazione non è adiacente alla posizione corrente."}

        if not (0 <= to_row < self.game_map.rows and 0 <= to_col < self.game_map.cols):
            return {"ok": False, "message": "Destinazione fuori dalla mappa."}

        own_castle = self.game_map.get_castle_position(PLAYER)
        if to_pos == own_castle:
            return {
                "ok": False,
                "message": "La casella del castello è proibita al movimento.",
            }

        enemy_pos = self.game_map.positions.get(AI)
        if enemy_pos == to_pos:
            return {
                "ok": False,
                "message": "Armata senza truppe: non puoi ingaggiare direttamente l'armata nemica.",
            }

        self.game_map.positions[PLAYER] = to_pos
        dest_cell = self.game_map.get_cell(to_row, to_col)
        terrain = dest_cell.terrain if dest_cell is not None else "Sconosciuto"
        return {
            "ok": True,
            "terrain": terrain,
            "from_pos": from_pos,
            "to_pos": to_pos,
            "message": (
                f"[Turno {self.game_map.turn}] PLAYER si riposiziona -> ({to_row},{to_col}) "
                f"[{terrain}] senza truppe: nessuna conquista o attacco"
            ),
        }

    def _format_movement_cost_suffix(self, move_cost_info: Dict[str, Any]) -> str:
        """Ritorna un suffisso leggibile con costo movimento e ritardo eventuale."""
        cost = int(move_cost_info.get("cost", 0))
        points_per_turn = int(move_cost_info.get("points_per_turn", 100))
        extra_wait_turns = int(move_cost_info.get("extra_wait_turns", 0))
        if extra_wait_turns > 0:
            return (
                f" — Movimento: costo {cost}/{points_per_turn}"
                f" (rallentamento: +{extra_wait_turns} turno/i)"
            )
        return f" — Movimento: costo {cost}/{points_per_turn}"

    def _build_movement_block_message(self, entity: Occupation, block: Dict[str, Any]) -> str:
        """Messaggio di skip turno quando l'armata è rallentata dal terreno."""
        side = entity.value.upper()
        remaining = int(block.get("remaining_blocked_turns", 0))
        terrain = str(block.get("last_terrain") or "terreno difficile")
        cost = int(block.get("last_cost", self.movement_system.points_per_turn))
        if remaining > 0:
            return (
                f"[Turno {self.game_map.turn}] {side} rallentato su {terrain} "
                f"(costo {cost}): turno di movimento bloccato "
                f"({remaining} turno/i di ritardo residui)"
            )
        return (
            f"[Turno {self.game_map.turn}] {side} rallentato su {terrain} "
            f"(costo {cost}): ultimo turno di ritardo consumato"
        )

    # ──────────────────────────────────────────────────────────
    # TURNO IA (privato)
    # ──────────────────────────────────────────────────────────

    def _ai_turn(self) -> Dict[str, Any]:
        """
        Logica del turno IA:
          1. Se esistono celle strategiche non controllate dall'IA, prende quella
             con il punteggio di terreno più alto per il suo esercito.
          2. Se il giocatore è molto vicino (≤ 2 passi) e più vicino del target
             strategico, attacca direttamente.
          3. Esegue la mossa; se scatta battaglia la risolve.
          4. Passa il turno al giocatore (anche in caso di errori, via finally).
        """
        result: Dict[str, Any] = {"skipped": False, "ok": False, "message": ""}

        try:
            if self.state != SessionState.ACTIVE:
                result.update({"skipped": True, "reason": "partita terminata"})
                return result

            if self.debug_ai_kill_switch:
                result.update({
                    "skipped": True,
                    "ok": True,
                    "reason": "kill_switch_attivo",
                    "message": f"[Turno {self.game_map.turn}] 🧪 DEBUG: IA in pausa (kill switch attivo)",
                })
                return result

            if self.ai_policy.should_skip_turn(self.game_map.turn):
                result.update({
                    "skipped": True,
                    "ok": True,
                    "reason": "easy_ai_skip_turn",
                    "message": f"[Turno {self.game_map.turn}] IA esita e perde l'iniziativa.",
                })
                return result

            ai_pos = self.game_map.positions.get(AI)
            if ai_pos is None:
                result.update({"skipped": True, "reason": "IA eliminata"})
                return result

            ai_block = self.movement_system.consume_block_if_any(AI)
            if ai_block.get("blocked"):
                blocked_message = self._build_movement_block_message(AI, ai_block)
                self.battle_log.append(blocked_message)
                result.update(
                    {
                        "skipped": True,
                        "ok": True,
                        "reason": "movement_delay",
                        "message": blocked_message,
                    }
                )
                return result

            target_pos = self._compute_ai_target(ai_pos)
            if target_pos is None:
                result.update({"skipped": True, "reason": "nessun target disponibile"})
                return result

            next_move = self.game_map.best_move_toward(AI, target_pos)
            if next_move is None:
                result.update({"skipped": True, "reason": "nessuna mossa valida"})
                return result

            leave_garrison = self._should_ai_leave_garrison(ai_pos)
            if leave_garrison and self._available_garrisons(AI) <= 0:
                leave_garrison = False

            ai_move = self.game_map.move(AI, next_move, leave_garrison=leave_garrison)
            if leave_garrison and ai_move.get("leave_garrison"):
                detach_result = self._detach_unit_to_garrison(
                    entity=AI,
                    cell_pos=tuple(ai_move["from_pos"]),
                    unit_id=None,
                    auto=True,
                )
                if detach_result and ai_move.get("message"):
                    ai_move["message"] += f" — Distaccata: {detach_result['unit_name']}"

            if ai_move.get("ok"):
                ai_move_cost_info = self.movement_system.register_move(
                    AI,
                    ai_move.get("terrain", "Pianura"),
                    from_pos=tuple(ai_move["from_pos"]),
                    to_pos=tuple(ai_move["to_pos"]),
                )
                if ai_move.get("message"):
                    ai_move["message"] += self._format_movement_cost_suffix(ai_move_cost_info)

            if ai_move.get("ok") and ai_move.get("message"):
                self.battle_log.append(ai_move["message"])

            result["ok"]      = ai_move.get("ok", False)
            result["message"] = ai_move.get("message", "")

            if ai_move.get("battle"):
                result["battle_result"] = self._resolve_encounter(
                    move_result=ai_move,
                    attacker=AI,
                )

            return result

        finally:
            # Il turno torna sempre al giocatore, anche in caso di skip
            self.game_map.end_turn()

    def _compute_ai_target(
        self,
        ai_pos: Tuple[int, int],
    ) -> Optional[Tuple[int, int]]:
        """
        Determina la cella obiettivo dell'IA:
          - Se può minacciare il castello del giocatore, avanza verso il castello.
          - Altrimenti prende celle strategiche utili al suo esercito.
          - Se il giocatore è molto vicino, prova a intercettarlo.
        """
        player_pos = self.game_map.positions.get(PLAYER)
        enemy_castle = self.game_map.get_castle_position(PLAYER)
        own_castle = self.game_map.get_castle_position(AI)
        ai_cell = self.game_map.get_cell(*ai_pos)
        estimate_terrain = ai_cell.terrain if ai_cell is not None else "Pianura"

        strategic_targets = self.game_map.get_strategic_targets(
            entity=AI,
            army_vector=self.ai_army,
            terrain_modifiers=self.data["terrain"],
        )

        ai_strength_est = self._strength_breakdown(AI, estimate_terrain)["effective_strength"]
        player_strength_est = self._strength_breakdown(PLAYER, estimate_terrain)["effective_strength"]
        ai_has_advantage = ai_strength_est >= (player_strength_est * 1.08)

        easy_target = self.ai_policy.choose_target(
            ai_pos=ai_pos,
            player_pos=player_pos,
            own_castle=own_castle,
            enemy_castle=enemy_castle,
            strategic_targets=strategic_targets,
            economic_targets=self._collect_ai_economic_targets(ai_pos),
        )
        if easy_target is not None:
            return easy_target

        # Priorita difensiva: se il player e vicino al castello IA, intercetta.
        if player_pos and own_castle:
            player_to_own_castle = abs(player_pos[0] - own_castle[0]) + abs(player_pos[1] - own_castle[1])
            if player_to_own_castle <= 3:
                return player_pos

        if enemy_castle:
            dist_castle = abs(ai_pos[0] - enemy_castle[0]) + abs(ai_pos[1] - enemy_castle[1])
            if dist_castle <= 2:
                return enemy_castle
            if dist_castle <= 4 and ai_has_advantage and not strategic_targets:
                return enemy_castle

        targets = strategic_targets

        if targets:
            _, best_cell     = targets[0]
            strat_pos        = (best_cell.row, best_cell.col)
            dist_strat       = abs(ai_pos[0] - strat_pos[0]) + abs(ai_pos[1] - strat_pos[1])

            if player_pos:
                dist_player = abs(ai_pos[0] - player_pos[0]) + abs(ai_pos[1] - player_pos[1])
                if dist_player <= 2 and dist_player <= dist_strat and ai_has_advantage:
                    return player_pos

            return strat_pos

        # Nessun target strategico: carica il castello o il giocatore
        if ai_has_advantage:
            return enemy_castle or player_pos
        return player_pos or enemy_castle

    def _should_ai_leave_garrison(self, from_pos: Tuple[int, int]) -> bool:
        """L'IA lascia guarnigioni su castelli e punti strategici quando possibile."""
        cell = self.game_map.get_cell(*from_pos)
        if cell is None:
            return False
        available = self._available_garrisons(AI)
        if available <= 0:
            return False

        return self.ai_policy.should_leave_garrison(
            is_castle=cell.is_castle,
            is_strategic=cell.is_strategic,
            current_strength=cell.garrison_strength,
            available=available,
        )

    def _advance_round_economy(self) -> List[str]:
        """Accredita i grux delle miniere e fa gestire all'IA la propria economia."""
        logs: List[str] = []
        for entity in (PLAYER, AI):
            if entity == AI and self.debug_ai_kill_switch:
                continue
            mine_count = self.game_map.count_mines(entity)
            if mine_count > 0:
                linear_income = mine_count * MINE_YIELD_PER_ROUND
                income = self._mine_income_for_count(mine_count, entity)
                self.grux_balance[entity] += income
                diminishing_note = ""
                if income < linear_income:
                    diminishing_note = f" (rendimenti decrescenti: -{linear_income - income})"
                logs.append(
                    f"[Turno {self.game_map.turn}] ⛏ {entity.value.upper()} incassa {income} grux da {mine_count} miniere{diminishing_note}"
                )

        # Il banco cambia merce prima che l'IA faccia la spesa: se no
        # comprerebbe sempre le offerte del giro precedente.
        logs.extend(self._tick_black_market())

        if not self.debug_ai_kill_switch:
            logs.extend(self._auto_manage_ai_economy())
        logs.extend(self._run_player_auto_recruit())
        return logs

    def toggle_debug_ai_kill_switch(self) -> Dict[str, Any]:
        """[DEBUG-MODULE] Pausa/riprende totalmente l'IA.

        Chiamato solo da gamecore/debug_module: rimuovibile insieme a esso.
        """
        self.debug_ai_kill_switch = not self.debug_ai_kill_switch
        status = "ATTIVO" if self.debug_ai_kill_switch else "DISATTIVO"
        log_entry = (
            f"[Turno {self.game_map.turn}] 🧪 DEBUG TEMPORANEO - KILL SWITCH IA {status} "
            f"(rimuovere in produzione)"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "enabled": self.debug_ai_kill_switch,
            "message": log_entry,
            "session": self.to_dict(),
        }

    def _rebuild_ai_army_for_difficulty(self) -> Optional[str]:
        """Ricostruisce l'esercito IA col profilo della difficoltà, se la partita non è iniziata.

        Ogni difficoltà ha il proprio costruttore (budget, qualità delle unità,
        strategia iniziale): senza questo, cambiare difficoltà dal selettore
        avrebbe cambiato solo il comportamento, lasciando l'esercito di 'facile'.
        """
        if self.game_map.turn > 1 or self.player_legions or self.ai_legions:
            return None

        ai_data = build_ai_army(
            data=self.data,
            ai_terrain=self.ai_home_terrain,
            weather=self.weather,
            n_units=3,
            budget=STARTING_GRUX,
            seed=self.ai_policy_seed,
            difficulty=self.ai_difficulty,
        )

        self.ai_units = list(ai_data["units"])
        self.ai_strategy_id = ai_data["strategy"]["id"]
        self.ai_strategy_name = ai_data["strategy"]["name"]
        self.ai_army = ai_data["army_vector"]
        self.ai_modified = ai_data["modified_vector"]
        self.ai_troop_status = ai_data["troop_status"]
        self.ai_army_cost = ai_data.get("army_cost", 0)
        self.grux_balance[AI] = ai_data.get("remaining_grux", STARTING_GRUX - self.ai_army_cost)

        # Gli HP del castello dipendono dalla dimensione dell'esercito.
        self.castle_hp_max = self._build_castle_hp_pool()
        self.castle_hp[AI] = self.castle_hp_max[AI]

        composition = ", ".join(
            f"{count} {self.units_map.get(uid, {}).get('name', uid)}"
            for uid, count in sorted(Counter(self.ai_units).items())
        )
        return (
            f"[Turno {self.game_map.turn}] 🏗 L'IA riorganizza l'esercito per la difficoltà "
            f"{self.ai_difficulty.upper()}: {composition} · strategia {self.ai_strategy_name} "
            f"· {self.grux_balance[AI]} grux in cassa"
        )

    def set_ai_difficulty(self, difficulty: str) -> Dict[str, Any]:
        """Aggiorna la difficoltà IA runtime e ricalcola la policy decisionale."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        normalized = normalize_ai_difficulty(difficulty)
        if normalized == self.ai_difficulty:
            return {
                "ok": True,
                "message": f"Difficoltà IA già impostata su {normalized}.",
                "state": self.state.value,
                "map": self.game_map.to_dict(),
                "session": self.to_dict(),
            }

        self.ai_difficulty = normalized
        self.ai_policy = build_ai_policy(self.ai_difficulty, seed=None)
        # Le ricerche non ancora avviate prendono il ritmo della nuova
        # difficoltà; quelle in corso o già sbloccate restano come sono, che
        # cambiare i turni sotto una ricerca aperta sarebbe riscrivere il passato.
        research_scale = ab.ai_research_scale(self.ai_difficulty)
        for ability_id, ability_state in self.ability_states[AI].items():
            definition = ab.ABILITIES.get(ability_id)
            if definition is not None and ability_state.started_turn is None:
                ability_state.turns_required = max(
                    4, int(round(definition.turns_required * research_scale))
                )
        # Cambia difficoltà, cambia manovra: le corsie già assegnate alle
        # legioni restano, la dottrina nuova vale dal prossimo obiettivo.
        self.ai_doctrine = ai_doctrine.for_difficulty(self.ai_difficulty, seed=None)
        log_entry = f"[Turno {self.game_map.turn}] ⚙ Sistema: difficoltà IA impostata su {self.ai_difficulty.upper()}"
        self.battle_log.append(log_entry)

        # A partita appena iniziata la difficoltà deve valere davvero: ogni profilo
        # costruisce l'esercito IA a modo suo (budget, qualità unità, strategia).
        # A partita in corso non si può riscrivere il passato: cambia solo la policy.
        rebuild_log = self._rebuild_ai_army_for_difficulty()
        if rebuild_log:
            self.battle_log.append(rebuild_log)

        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    # Attributi che caratterizzano una strategia come offensiva o difensiva.
    _OFFENSE_ATTRS = ("U1_attack", "U3_mobility", "U7_range_power")
    _DEFENSE_ATTRS = ("U2_defense", "U5_discipline", "U8_support")

    def _update_ai_phase_and_profile(self) -> Optional[str]:
        """Aggiorna la fase interna dell'IA leggendo lo stato reale della partita."""
        updater = getattr(self.ai_policy, "update_phase", None)
        if not callable(updater):
            return None

        stats = self.game_map.to_dict().get("stats", {})
        ai_cells = int(stats.get("ai_cells", 0))
        player_cells = int(stats.get("player_cells", 0))

        was_annihilating = bool(getattr(self.ai_policy, "is_annihilating", lambda: False)())
        phase = updater(
            turn=self.game_map.turn,
            ai_army=len(self.ai_units),
            player_army=len(self.player_units) + sum(
                len(lg.get("units", [])) for lg in self.player_legions.values()
            ),
            ai_cells=ai_cells,
            player_cells=player_cells,
            ai_grux=self.grux_balance[AI],
            player_grux=self.grux_balance[PLAYER],
            player_intruding=bool(self._ai_intruder_legions()),
        )

        now_annihilating = bool(getattr(self.ai_policy, "is_annihilating", lambda: False)())
        if now_annihilating and not was_annihilating:
            # Commutazione irreversibile: il giocatore deve accorgersene.
            for legion in self.ai_legions.values():
                legion["target"] = None
                legion["castle_commit"] = False
            return (
                f"[Turno {self.game_map.turn}] ☠️ L'IA ha raggiunto la superiorità: "
                f"abbandona la difesa e marcia per annientarti."
            )
        return None

    def _maybe_update_ai_strategy(self) -> Optional[str]:
        """Rivaluta la strategia IA sull'esercito corrente, adattandola al player."""
        review = getattr(self.ai_policy, "should_review_strategy", None)
        if not callable(review) or not review(self.game_map.turn):
            return None
        if not self.ai_units:
            return None

        terrain = self.ai_home_terrain
        if self.ai_legions:
            first = next(iter(sorted(self.ai_legions.items())))[1]
            pos = tuple(first.get("pos", ()))
            if len(pos) == 2:
                cell = self.game_map.get_cell(*pos)
                if cell is not None:
                    terrain = cell.terrain

        modified, _ = apply_modifiers(
            army_vector=self.ai_army,
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=self.ai_troop_status,
            modifiers_data=self.data,
        )
        ranking = compute_ranking(
            army_vector=modified,
            strategies_list=self.data["strategies"],
            unit_ids=self.ai_units,
            terrain_name=terrain,
            weather_name=self.weather,
            affinities_data=self.data.get("unit_affinities", {}),
        )
        if not ranking:
            return None

        bias_getter = getattr(self.ai_policy, "strategy_bias", None)
        bias = bias_getter() if callable(bias_getter) else {"offense": 0.5, "defense": 0.5}

        # Fra le strategie compatibili sceglie quella coerente con la postura
        # attuale: difensiva se il player preme, offensiva quando deve chiudere.
        def posture_score(entry: Dict[str, Any]) -> float:
            ideal = entry.get("ideal_attributes", {})
            offense = sum(float(ideal.get(a, 0.0)) for a in self._OFFENSE_ATTRS)
            defense = sum(float(ideal.get(a, 0.0)) for a in self._DEFENSE_ATTRS)
            fit = float(entry.get("compatibility", 0.0)) / 100.0
            return fit + (offense * bias.get("offense", 0.5) + defense * bias.get("defense", 0.5)) * 0.22

        best = max(ranking[: min(5, len(ranking))], key=posture_score)
        if best["id"] == self.ai_strategy_id:
            return None

        previous = self.ai_strategy_name
        self.ai_strategy_id = best["id"]
        self.ai_strategy_name = best["name"]
        profile = getattr(self.ai_policy, "player_profile", "sconosciuto")
        return (
            f"[Turno {self.game_map.turn}] 🧠 IA cambia strategia: {previous} → "
            f"{best['name']} (ti legge come '{profile}')"
        )

    def _auto_manage_ai_economy(self) -> List[str]:
        """L'IA piazza miniere disponibili e recluta automaticamente se può permetterselo."""
        logs: List[str] = []

        phase_log = self._update_ai_phase_and_profile()
        if phase_log:
            logs.append(phase_log)

        strategy_log = self._maybe_update_ai_strategy()
        if strategy_log:
            logs.append(strategy_log)

        logs.extend(self._reinforce_ai_castle_ring())
        logs.extend(self._garrison_ai_castle())
        if self.ai_policy.should_start_research(self.game_map.turn):
            # La riga di log la scrive già `_start_ability_research`: qui non
            # va rimessa nella lista, o comparirebbe due volte nel registro.
            self._run_ai_research()

        logs.extend(self._run_ai_black_market())

        ai_slots = self._available_mine_slots(AI)
        attempts = self.ai_policy.mine_attempts(ai_slots, self.game_map.turn)
        while attempts > 0 and ai_slots > 0:
            placed = self._place_best_ai_mine()
            if not placed:
                break
            logs.append(placed)
            ai_slots -= 1
            attempts -= 1

        # Fortificazione IA: la cadenza appartiene al profilo di difficoltà.
        if self.grux_balance[AI] >= self.base_fortification_cost:
            gate_getter = getattr(self.ai_policy, "fortify_turn_gate", None)
            fortify_turn_gate = max(1, int(gate_getter())) if callable(gate_getter) else 3
            if self.game_map.turn % fortify_turn_gate == 0:
                fort_log = self._place_best_ai_fortification()
                if fort_log:
                    logs.append(fort_log)

        # L'IA mette da parte i grux della ricerca che ha in programma, se no
        # non ci arriverebbe mai: alle difficoltà alte recluta ogni turno che
        # può e la cassa non supera il prezzo di un'abilità.
        recruit_budget = max(0, self.grux_balance[AI] - self._ai_research_savings())

        can_recruit_now = self._can_recruit_now(AI)
        if can_recruit_now and self.ai_policy.should_recruit(grux_balance=recruit_budget, turn=self.game_map.turn):
            affordable_units = [unit for unit in self.data["units"] if self._recruit_cost(AI, unit["id"]) <= recruit_budget]
            if affordable_units:
                best_unit = max(
                    affordable_units,
                    key=lambda unit: self._effective_unit_value_for_ai(unit),
                )
                self._recruit_unit(AI, best_unit["id"], auto=True)

        return logs

    def _recruit_cooldown_for(self, entity: Occupation) -> int:
        """Cooldown reclutamento dell'entità, abilità comprese (minimo 1 turno)."""
        # [ABILITY-EFFECTS] Industria Bellica accorcia l'attesa fra due reclute.
        bonus = ab.recruit_cooldown_bonus(self._unlocked_abilities(entity))
        return max(1, self.recruit_cooldown_turns + bonus)

    def _recruit_cost(self, entity: Occupation, unit_id: str) -> int:
        """Prezzo di una recluta per questa entità, abilità comprese."""
        base = int(self.unit_costs[unit_id])
        # [ABILITY-EFFECTS] Industria Bellica abbassa il listino delle reclute.
        factor = self._ability_economy_factor(entity, ab.ECO_RECRUIT_COST)
        if factor == 1.0:
            return base
        return max(5, int(round(base * factor)))

    def _can_recruit_now(self, entity: Occupation) -> bool:
        """True se l'entità può reclutare in questo turno (cooldown anti-spam)."""
        last_turn = self.last_recruit_turn.get(entity)
        if last_turn is None:
            return True
        return (self.game_map.turn - last_turn) >= self._recruit_cooldown_for(entity)

    def _effective_unit_value_for_ai(self, unit: Dict[str, Any]) -> float:
        """Heuristica semplice per decidere la recluta dell'IA."""
        attrs = unit["attributes"]
        return (
            attrs["U1_attack"]
            + attrs["U2_defense"]
            + attrs["U3_mobility"]
            + attrs["U6_terrain_adapt"]
            + attrs["U7_range_power"]
        )

    def _entity_units(self, entity: Occupation) -> List[str]:
        return self.player_units if entity == PLAYER else self.ai_units

    def _available_garrisons(self, entity: Occupation) -> int:
        """Unità distaccabili: sempre almeno una legione resta con l'armata principale."""
        units = self._entity_units(entity)
        return max(0, len(units) - 1)

    def is_manual_control_enabled(self) -> bool:
        return self.player_control_mode == "manual"

    def set_player_orders(
        self,
        *,
        movement_order: Optional[str] = None,
        build_order: Optional[str] = None,
        control_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Aggiorna la configurazione ordini del player (modalità graduale manual/orders)."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        changed: List[str] = []

        if control_mode is not None:
            if control_mode not in PLAYER_CONTROL_MODES:
                raise ValueError(f"Modalità controllo non valida: {control_mode}")
            if control_mode != self.player_control_mode:
                self.player_control_mode = control_mode
                changed.append(f"modalità={control_mode}")

        if movement_order is not None:
            if movement_order not in PLAYER_MOVEMENT_ORDERS:
                raise ValueError(f"Ordine movimento non valido: {movement_order}")
            if movement_order != self.player_orders.get("movement_order"):
                self.player_orders["movement_order"] = movement_order
                changed.append(f"movimento={movement_order}")

        if build_order is not None:
            if build_order not in PLAYER_BUILD_ORDERS:
                raise ValueError(f"Ordine supporto non valido: {build_order}")
            if build_order != self.player_orders.get("build_order"):
                self.player_orders["build_order"] = build_order
                changed.append(f"supporto={build_order}")

        if changed:
            log_entry = f"[Turno {self.game_map.turn}] 🧭 PLAYER aggiorna ordini: " + ", ".join(changed)
            self.battle_log.append(log_entry)
        else:
            log_entry = f"[Turno {self.game_map.turn}] 🧭 Ordini PLAYER invariati"

        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    @staticmethod
    def _order_distance(a: Tuple[int, int], b: Tuple[int, int]) -> int:
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    @staticmethod
    def _order_direction(from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> Tuple[int, int]:
        return (to_pos[0] - from_pos[0], to_pos[1] - from_pos[1])

    def _adjacent_positions(self, origin: Tuple[int, int]) -> List[Tuple[int, int]]:
        positions: List[Tuple[int, int]] = []
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = origin[0] + dr, origin[1] + dc
            if 0 <= nr < self.game_map.rows and 0 <= nc < self.game_map.cols:
                positions.append((nr, nc))
        return positions

    def _expand_direction_penalty(self, direction: Tuple[int, int]) -> float:
        last_direction = self.player_order_memory.get("last_direction")
        straight_streak = int(self.player_order_memory.get("straight_streak") or 0)
        if not isinstance(last_direction, tuple):
            return 0.0
        if direction != last_direction:
            return 0.0
        return min(1.8, 0.35 * max(0, straight_streak - 1))

    def _update_player_order_movement_memory(self, from_pos: Tuple[int, int], to_pos: Tuple[int, int]) -> None:
        direction = self._order_direction(from_pos, to_pos)
        last_direction = self.player_order_memory.get("last_direction")
        if isinstance(last_direction, tuple) and direction == last_direction:
            streak = int(self.player_order_memory.get("straight_streak") or 0) + 1
        else:
            streak = 1
        self.player_order_memory["last_direction"] = direction
        self.player_order_memory["straight_streak"] = streak

    def _frontier_pressure_score(self, pos: Tuple[int, int]) -> float:
        pressure = 0.0
        for ar, ac in self._adjacent_positions(pos):
            adjacent_cell = self.game_map.get_cell(ar, ac)
            if adjacent_cell is None:
                continue
            if adjacent_cell.occupation != PLAYER:
                pressure += 0.68
                if adjacent_cell.is_strategic:
                    pressure += 0.42
        return pressure

    def _select_player_expand_move(self) -> Optional[Tuple[int, int]]:
        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            return None

        own_castle = self.game_map.get_castle_position(PLAYER)
        enemy_castle = self.game_map.get_castle_position(AI)
        ai_pos = self.game_map.positions.get(AI)

        current_enemy_castle_dist = self._order_distance(player_pos, enemy_castle) if enemy_castle else None
        current_own_castle_dist = self._order_distance(player_pos, own_castle) if own_castle else None

        candidates: List[Tuple[float, Tuple[int, int, int], Tuple[int, int]]] = []
        for candidate in self._adjacent_positions(player_pos):
            cell = self.game_map.get_cell(*candidate)
            if cell is None:
                continue

            score = 0.0

            if cell.occupation != PLAYER:
                score += 2.6
            else:
                score -= 0.8

            if cell.occupation == AI:
                score += 1.35

            if cell.is_strategic and cell.occupation != PLAYER:
                score += 2.25

            if cell.is_mine and cell.occupation != PLAYER:
                score += 1.1

            if cell.is_castle and cell.occupation == AI:
                score += 3.0

            score += self._frontier_pressure_score(candidate)

            move_cost = self.movement_system.terrain_cost(cell.terrain)
            if move_cost > self.movement_system.points_per_turn:
                score -= (move_cost - self.movement_system.points_per_turn) / 60.0

            if enemy_castle and current_enemy_castle_dist is not None:
                next_enemy_castle_dist = self._order_distance(candidate, enemy_castle)
                castle_delta = current_enemy_castle_dist - next_enemy_castle_dist
                score += max(-0.8, min(0.8, castle_delta * 0.25))

            if own_castle and current_own_castle_dist is not None:
                next_own_castle_dist = self._order_distance(candidate, own_castle)
                outward_delta = next_own_castle_dist - current_own_castle_dist
                score += max(-0.4, min(0.6, outward_delta * 0.15))

            if ai_pos is not None:
                next_ai_dist = self._order_distance(candidate, ai_pos)
                if next_ai_dist <= 1 and len(self.player_units) < len(self.ai_units):
                    score -= 0.75
                elif next_ai_dist <= 2:
                    score += 0.15

            direction = self._order_direction(player_pos, candidate)
            score -= self._expand_direction_penalty(direction)

            tie_rank = (
                0 if cell.occupation != PLAYER else 1,
                0 if (cell.is_strategic and cell.occupation != PLAYER) else 1,
                move_cost,
            )
            candidates.append((score, tie_rank, candidate))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]

    def _select_player_order_target(self) -> Optional[Tuple[int, int]]:
        movement_order = self.player_orders.get("movement_order", "advance_castle")
        player_pos = self.game_map.positions.get(PLAYER)
        ai_pos = self.game_map.positions.get(AI)
        own_castle = self.game_map.get_castle_position(PLAYER)
        enemy_castle = self.game_map.get_castle_position(AI)

        if movement_order == "hold":
            return None

        if movement_order == "engage_ai":
            return ai_pos or enemy_castle

        if movement_order == "defend_castle":
            if ai_pos and own_castle and self._order_distance(ai_pos, own_castle) <= 4:
                return ai_pos
            return own_castle or ai_pos or enemy_castle

        if movement_order == "expand_front":
            targets = self.game_map.get_strategic_targets(
                entity=PLAYER,
                army_vector=self.player_army,
                terrain_modifiers=self.data["terrain"],
            )
            if targets:
                _, cell = targets[0]
                return (cell.row, cell.col)
            return enemy_castle or ai_pos

        # default: advance_castle
        if enemy_castle is not None:
            return enemy_castle
        return ai_pos

    def _select_player_order_move(self) -> Optional[Tuple[int, int]]:
        movement_order = self.player_orders.get("movement_order", "advance_castle")
        if movement_order == "expand_front":
            expand_move = self._select_player_expand_move()
            if expand_move is not None:
                return expand_move

        target = self._select_player_order_target()
        if target is None:
            return None
        return self.game_map.best_move_toward(PLAYER, target)

    def _choose_player_order_mine_cell(self) -> Optional[Tuple[int, int]]:
        if self._available_mine_slots(PLAYER) <= 0:
            return None

        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            return None

        if not self._is_ability_unlocked(PLAYER, DOMAIN_ENGINEERING_ID):
            cell = self.game_map.get_cell(*player_pos)
            if cell and cell.occupation == PLAYER and not cell.is_castle and not cell.is_mine and cell.terrain != "Fiume":
                return player_pos
            return None

        ai_pos = self.game_map.positions.get(AI)
        best: Optional[Tuple[float, Tuple[int, int]]] = None
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != PLAYER or cell.is_castle or cell.is_mine or cell.terrain == "Fiume":
                    continue
                score = 0.0
                if cell.is_strategic:
                    score += 2.8
                if cell.terrain in {"Pianura", "Montagna"}:
                    score += 1.1
                if ai_pos is not None:
                    score -= self._order_distance((cell.row, cell.col), ai_pos) * 0.05
                score -= self._order_distance((cell.row, cell.col), player_pos) * 0.02
                if best is None or score > best[0]:
                    best = (score, (cell.row, cell.col))

        return best[1] if best else None

    def _choose_player_order_fortification_cell(self) -> Optional[Tuple[int, int]]:
        player_pos = self.game_map.positions.get(PLAYER)
        if player_pos is None:
            return None

        if not self._is_ability_unlocked(PLAYER, DOMAIN_ENGINEERING_ID):
            cell = self.game_map.get_cell(*player_pos)
            if cell and cell.occupation == PLAYER and not cell.is_castle:
                return player_pos
            return None

        best: Optional[Tuple[Tuple[int, int, int], Tuple[int, int]]] = None
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != PLAYER or cell.is_castle:
                    continue
                # Priorità: celle strategiche, poi livelli fortificazione più bassi.
                rank = (
                    0 if cell.is_strategic else 1,
                    cell.fortification_level,
                    self._order_distance((cell.row, cell.col), player_pos),
                )
                if best is None or rank < best[0]:
                    best = (rank, (cell.row, cell.col))

        return best[1] if best else None

    def _run_player_order_build_phase(self) -> List[str]:
        logs: List[str] = []
        build_order = self.player_orders.get("build_order", "balanced")

        if build_order == "none":
            return logs

        if build_order == "economy":
            plan = ["mine"]
        elif build_order == "fortify":
            plan = ["fortify"]
        elif build_order == "garrison":
            plan = ["garrison"]
        else:
            plan = ["mine", "fortify", "garrison"]

        for step in plan:
            try:
                if step == "mine":
                    legion_id = self._find_first_legion_of_type(PLAYER, LEGION_TYPE_MINING)
                    if legion_id is None:
                        continue
                    result = self.place_mine(legion_id)
                    logs.append(result["message"])
                    break

                if step == "fortify":
                    legion_id = self._find_first_legion_of_type(PLAYER, LEGION_TYPE_CONSTRUCTION)
                    if legion_id is None:
                        continue
                    result = self.place_fortification(legion_id)
                    logs.append(result["message"])
                    break

                if step == "garrison":
                    legion_id = self._find_first_legion_with_spare_units(PLAYER)
                    if legion_id is None:
                        continue
                    result = self.place_garrison(legion_id)
                    logs.append(result["message"])
                    break
            except ValueError:
                continue

        return logs

    def _pass_turn_without_player_move(self, message: str, build_logs: Optional[List[str]] = None) -> Dict[str, Any]:
        self.battle_log.append(message)

        self.game_map.end_turn()
        ai_result = self._ai_turn()

        if self.state == SessionState.ACTIVE:
            economy_logs = self._advance_round_economy()
            if economy_logs:
                self.battle_log.extend(economy_logs)

        result: Dict[str, Any] = {
            "ok": True,
            "skipped": True,
            "message": message,
            "battle_result": None,
            "ai_move_result": ai_result,
            "game_over": self.state == SessionState.GAME_OVER,
            "winner": self.winner,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "order_mode": True,
            "session": self.to_dict(),
        }
        if build_logs:
            result["build_logs"] = build_logs
        return result

    def execute_turn(self) -> dict:
        """Avanza il turno di tutte le legioni e risolve i conflitti."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("Partita terminata.")

        logs = []

        # 1. Movimento Legioni Player
        for legion_id, legion in list(self.player_legions.items()):
            # Ordine di cattura d'area: la meta di questo turno esce dalla coda
            # delle caselle che restano da prendere.
            self._refresh_capture_area(legion, logs)

            target = legion.get("target")
            target_pos = tuple(target) if target is not None else None
            current_pos = tuple(legion.get("pos", ()))
            if target_pos is None or len(current_pos) != 2 or len(target_pos) != 2:
                continue
            if current_pos == target_pos:
                continue

            # Terreno difficile: la legione può essere ancora in marcia dal turno scorso.
            if self._legion_is_movement_blocked(PLAYER, legion_id, legion, logs):
                continue

            next_pos, resolution = self._next_legion_step(
                current_pos, target_pos, PLAYER, legion_id,
                origin=self._march_origin(legion, current_pos, target_pos),
            )
            self._log_legion_fallback(legion, "PLAYER", target_pos, next_pos, resolution, logs)
            if next_pos == current_pos:
                continue
            legion["pos"] = next_pos
            self._register_legion_move_cost(PLAYER, legion_id, legion, current_pos, next_pos)

            row, col = next_pos
            cell = self.game_map.get_cell(row, col)
            # Terreno attraversato: la fatica viene contata a fine turno.
            legion["marched_terrain"] = cell.terrain if cell is not None else "Pianura"
            if cell and getattr(cell, "occupation", None) != PLAYER:
                cell.occupation = PLAYER
                logs.append(f"⚔️ La legione PLAYER '{legion['name']}' conquista la cella ({row},{col}).")

            self._apply_legion_castle_assault(PLAYER, legion, current_pos, next_pos, logs)
            if tuple(legion.get("pos", ())) != next_pos:
                continue

            self._resolve_legion_clash_if_any(next_pos, logs, attacker=PLAYER)
            if self.state != SessionState.ACTIVE:
                break

        # 2. Movimento Legioni IA
        ai_moved = False
        ai_skipped = False
        # [DEBUG-MODULE] Gate del kill switch nel ciclo vivo dell'IA.
        if self.state == SessionState.ACTIVE and self.debug_ai_kill_switch:
            # Kill switch: l'IA è completamente congelata. Il controllo va qui,
            # nel ciclo vivo: quello storico stava in `_ai_turn`, cioè nel vecchio
            # sistema a singola armata ormai irraggiungibile, quindi le legioni
            # continuavano a muoversi, conquistare e assaltare a switch attivo.
            ai_skipped = True
            logs.append(
                f"[Turno {self.game_map.turn}] 🧪 IA CONGELATA (kill switch attivo): "
                f"nessun movimento, nessuna costruzione, nessuna recluta."
            )
        elif self.state == SessionState.ACTIVE:
            self._ensure_ai_legions_initialized()
            # Rete di sicurezza: assorbe qualsiasi disallineamento legione/esercito IA
            # maturato fuori dai punti di mutazione noti (recluta, perdite).
            self._sync_ai_legion_units()
            if self.ai_policy.should_skip_turn(self.game_map.turn):
                ai_skipped = True
                logs.append(f"[Turno {self.game_map.turn}] IA esita e mantiene la posizione.")
            else:
                # Nemico dentro casa: la dottrina sospende manovre e attese.
                under_threat = bool(self._ai_intruder_legions())
                for legion_index, (legion_id, legion) in enumerate(list(self.ai_legions.items())):
                    current_pos = tuple(legion.get("pos", ()))
                    if len(current_pos) != 2:
                        continue

                    # Stesso vincolo del player: nessuna corsia preferenziale per l'IA.
                    if self._legion_is_movement_blocked(AI, legion_id, legion, logs):
                        continue

                    target_pos = self._pick_ai_legion_target(legion)
                    if target_pos is None:
                        continue

                    # La dottrina trasforma l'obiettivo in manovra: corsia,
                    # aggiramento, giro largo o sosta.
                    plan = self._ai_doctrine_plan(
                        legion, legion_index, current_pos, target_pos, under_threat
                    )
                    if plan.hold:
                        ai_moved = True   # è una scelta, non immobilismo
                        logs.append(
                            f"🤖 La legione IA '{legion['name']}' resta in {plan.reason} "
                            f"su {current_pos}."
                        )
                        continue
                    if plan.target is not None:
                        target_pos = tuple(plan.target)

                    lock_until = int(legion.get("target_lock_until", 0) or 0)
                    existing_target_raw = legion.get("target")
                    existing_target: Tuple[int, int] | Tuple[()] = ()
                    if isinstance(existing_target_raw, (list, tuple)) and len(existing_target_raw) == 2:
                        existing_target = (int(existing_target_raw[0]), int(existing_target_raw[1]))

                    if len(existing_target) == 2 and self.game_map.turn <= lock_until:
                        target_pos = existing_target
                    else:
                        legion["target"] = target_pos
                        legion["target_lock_until"] = self.game_map.turn + self._ai_legion_target_lock_turns()

                    next_pos, resolution = self._next_legion_step(
                        current_pos, target_pos, AI, legion_id, lane_col=plan.lane_col,
                        origin=self._march_origin(legion, current_pos, target_pos),
                    )
                    self._log_legion_fallback(legion, "IA", target_pos, next_pos, resolution, logs)
                    if next_pos == current_pos:
                        if resolution["blocked_by"]:
                            # Non c'è nemmeno un ripiego utile: sblocca il target
                            # invece di restare incollata al lock a fissare il muro.
                            legion["target_lock_until"] = 0
                        continue

                    ai_moved = True
                    legion["pos"] = next_pos
                    self._register_legion_move_cost(AI, legion_id, legion, current_pos, next_pos)

                    row, col = next_pos
                    cell = self.game_map.get_cell(row, col)
                    # Stessa regola del player: la fatica si conta a fine turno.
                    legion["marched_terrain"] = cell.terrain if cell is not None else "Pianura"
                    if cell and getattr(cell, "occupation", None) != AI:
                        cell.occupation = AI
                        logs.append(f"🤖 La legione IA '{legion['name']}' conquista la cella ({row},{col}).")

                    self._apply_legion_castle_assault(AI, legion, current_pos, next_pos, logs)
                    if tuple(legion.get("pos", ())) != next_pos:
                        continue

                    self._resolve_legion_clash_if_any(next_pos, logs, attacker=AI)
                    if self.state != SessionState.ACTIVE:
                        break

        if self.state == SessionState.ACTIVE and not ai_moved and not ai_skipped:
            logs.append("🤖 L'IA resta in attesa strategica.")

        # 3. Aggiorna economia (miniere e reclute)
        if self.state == SessionState.ACTIVE:
            econ_logs = self._advance_round_economy()
            if econ_logs:
                logs.extend(econ_logs)

        # 4. Stanchezza, morale e gradi: una sola passata a fine turno, così
        #    ogni legione paga la marcia o incassa il riposo esattamente una volta.
        if self.state == SessionState.ACTIVE:
            self._advance_troop_conditions(logs)
            self._advance_weather(logs)

        self._prune_legion_movement_states()

        self.game_map.turn += 1
        self.battle_log.extend(logs)

        return {
            "ok": True,
            "message": "Turno eseguito.",
            "session": self.to_dict(),
            "logs": logs
        }

    def resolve_player_order_turn(self) -> Dict[str, Any]:
        """Esegue un turno completo secondo gli ordini impostati (player -> IA -> economia)."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if self.player_control_mode != "orders":
            raise ValueError("Controllo manuale attivo: passa prima alla modalità ordini.")

        build_logs = self._run_player_order_build_phase()
        movement_order = self.player_orders.get("movement_order", "advance_castle")
        next_move = self._select_player_order_move()

        if next_move is None:
            wait_message = (
                f"[Turno {self.game_map.turn}] 🧭 PLAYER mantiene posizione "
                f"(ordine movimento: {movement_order})"
            )
            return self._pass_turn_without_player_move(wait_message, build_logs=build_logs)

        player_from_pos = self.game_map.positions.get(PLAYER)
        move_result = self.player_move(
            next_move[0],
            next_move[1],
            leave_garrison=False,
            garrison_unit_id=None,
        )

        if not move_result.get("ok", False):
            fallback_message = (
                f"[Turno {self.game_map.turn}] 🧭 Ordine PLAYER non eseguibile: "
                f"{move_result.get('message', 'mossa non valida')}"
            )
            return self._pass_turn_without_player_move(fallback_message, build_logs=build_logs)

        if player_from_pos is not None and not move_result.get("skipped", False):
            self._update_player_order_movement_memory(player_from_pos, next_move)

        move_result["order_mode"] = True
        move_result["session"] = self.to_dict()
        if build_logs:
            move_result["build_logs"] = build_logs
        return move_result

    def _detach_unit_to_garrison(
        self,
        entity: Occupation,
        cell_pos: Tuple[int, int],
        unit_id: Optional[str],
        auto: bool,
    ) -> Dict[str, Any]:
        """Distacca una specifica unità dall'armata e la assegna alla guarnigione della cella."""
        units = self._entity_units(entity)
        if self._available_garrisons(entity) <= 0:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError("Non hai unità sufficienti per lasciare un presidio.")

        selected_unit_id: Optional[str] = unit_id
        if selected_unit_id is None:
            sorted_units = sorted(units, key=lambda uid: self._unit_battle_value(uid))
            selected_unit_id = sorted_units[0] if sorted_units else None

        if selected_unit_id is None or selected_unit_id not in units:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError("La truppa selezionata non è disponibile per il presidio.")

        cell = self.game_map.get_cell(*cell_pos)
        if cell is None:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError("Cella presidio non valida.")
        full = self._garrison_full_error(cell)
        if full:
            if auto:
                return {"unit_id": None, "unit_name": ""}
            raise ValueError(full)

        units.remove(selected_unit_id)
        cell.garrison_unit_ids.append(selected_unit_id)
        cell.garrison_strength = max(cell.garrison_strength, len(cell.garrison_unit_ids))
        self._recompute_entity_army_state(entity)

        unit_name = self.units_map.get(selected_unit_id, {}).get("name", selected_unit_id)
        return {
            "unit_id": selected_unit_id,
            "unit_name": unit_name,
        }

    def _empty_army_vector(self) -> Dict[str, float]:
        return {
            "U1_attack": 0.0,
            "U2_defense": 0.0,
            "U3_mobility": 0.0,
            "U4_stealth": 0.0,
            "U5_discipline": 0.0,
            "U6_terrain_adapt": 0.0,
            "U7_range_power": 0.0,
            "U8_support": 0.0,
        }

    def _recompute_entity_army_state(self, entity: Occupation) -> None:
        units = self._entity_units(entity)
        if units:
            army_vector = aggregate_army(units, self.data["units"])
        else:
            army_vector = self._empty_army_vector()
        home_terrain = self.player_home_terrain if entity == PLAYER else self.ai_home_terrain
        troop_status = self.player_troop_status if entity == PLAYER else self.ai_troop_status
        if units:
            modified, _ = apply_modifiers(
                army_vector=army_vector,
                terrain_name=home_terrain,
                weather_name=self.weather,
                troop_status_name=troop_status,
                modifiers_data=self.data,
            )
        else:
            modified = army_vector.copy()

        army_cost = sum(self.unit_costs.get(unit_id, 0) for unit_id in units)
        if entity == PLAYER:
            self.player_army = army_vector
            self.player_modified = modified
            self.player_army_cost = army_cost
        else:
            self.ai_army = army_vector
            self.ai_modified = modified
            self.ai_army_cost = army_cost

    def _apply_attacker_losses(self, attacker: Occupation, losses: int) -> Dict[str, Any]:
        units = self._entity_units(attacker)
        if losses <= 0 or not units:
            return {"losses": 0, "removed_units": [], "removed_text": ""}

        losses = min(losses, len(units))
        sorted_for_losses = sorted(units, key=lambda unit_id: self._unit_battle_value(unit_id))
        removed = sorted_for_losses[:losses]
        for unit_id in removed:
            units.remove(unit_id)
        self.troops_lost[attacker] += losses      # [ENDGAME-STATS]

        self._recompute_entity_army_state(attacker)
        if attacker == AI:
            self._sync_ai_legion_units()

        removed_counts: Dict[str, int] = dict(Counter(removed))
        removed_parts: List[str] = []
        for unit_id, count in sorted(removed_counts.items(), key=lambda item: (-item[1], item[0])):
            unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
            removed_parts.append(f"{count} {unit_name}")

        return {
            "losses": losses,
            "removed_units": removed,
            "removed_text": ", ".join(removed_parts),
        }

    def _calculate_losses_for_battle(
        self,
        units_before: int,
        own_strength: float,
        enemy_strength: float,
        *,
        fortification_level: int = 0,
        garrison_strength: int = 0,
    ) -> int:
        """Regola perdite condivisa: attrito progressivo, meno wipe istantanei."""
        if units_before <= 0:
            return 0

        if enemy_strength <= 0:
            return 0

        if own_strength <= 0:
            return units_before

        weaker_side = own_strength <= enemy_strength

        if weaker_side:
            disadvantage = 1.0 - min(1.0, own_strength / max(1.0, enemy_strength))
            loss_ratio = (
                0.30
                + (0.34 * disadvantage)
                + (0.03 * fortification_level)
                + (0.02 * garrison_strength)
            )
            loss_ratio = min(0.88, max(0.24, loss_ratio))
        else:
            pressure_ratio = min(1.0, enemy_strength / max(1.0, own_strength))
            loss_ratio = (
                0.05
                + (0.24 * pressure_ratio)
                + (0.02 * fortification_level)
                + (0.015 * garrison_strength)
            )
            loss_ratio = min(0.52, max(0.03, loss_ratio))

        losses = int(round(units_before * loss_ratio))

        catastrophic_gap = own_strength < (enemy_strength * 0.32)
        if units_before > 1:
            losses = max(1, losses)
            if catastrophic_gap and weaker_side:
                losses = min(units_before, losses)
            else:
                losses = min(units_before - 1, losses)
        else:
            losses = min(units_before, losses)
        return losses

    def _unit_battle_value(self, unit_id: str) -> float:
        """Valore base di una singola legione/unità in combattimento.

        Include le condizioni ambientali correnti: l'artiglieria sotto la
        pioggia vale meno, gli assassini di notte valgono di più. Passando da
        qui l'effetto arriva ovunque si conti una truppa — legioni in campo,
        presidi, difesa del castello, assalti, IA compresa — senza doverlo
        ripetere in ogni formula.
        """
        attrs = self.units_map[unit_id]["attributes"]
        weighted = sum(attrs[key] * weight for key, weight in UNIT_BATTLE_WEIGHTS.items())
        return weighted * self._weather_unit_factor(unit_id)

    def _weather_unit_factor(self, unit_id: str) -> float:
        """Moltiplicatore meteo della singola unità, con cache per condizione.

        `_unit_battle_value` viene chiamato migliaia di volte per turno e il
        fattore dipende solo da (condizioni, unità): si calcola una volta per
        combinazione e le condizioni cambiano ogni 20+ turni.
        """
        cache = getattr(self, "_weather_unit_cache", None)
        if cache is None:
            cache = self._weather_unit_cache = {}

        key = (self.weather, unit_id)
        if key not in cache:
            cache[key] = wc.unit_weather_factor(
                self.units_map[unit_id]["attributes"],
                self.weather,
                self.data,
                UNIT_BATTLE_WEIGHTS,
            )
        return cache[key]

    def _garrison_unit_defense_value(self, unit_id: str, terrain: str) -> float:
        """Valore difensivo di una unità distaccata, modulato dal terreno corrente."""
        base_value = self._unit_battle_value(unit_id)
        attrs = self.units_map[unit_id]["attributes"]

        terrain_lower = terrain.lower()
        terrain_factor = 1.0 + (attrs["U6_terrain_adapt"] * 0.18)

        if terrain_lower == "foresta":
            terrain_factor += (attrs["U4_stealth"] * 0.08) + (attrs["U3_mobility"] * 0.04)
        elif terrain_lower == "palude":
            terrain_factor += (attrs["U6_terrain_adapt"] * 0.08) + (attrs["U3_mobility"] * 0.05)
        elif terrain_lower == "montagna":
            terrain_factor += (attrs["U2_defense"] * 0.08) + (attrs["U5_discipline"] * 0.04)
        elif terrain_lower == "pianura":
            terrain_factor += (attrs["U1_attack"] * 0.05) + (attrs["U7_range_power"] * 0.03)
        elif terrain_lower == "fiume":
            terrain_factor += (attrs["U3_mobility"] * 0.08) + (attrs["U6_terrain_adapt"] * 0.08)

        return base_value * terrain_factor

    def _army_composition(self, entity: Occupation) -> Dict[str, int]:
        """Composizione esercito per tipo unità (id -> conteggio)."""
        unit_ids = self.player_units if entity == PLAYER else self.ai_units
        return dict(Counter(unit_ids))

    def _format_composition(self, entity: Occupation) -> str:
        """Stringa leggibile della composizione in legioni."""
        composition = self._army_composition(entity)
        if not composition:
            return "nessuna legione"

        parts: List[str] = []
        for unit_id, count in sorted(composition.items(), key=lambda item: (-item[1], item[0])):
            unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
            parts.append(f"{count} legioni {unit_name}")
        return ", ".join(parts)

    def _format_battle_location(self, terrain: str) -> str:
        """Rende il tipo battaglia con preposizione naturale in base al terreno."""
        prepositions = {
            "foresta": "nella",
            "palude": "nella",
            "montagna": "sulla",
            "pianura": "sulla",
            "fiume": "sul",
        }
        terrain_lower = terrain.lower()
        preposition = prepositions.get(terrain_lower, "su")
        return f"⚔ Battaglia {preposition} {terrain_lower}"

    def _strategy_factor(
        self,
        entity: Occupation,
        terrain: str,
        modified_vector: Dict[str, float],
        strategy_id: Optional[str] = None,
    ) -> float:
        """Fattore tattico legato alla qualità della manovra scelta rispetto all'esercito corrente."""
        compatibility = self._strategy_compatibility(entity, modified_vector, strategy_id)

        # Impatto strategico intenzionalmente forte:
        # - strategia affine => moltiplicatore molto alto
        # - strategia disallineata => malus severo
        # - soglie critiche per premiare/penalizzare scelte estreme
        base_factor = 0.38 + ((compatibility ** 2.6) * 1.92)

        critical_bonus = 0.0
        if compatibility >= 0.88:
            critical_bonus += 0.22
        elif compatibility >= 0.78:
            critical_bonus += 0.12

        critical_malus = 0.0
        if compatibility <= 0.22:
            critical_malus += 0.22
        elif compatibility <= 0.32:
            critical_malus += 0.12

        factor = base_factor + critical_bonus - critical_malus
        return max(0.30, min(2.35, factor))

    def _strategy_compatibility(
        self,
        entity: Occupation,
        modified_vector: Dict[str, float],
        strategy_id: Optional[str] = None,
    ) -> float:
        """Compatibilità [0..1] tra esercito modificato e strategia.

        `strategy_id` permette di valutare la strategia di una singola legione
        invece di quella globale dello schieramento.
        """
        if strategy_id is None:
            strategy_id = self.player_strategy_id if entity == PLAYER else self.ai_strategy_id
        strategy = next((s for s in self.data["strategies"] if s["id"] == strategy_id), None)
        if strategy is None:
            return 0.5

        distance = euclidean_distance(modified_vector, strategy["ideal_attributes"])
        return max(0.0, min(1.0, 1.0 - (distance / (8 ** 0.5))))

    def _current_army_terrain(self, entity: Occupation) -> str:
        """Terreno attuale dell'armata, fallback al terreno base se la posizione non è valida."""
        pos = self.game_map.positions.get(entity)
        if pos is not None:
            cell = self.game_map.get_cell(*pos)
            if cell is not None:
                return cell.terrain
        return self.player_home_terrain if entity == PLAYER else self.ai_home_terrain

    # ──────────────────────────────────────────────────────────
    # CONDIZIONE TRUPPE (stanchezza / morale / grado)
    # ──────────────────────────────────────────────────────────

    def _initial_troop_status(self, entity: Occupation) -> str:
        """Stato di riferimento dello schieramento, scelto prima della battaglia."""
        chosen = self.player_troop_status if entity == PLAYER else self.ai_troop_status
        return chosen if chosen in tc.ALL_STATUSES else tc.STATUS_FRESH

    def _legion_condition(self, entity: Occupation, legion: Dict[str, Any]) -> Dict[str, Any]:
        return tc.ensure_condition(legion, self._initial_troop_status(entity))

    def _legion_troop_status(self, entity: Occupation, legion: Dict[str, Any]) -> str:
        """Stato truppe di una legione: è il metro usato in combattimento."""
        return tc.resolve_status(self._legion_condition(entity, legion))

    def _distance_from_home(self, entity: Occupation, pos: Tuple[int, int]) -> int:
        """Distanza dal proprio castello, in celle."""
        castle = self.game_map.castle_positions.get(entity)
        if castle is None or len(pos) != 2:
            return 0
        return abs(int(pos[0]) - int(castle[0])) + abs(int(pos[1]) - int(castle[1]))

    def _log_condition_change(
        self,
        entity: Occupation,
        legion: Dict[str, Any],
        before: str,
        logs: List[str],
    ) -> None:
        """Annota il passaggio di stato, che altrimenti resterebbe invisibile."""
        after = tc.resolve_status(self._legion_condition(entity, legion))
        if after == before:
            return
        condition = self._legion_condition(entity, legion)
        icons = {
            tc.STATUS_FRESH: "🌿",
            tc.STATUS_TIRED: "😓",
            tc.STATUS_DEMORALIZED: "💔",
            tc.STATUS_VETERAN: "🎖",
        }
        extra = ""
        if after == tc.STATUS_VETERAN and before != tc.STATUS_VETERAN and condition.get("veteran"):
            extra = f" — {condition.get('victories', 0)} vittorie sul campo"
        logs.append(
            f"[Turno {self.game_map.turn}] {icons.get(after, '•')} {entity.value.upper()}: "
            f"legione '{legion.get('name', '?')}' {before} → {after}{extra}"
        )

    # ──────────────────────────────────────────────────────────
    # METEO E CICLO GIORNO/NOTTE
    # ──────────────────────────────────────────────────────────

    def _refresh_weather_key(self) -> None:
        """Riallinea la chiave passata all'engine ai due assi correnti."""
        self.weather = wc.combined_key(self.day_cycle, self.weather_base)

    def _advance_weather(self, logs: List[str]) -> None:
        """Fa scorrere ciclo e meteo sui loro due orologi indipendenti.

        Cambiano di rado apposta: sotto i 20 turni diventerebbero rumore e
        renderebbero imprevedibile ogni pianificazione a lungo termine.
        """
        self.turns_to_weather_change -= 1
        if self.turns_to_weather_change > 0:
            return

        self.day_cycle, self.weather_base = wc.advance(
            self.day_cycle, self.weather_base, self.weather_rng
        )
        self.turns_to_weather_change = wc.next_change_delay(self.weather_rng)
        self._refresh_weather_key()
        info = self.weather_state()
        effetti = " · ".join(info["effects"])
        logs.append(
            f"[Turno {self.game_map.turn}] {info['emoji']} Condizioni: "
            f"{info['label']} — {effetti}"
        )

        # Chi ci guadagna e chi ci perde davvero, in numeri: senza questa riga
        # il cambio di condizioni restava una scritta senza conseguenze visibili.
        movers = self._weather_unit_effects(limit=4)
        if movers:
            dettaglio = ", ".join(
                f"{row['unit_name']} {row['percent']:+d}%" for row in movers
            )
            logs.append(f"[Turno {self.game_map.turn}] Effetto sulle truppe: {dettaglio}")

    def weather_state(self) -> Dict[str, Any]:
        """Payload dell'indicatore meteo (emoji, colori, effetti, countdown)."""
        state = wc.describe(
            self.day_cycle,
            self.weather_base,
            changes_in=self.turns_to_weather_change,
        )
        # Chi guadagna e chi perde adesso, in chiaro: il giocatore deve poter
        # decidere quale legione muovere senza andare a leggere il JSON.
        state["unit_effects"] = self._weather_unit_effects()
        return state

    def _weather_unit_effects(self, limit: int = 0) -> List[Dict[str, Any]]:
        """Effetto delle condizioni correnti su ogni tipo di unità."""
        return wc.unit_effects(
            self.data.get("units", []),
            self.weather,
            self.data,
            UNIT_BATTLE_WEIGHTS,
            limit=limit,
        )

    def _advance_troop_conditions(self, logs: List[str]) -> None:
        """Chiude il turno per ogni legione: marcia, riposo, cambio di stato.

        Chi si è mosso paga la fatica del terreno attraversato; chi ha
        combattuto ha già pagato nello scontro; chi è rimasto fermo recupera,
        tanto meno quanto è lontano da casa.
        """
        for entity, legions in ((PLAYER, self.player_legions), (AI, self.ai_legions)):
            for legion in list(legions.values()):
                condition = self._legion_condition(entity, legion)
                before = tc.resolve_status(condition)

                terrain = legion.pop("marched_terrain", None)
                traversing = legion.pop("traversing_terrain", None)
                acted = bool(legion.pop("acted_this_turn", False))

                if terrain is not None:
                    tc.apply_march(condition, terrain)
                elif traversing is not None:
                    tc.apply_traversal(condition, traversing)
                elif not acted:
                    tc.apply_rest(
                        condition,
                        self._distance_from_home(entity, tuple(legion.get("pos", ()))),
                    )

                # Il morale risale piano in ogni turno senza combattimenti,
                # anche marciando: si perde per le sconfitte, non per la strada.
                if not acted:
                    tc.apply_morale_drift(condition)

                self._log_condition_change(entity, legion, before, logs)

    def _merge_legion_into_reserve(self, entity: Occupation, legion: Dict[str, Any]) -> None:
        """Le truppe richiamate si mescolano alla riserva, condizione compresa."""
        condition = self._legion_condition(entity, legion)
        reserve = self._entity_units(entity)
        tc.merge_into_pool(
            self.reserve_condition[entity],
            len(reserve),
            condition,
            len(legion.get("units", [])),
        )

    def _legions_with_strategy(self, entity: Occupation) -> Dict[str, Dict[str, Any]]:
        """Legioni per il payload, con strategia risolta e nome leggibile.

        Il frontend deve poter mostrare la strategia di ogni legione senza
        rifare il ripiego sulla strategia globale.
        """
        source = self.player_legions if entity == PLAYER else self.ai_legions
        out: Dict[str, Dict[str, Any]] = {}
        for legion_id, legion in source.items():
            strategy_id = self._legion_strategy_id(entity, legion)
            condition = self._legion_condition(entity, legion)
            out[legion_id] = {
                **legion,
                "strategy_id": strategy_id,
                "strategy_name": self.strategies_map.get(strategy_id, {}).get(
                    "name", strategy_id
                ),
                "troop_status": tc.resolve_status(condition),
                "condition": tc.describe(condition),
            }
        return out

    def _legion_strategy_id(self, entity: Occupation, legion: Dict[str, Any]) -> str:
        """Strategia di una legione, con ripiego su quella generale dello schieramento.

        Le legioni nate prima che le strategie diventassero individuali non
        hanno il campo: per loro vale ancora quella globale.
        """
        default = self.player_strategy_id if entity == PLAYER else self.ai_strategy_id
        strategy_id = legion.get("strategy_id") or default
        return strategy_id if strategy_id in self.strategies_map else default

    def set_legion_strategy(self, legion_id: str, strategy_id: str) -> Dict[str, Any]:
        """Assegna una strategia a una singola legione player."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        legion = self._get_player_legion_or_raise(legion_id)
        strategy = self.strategies_map.get(strategy_id)
        if strategy is None:
            raise ValueError("Strategia non valida.")

        legion["strategy_id"] = strategy_id

        pos = tuple(legion.get("pos", ()))
        cell = self.game_map.get_cell(*pos) if len(pos) == 2 else None
        terrain = cell.terrain if cell is not None else self.player_home_terrain
        breakdown = self._legion_battle_strength(
            PLAYER, legion, terrain,
            defending=False, cell=cell, enemy_strength=0.0, movement_key=None,
        )

        log_entry = (
            f"[Turno {self.game_map.turn}] 🎯 PLAYER: legione '{legion['name']}' adotta "
            f"{strategy['name']} → forza {int(round(breakdown['strength']))} su {terrain}"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "legion_id": legion_id,
            "strategy_id": strategy_id,
            "strategy_name": strategy["name"],
            "strength": int(round(breakdown["strength"])),
            "strategy_factor": round(breakdown["strategy_factor"], 3),
            "state": self.state.value,
            "session": self.to_dict(),
        }

    def set_player_strategy(self, strategy_id: str) -> Dict[str, Any]:
        """Aggiorna la strategia corrente del player e logga snapshot forza attuale."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        strategy = self.strategies_map.get(strategy_id)
        if strategy is None:
            raise ValueError("Strategia non valida.")

        self.player_strategy_id = strategy_id
        terrain = self._current_army_terrain(PLAYER)
        breakdown = self._strength_breakdown(PLAYER, terrain)
        strength_now = breakdown["effective_strength"]
        reserve_units = len(self.player_units)

        # Questa è la strategia GENERALE, che vale per la riserva e per le
        # legioni che nasceranno: non per quelle già in campo, che hanno la
        # propria. Con tutte le truppe in legione la riserva è vuota e la
        # vecchia riga diceva "forza attuale 0", che sembrava un guasto.
        if reserve_units:
            dettaglio = f"forza riserva {strength_now} su {terrain} ({reserve_units} unità)"
        else:
            dettaglio = "riserva vuota: varrà per le prossime legioni"

        log_entry = (
            f"[Turno {self.game_map.turn}] 🎯 PLAYER imposta strategia generale "
            f"{strategy['name']} → {dettaglio}"
        )
        self.battle_log.append(log_entry)
        log_strength_debug(
            "strategy_change_strength_snapshot",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "entity": PLAYER.value,
                "strategy_id": strategy_id,
                "strategy_name": strategy["name"],
                "terrain": terrain,
                "strength_breakdown": breakdown,
            },
        )

        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def get_in_game_advisor(self) -> Dict[str, Any]:
        """Report advisor in-battle: uno per la riserva, uno per ogni legione in campo.

        Ogni legione ha la propria composizione, il proprio terreno e la propria
        strategia, quindi il consiglio va calcolato su di lei: un solo report
        globale descriveva un esercito che sul campo non esiste più.
        """
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        terrain_name = self._current_army_terrain(PLAYER)
        reserve_status = tc.resolve_status(self.reserve_condition[PLAYER])
        payload = build_in_game_advisor_payload(
            data=self.data,
            turn=self.game_map.turn,
            player_units=list(self.player_units),
            player_army=dict(self.player_army),
            player_strategy_id=self.player_strategy_id,
            troop_status_name=reserve_status,
            terrain_name=terrain_name,
            weather_name=self.weather,
        )
        payload["troop_condition"] = tc.describe(self.reserve_condition[PLAYER])
        payload["scope"] = "reserve"
        payload["legion_id"] = None
        payload["legion_name"] = "Riserva nel castello"
        payload["current_strategy_id"] = self.player_strategy_id
        payload["current_strategy_name"] = self.strategies_map.get(
            self.player_strategy_id, {}
        ).get("name", self.player_strategy_id)
        payload["units_count"] = len(self.player_units)

        payload["legions"] = [
            self._legion_advisor_payload(legion_id, legion)
            for legion_id, legion in self.player_legions.items()
        ]
        return payload

    def _legion_advisor_payload(self, legion_id: str, legion: Dict[str, Any]) -> Dict[str, Any]:
        """Report advisor calcolato sulla singola legione."""
        unit_ids = list(legion.get("units", []))
        pos = tuple(legion.get("pos", ()))
        cell = self.game_map.get_cell(*pos) if len(pos) == 2 else None
        terrain_name = cell.terrain if cell is not None else self.player_home_terrain
        strategy_id = self._legion_strategy_id(PLAYER, legion)
        condition = self._legion_condition(PLAYER, legion)
        troop_status = tc.resolve_status(condition)

        if not unit_ids:
            return {
                "scope": "legion",
                "legion_id": legion_id,
                "legion_name": legion.get("name", legion_id),
                "legion_type": legion.get("legion_type", LEGION_TYPE_ARMY),
                "legion_type_label": LEGION_TYPE_LABELS.get(
                    legion.get("legion_type", LEGION_TYPE_ARMY), ""
                ),
                "pos": list(pos) if len(pos) == 2 else None,
                "terrain_name": terrain_name,
                "units_count": 0,
                "current_strategy_id": strategy_id,
                "current_strategy_name": self.strategies_map.get(strategy_id, {}).get(
                    "name", strategy_id
                ),
                "troop_status_name": troop_status,
                "troop_condition": tc.describe(condition),
                "empty": True,
                "ranking": [],
            }

        payload = build_in_game_advisor_payload(
            data=self.data,
            turn=self.game_map.turn,
            player_units=unit_ids,
            player_army=aggregate_army(unit_ids, self.data["units"]),
            player_strategy_id=strategy_id,
            troop_status_name=troop_status,
            terrain_name=terrain_name,
            weather_name=self.weather,
        )
        breakdown = self._legion_battle_strength(
            PLAYER, legion, terrain_name,
            defending=False, cell=cell, enemy_strength=0.0, movement_key=None,
        )
        payload.update({
            "scope": "legion",
            "legion_id": legion_id,
            "legion_name": legion.get("name", legion_id),
            "legion_type": legion.get("legion_type", LEGION_TYPE_ARMY),
            "legion_type_label": LEGION_TYPE_LABELS.get(
                legion.get("legion_type", LEGION_TYPE_ARMY), ""
            ),
            "pos": list(pos) if len(pos) == 2 else None,
            "units_count": len(unit_ids),
            "current_strategy_id": strategy_id,
            "current_strategy_name": self.strategies_map.get(strategy_id, {}).get(
                "name", strategy_id
            ),
            "current_strength": int(round(breakdown["strength"])),
            "current_strategy_factor": round(breakdown["strategy_factor"], 3),
            "troop_status_name": troop_status,
            "troop_condition": tc.describe(condition),
            "empty": False,
        })
        return payload

    def _available_mine_slots(self, entity: Occupation) -> int:
        """Slot miniera disponibili in base alle celle controllate."""
        return available_mine_slots(
            controlled_cells=self.game_map.count_occupied(entity),
            existing_mines=self.game_map.count_mines(entity),
        )

    def _ability_state(self, entity: Occupation, ability_id: str) -> Optional[Any]:
        return self.ability_states.get(entity, {}).get(ability_id)

    def _is_ability_unlocked(self, entity: Occupation, ability_id: str) -> bool:
        ability = self._ability_state(entity, ability_id)
        if ability is None:
            return False
        return ability.is_unlocked(self.game_map.turn)

    def _start_ability_research(self, entity: Occupation, ability_id: str) -> Optional[str]:
        """Avvia una ricerca pagandola. Ritorna la riga di log, o None se non si può.

        Il controllo di disponibilità (una ricerca alla volta, prerequisiti,
        turno minimo, esclusività) sta in `abilities.availability`: qui si
        aggiunge solo il conto in grux, che è l'unica cosa che il catalogo non
        può sapere da solo.
        """
        states = self.ability_states.get(entity, {})
        ability = states.get(ability_id)
        if ability is None:
            return None

        can_start, _ = ab.availability(ability_id, states, self.game_map.turn)
        if not can_start:
            return None

        cost = int(getattr(ability, "grux_cost", 0))
        if self.grux_balance[entity] < cost:
            return None

        self.grux_balance[entity] -= cost
        ability.start(self.game_map.turn)
        side = entity.value.upper()
        price_note = f", {cost} grux" if cost > 0 else ""
        log_entry = (
            f"[Turno {self.game_map.turn}] ⭐ {side} avvia ricerca Abilità: {ability.name} "
            f"({ability.turns_required} turni{price_note})"
        )
        self.battle_log.append(log_entry)
        return log_entry

    def _ai_research_savings(self) -> int:
        """Grux che l'IA tiene da parte per la prossima ricerca in programma.

        Zero se sta già ricercando o se non c'è niente di avviabile: il
        risparmio serve solo quando c'è un obiettivo concreto da raggiungere.

        E zero finché l'esercito non arriva a due reparti pieni: prima vengono
        le truppe. Misurato risparmiando fin dal primo turno, l'IA a incubo
        restava a una legione sola per mezza partita (media 1.5 invece di 2.1) e
        arrivava al castello 60 turni più tardi, pur finendo con il triplo delle
        truppe. Il tempo perso all'inizio non si recupera comprando dopo.

        La soglia esatta è un compromesso misurato su 5 partite per difficoltà:
        a 4 unità l'IA a incubo sblocca 5.2 abilità ma impiega 155 turni, a 18
        ne sblocca 3 in 122 turni. A 12 ne sblocca 4 in 125.
        """
        states = self.ability_states.get(AI, {})
        turn = self.game_map.turn
        if ab.researching_id(states, turn) is not None:
            return 0

        if len(self.ai_units) < AI_RESEARCH_MIN_ARMY:
            return 0

        plan = ab.AI_RESEARCH_PLANS.get(self.ai_difficulty.lower()) or ab.AI_RESEARCH_PLANS["normal"]
        for ability_id in plan:
            state = states.get(ability_id)
            if state is None:
                continue
            can_start, _ = ab.availability(ability_id, states, turn)
            if can_start:
                return int(state.grux_cost) + ab.AI_RESEARCH_RESERVE
        return 0

    def _run_ai_research(self) -> Optional[str]:
        """L'IA sceglie e avvia la prossima ricerca del suo piano.

        Stesse regole del giocatore: una alla volta, pagata, con prerequisiti
        e turno minimo. Cambia solo l'ordine delle priorità, che dipende dalla
        difficoltà ed è scritto in `abilities.AI_RESEARCH_PLANS`.
        """
        states = self.ability_states.get(AI, {})
        ability_id = ab.ai_next_research(
            self.ai_difficulty, states, self.game_map.turn, self.grux_balance[AI]
        )
        if ability_id is None:
            return None
        return self._start_ability_research(AI, ability_id)

    # ── Effetti delle abilità ──────────────────────────────────────
    # Punto unico di lettura: il resto del motore chiede "quanto vale" o
    # "posso farlo", e non sa quali abilità esistano.

    def _unlocked_abilities(self, entity: Occupation) -> Tuple[str, ...]:
        """Abilità attive di un'entità in questo momento.

        Volutamente senza cache: il risultato può cambiare a metà turno (il
        pannello di debug sblocca tutto retrodatando la ricerca) e una lista
        di undici id si ricalcola in niente. Chi conta unità in serie chiede
        una volta questa tupla e poi la riusa.
        """
        return ab.unlocked_ids(self.ability_states.get(entity, {}), self.game_map.turn)

    def _ability_flag(self, entity: Occupation, flag: str) -> bool:
        return ab.has_flag(self._unlocked_abilities(entity), flag)

    def _ability_unit_factor(self, entity: Occupation, unit_id: str, context: str) -> float:
        return ab.unit_factor(self._unlocked_abilities(entity), unit_id, context)

    def _ability_economy_factor(self, entity: Occupation, key: str) -> float:
        return ab.economy_factor(self._unlocked_abilities(entity), key)

    def _ability_value_of(self, entity: Occupation, context: str):
        """Funzione `unit_id -> valore` con dentro i bonus di stile del contesto.

        Serve dove il valore delle unità viene sommato da codice che non deve
        sapere niente di abilità (il layer di bilanciamento, per esempio).
        Quando non c'è nessun bonus in gioco restituisce la funzione originale,
        così il caso normale non paga niente.
        """
        unlocked = self._unlocked_abilities(entity)
        if not ab.has_unit_effects(unlocked, context):
            return self._unit_battle_value
        return lambda unit_id: self._unit_battle_value(unit_id) * ab.unit_factor(
            unlocked, unit_id, context
        )

    def research_player_ability(self, ability_id: str = DOMAIN_ENGINEERING_ID) -> Dict[str, Any]:
        """Avvia la ricerca di una abilità lato player."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        states = self.ability_states.get(PLAYER, {})
        ability = states.get(ability_id)
        if ability is None:
            raise ValueError("Abilità sconosciuta.")

        can_start, reason = ab.availability(ability_id, states, self.game_map.turn)
        if not can_start:
            raise ValueError(reason)

        cost = int(getattr(ability, "grux_cost", 0))
        if self.grux_balance[PLAYER] < cost:
            raise ValueError(
                f"Grux insufficienti per la ricerca: servono {cost}, "
                f"disponibili {self.grux_balance[PLAYER]}"
            )

        log_entry = self._start_ability_research(PLAYER, ability_id)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    # ── Mercato Nero ───────────────────────────────────────────────

    def _black_market_open(self, entity: Occupation) -> bool:
        return self._ability_flag(entity, ab.FLAG_BLACK_MARKET)

    def _tick_black_market(self) -> List[str]:
        """Aggiorna i banchi di chi ha l'abilità. Chiusi non fanno nulla."""
        logs: List[str] = []
        for entity in (PLAYER, AI):
            if entity == AI and self.debug_ai_kill_switch:
                continue
            if not self._black_market_open(entity):
                continue
            # Il listino di riferimento è quello che questa entità pagherebbe
            # davvero, non il prezzo base: con Industria Bellica sbloccata uno
            # sconto del 20% sul listino pieno poteva essere un affare PEGGIORE
            # del reclutamento normale, e il banco l'avrebbe comunque scritto
            # come risparmio.
            reference_prices = {
                unit_id: self._recruit_cost(entity, unit_id) for unit_id in self.unit_costs
            }
            line = self.black_market[entity].tick(
                self.game_map.turn, reference_prices, self.units_map, self.black_market_rng
            )
            # Il cambio banco dell'IA non è affar suo: resta fuori dal registro.
            if line and entity == PLAYER:
                logs.append(line)
        return logs

    def _absorb_market_block(self, entity: Occupation, unit_id: str, quantity: int) -> None:
        """Fa entrare in riserva un blocco comprato al banco.

        Stessa strada di una recluta normale — riserva, vettore esercito,
        diluizione della stanchezza — solo moltiplicata per la quantità e
        senza toccare `last_recruit_turn`: il mercato nero non conosce
        cooldown, ed è il motivo per cui esiste.
        """
        tc.dilute_pool(self.reserve_condition[entity], len(self._entity_units(entity)))

        if entity == PLAYER:
            self.player_units.extend([unit_id] * quantity)
            self.player_army = aggregate_army(self.player_units, self.data["units"])
            self.player_modified, _ = apply_modifiers(
                army_vector=self.player_army,
                terrain_name=self.player_home_terrain,
                weather_name=self.weather,
                troop_status_name=self.player_troop_status,
                modifiers_data=self.data,
            )
        else:
            self.ai_units.extend([unit_id] * quantity)
            self.ai_army = aggregate_army(self.ai_units, self.data["units"])
            self.ai_modified, _ = apply_modifiers(
                army_vector=self.ai_army,
                terrain_name=self.ai_home_terrain,
                weather_name=self.weather,
                troop_status_name=self.ai_troop_status,
                modifiers_data=self.data,
            )

    def buy_black_market_offer(self, offer_id: str) -> Dict[str, Any]:
        """Compra un blocco al banco per il giocatore."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if not self._black_market_open(PLAYER):
            raise ValueError("Il Mercato Nero non è ancora sbloccato.")

        market = self.black_market[PLAYER]
        offer = market.get_offer(offer_id)
        if offer is None:
            raise ValueError("Offerta non più al banco.")
        if self.grux_balance[PLAYER] < offer.total_price:
            raise ValueError(
                f"Grux insufficienti: servono {offer.total_price}, "
                f"disponibili {self.grux_balance[PLAYER]}"
            )

        offer = market.take(offer_id, self.game_map.turn)
        self.grux_balance[PLAYER] -= offer.total_price
        self.player_army_cost += offer.total_price
        self._absorb_market_block(PLAYER, offer.unit_id, offer.quantity)

        saving = max(0, offer.list_total - offer.total_price)
        log_entry = (
            f"[Turno {self.game_map.turn}] 🕯 PLAYER compra al Mercato Nero: "
            f"{offer.unit_name} ×{offer.quantity} per {offer.total_price} grux "
            f"(-{offer.discount_pct}%, {saving} risparmiati)"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def _run_ai_black_market(self) -> List[str]:
        """L'IA passa al banco: prende l'affare che le fa risparmiare di più.

        Tiene da parte la stessa riserva che tiene per le ricerche, se no
        svuoterebbe la cassa in offerte e smetterebbe di fortificare.
        """
        if not self._black_market_open(AI):
            return []

        market = self.black_market[AI]
        # Non tocca i grux già promessi alla ricerca: senza questo l'IA metteva
        # da parte per l'abilità e poi si comprava le truppe con quei soldi,
        # rimandando la ricerca all'infinito.
        held_back = max(ab.AI_RESEARCH_RESERVE, self._ai_research_savings())
        budget = self.grux_balance[AI] - held_back
        if budget <= 0:
            return []

        offer = market.best_affordable(self.game_map.turn, budget)
        if offer is None:
            return []

        offer = market.take(offer.offer_id, self.game_map.turn)
        self.grux_balance[AI] -= offer.total_price
        self.ai_army_cost += offer.total_price
        self._absorb_market_block(AI, offer.unit_id, offer.quantity)
        self._sync_ai_legion_units()

        return [
            f"[Turno {self.game_map.turn}] 🕯 IA compra al Mercato Nero: "
            f"{offer.unit_name} ×{offer.quantity} ({offer.total_price} grux)"
        ]

    def _get_player_legion_or_raise(self, legion_id: str) -> Dict[str, Any]:
        legion = self.player_legions.get(legion_id)
        if legion is None:
            raise ValueError(f"Legione non trovata: {legion_id}")
        return legion

    def _require_legion_type(
        self,
        legion: Dict[str, Any],
        required_type: str,
        action_label: str,
        entity: Occupation = PLAYER,
    ) -> None:
        """La legione deve essere del tipo richiesto per eseguire questa costruzione."""
        legion_type = legion.get("legion_type", LEGION_TYPE_ARMY)
        if legion_type == required_type:
            return

        # [ABILITY-EFFECTS] Costruzione Caotica: i ruoli non contano più,
        # qualsiasi legione può costruire qualsiasi cosa.
        if self._ability_flag(entity, ab.FLAG_BUILD_ANY_LEGION):
            return

        legion_name = legion.get("name", "legione")
        raise ValueError(
            f"Non puoi costruire {action_label}: la legione '{legion_name}' è di tipo "
            f"'{LEGION_TYPE_LABELS.get(legion_type, legion_type)}'. Serve una legione "
            f"'{LEGION_TYPE_LABELS[required_type]}'."
        )

    def _find_first_legion_of_type(self, entity: Occupation, legion_type: str) -> Optional[str]:
        """Prima legione dell'entità con il tipo richiesto, se presente."""
        source = self.player_legions if entity == PLAYER else self.ai_legions
        for legion_id, legion in source.items():
            if legion.get("legion_type", LEGION_TYPE_ARMY) == legion_type:
                return legion_id
        return None

    def _find_first_legion_with_spare_units(self, entity: Occupation) -> Optional[str]:
        """Prima legione dell'entità con almeno 2 truppe (può lasciarne una a presidio)."""
        source = self.player_legions if entity == PLAYER else self.ai_legions
        for legion_id, legion in source.items():
            if len(legion.get("units", [])) >= 2:
                return legion_id
        return None

    def _resolve_build_cell(
        self,
        legion: Dict[str, Any],
        target: Optional[Tuple[int, int]],
        action_label: str,
    ) -> Tuple[int, int]:
        """Cella su cui costruire: quella della legione, o una a distanza.

        [ABILITY-EFFECTS] Costruire lontano dalla legione è il senso di
        Costruzione Territoriale: senza l'abilità si lavora solo sotto i propri
        piedi, con l'abilità su qualunque cella del dominio.
        """
        own_pos = tuple(legion.get("pos", ()))
        if target is None:
            return own_pos

        row, col = int(target[0]), int(target[1])
        if (row, col) == own_pos:
            return own_pos

        if not self._ability_flag(PLAYER, ab.FLAG_BUILD_ANYWHERE):
            raise ValueError(
                f"Puoi costruire {action_label} solo dove si trova la legione "
                f"'{legion.get('name', 'legione')}'. Serve l'abilità "
                f"'{ab.ABILITIES[ab.DOMAIN_ENGINEERING_ID].name}' per lavorare a distanza."
            )

        cell = self.game_map.get_cell(row, col)
        if cell is None:
            raise ValueError("Cella fuori dalla mappa.")
        if cell.occupation != PLAYER:
            raise ValueError(
                f"Puoi costruire {action_label} solo su celle che controlli: "
                f"({row},{col}) non è tua."
            )
        return (row, col)

    def place_mine(self, legion_id: str, target: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
        """Piazza una miniera con una legione Mineraria.

        Sulla cella della legione, oppure — con Costruzione Territoriale — su
        una qualsiasi cella controllata.
        """
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        legion = self._get_player_legion_or_raise(legion_id)
        self._require_legion_type(legion, LEGION_TYPE_MINING, "una Miniera")
        if self._available_mine_slots(PLAYER) <= 0:
            raise ValueError(
                f"Non hai slot miniera disponibili. Serve più territorio controllato "
                f"(1 slot ogni {MINE_TILES_PER_SLOT} celle)."
            )

        row, col = self._resolve_build_cell(legion, target, "una miniera")
        cell = self.game_map.place_mine(PLAYER, row, col)
        remote = "" if (row, col) == tuple(legion.get("pos", ())) else " (cantiere a distanza)"
        log_entry = (
            f"[Turno {self.game_map.turn}] ⛏ PLAYER costruisce una miniera su ({row},{col}) "
            f"con la legione '{legion['name']}'{remote}"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "player_grux": self.grux_balance[PLAYER],
        }

    def _garrison_capacity(self, cell: Optional[Any]) -> int:
        """Quanti presidi regge una cella.

        Il castello ha il suo tetto fisso; una cella normale ne ospita uno,
        più uno per ogni livello di fortificazione, fino al tetto assoluto.
        """
        if cell is None:
            return 0
        if cell.is_castle:
            return CASTLE_MAX_GARRISON_UNITS
        capacity = (
            CELL_GARRISON_BASE_CAPACITY
            + int(cell.fortification_level) * CELL_GARRISON_PER_FORT_LEVEL
        )
        return min(capacity, CELL_MAX_GARRISON_UNITS)

    def _garrison_full_error(self, cell: Optional[Any]) -> Optional[str]:
        """Messaggio di rifiuto se la cella non regge un altro presidio, altrimenti None."""
        if cell is None:
            return None
        capacity = self._garrison_capacity(cell)
        if len(cell.garrison_unit_ids) < capacity:
            return None

        if cell.is_castle:
            return (
                f"Il castello ha già il massimo di presidi ({capacity}): "
                f"oltre questo limite sarebbe imprendibile."
            )
        if capacity < CELL_MAX_GARRISON_UNITS:
            return (
                f"Questa cella regge {capacity} presidi al suo livello di fortificazione: "
                f"costruisci una fortificazione per ospitarne un altro."
            )
        return f"Questa cella ha già il massimo di presidi ({capacity})."

    def _detach_unit_from_legion_to_garrison(
        self,
        legion: Dict[str, Any],
        cell_pos: Tuple[int, int],
        unit_id: Optional[str],
    ) -> Dict[str, Any]:
        """Distacca una truppa dalla legione stessa (non dalla riserva) per presidiare la cella."""
        units = legion.get("units", [])
        if len(units) < 2:
            raise ValueError(
                "Non puoi lasciare un presidio: la legione deve avere almeno 2 truppe "
                "(ne resta sempre almeno 1 attiva)."
            )

        selected_unit_id = unit_id
        if selected_unit_id is None:
            sorted_units = sorted(units, key=lambda uid: self._unit_battle_value(uid))
            selected_unit_id = sorted_units[0]
        if selected_unit_id not in units:
            raise ValueError("La truppa selezionata non è presente in questa legione.")

        cell = self.game_map.get_cell(*cell_pos)
        if cell is None:
            raise ValueError("Cella presidio non valida.")
        full = self._garrison_full_error(cell)
        if full:
            raise ValueError(full)

        units.remove(selected_unit_id)
        cell.garrison_unit_ids.append(selected_unit_id)
        cell.garrison_strength = max(cell.garrison_strength, len(cell.garrison_unit_ids))

        unit_name = self.units_map.get(selected_unit_id, {}).get("name", selected_unit_id)
        return {"unit_id": selected_unit_id, "unit_name": unit_name}

    def place_garrison(self, legion_id: str, unit_id: Optional[str] = None) -> Dict[str, Any]:
        """Stacca una truppa dalla legione (che deve averne almeno 2) per presidiare la cella dove si trova."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        legion = self._get_player_legion_or_raise(legion_id)
        pos = tuple(legion["pos"])
        cell = self.game_map.get_cell(*pos)
        if cell is None or cell.occupation != PLAYER:
            raise ValueError("La cella della legione non è controllata dal PLAYER.")

        detach_result = self._detach_unit_from_legion_to_garrison(legion, pos, unit_id)

        row, col = pos
        log_entry = (
            f"[Turno {self.game_map.turn}] 🛡 PLAYER piazza un presidio su ({row},{col}) "
            f"con la legione '{legion['name']}' — Distaccata: {detach_result['unit_name']}"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
        }

    def _fortification_cost(self, current_level: int, entity: Occupation = PLAYER) -> int:
        """Costo fortificazione con crescita forte sullo stack della stessa cella."""
        cost = self.base_fortification_cost * (1 + (current_level * 1.7))
        # [ABILITY-EFFECTS] Trinceramento Rapido: palizzate prefabbricate.
        cost *= self._ability_economy_factor(entity, ab.ECO_FORTIFICATION_COST)
        return max(5, int(round(cost)))

    def place_fortification(
        self, legion_id: str, target: Optional[Tuple[int, int]] = None
    ) -> Dict[str, Any]:
        """Piazza una fortificazione con una legione Costruzione, con costo crescente.

        Sulla cella della legione, oppure — con Costruzione Territoriale — su
        una qualsiasi cella controllata.
        """
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")

        legion = self._get_player_legion_or_raise(legion_id)
        self._require_legion_type(legion, LEGION_TYPE_CONSTRUCTION, "una Fortificazione")

        row, col = self._resolve_build_cell(legion, target, "una fortificazione")
        cell = self.game_map.get_cell(row, col)
        if cell is None:
            raise ValueError("Cella fuori dalla mappa.")
        if cell.occupation != PLAYER:
            raise ValueError("Puoi fortificare solo celle controllate dal PLAYER.")

        # Il castello è fortificabile, ma con un tetto suo: ogni livello riduce
        # i danni da assedio, quindi senza limite diventerebbe imprendibile.
        is_own_castle = bool(cell.is_castle)
        max_level = CASTLE_MAX_FORTIFICATION_LEVEL if is_own_castle else None
        if is_own_castle and cell.fortification_level >= CASTLE_MAX_FORTIFICATION_LEVEL:
            raise ValueError(
                f"Il castello è già fortificato al massimo "
                f"(livello {CASTLE_MAX_FORTIFICATION_LEVEL}): "
                f"riduce i danni da assedio del "
                f"{int(CASTLE_MAX_FORTIFICATION_LEVEL * CASTLE_FORT_DAMAGE_REDUCTION_PER_LEVEL * 100)}%."
            )

        current_level = cell.fortification_level
        cost = self._fortification_cost(current_level)
        if self.grux_balance[PLAYER] < cost:
            raise ValueError(f"Grux insufficienti per fortificare: servono {cost}, disponibili {self.grux_balance[PLAYER]}")

        self.grux_balance[PLAYER] -= cost
        cell = self.game_map.place_fortification(PLAYER, row, col, max_level=max_level)
        next_cost = self._fortification_cost(cell.fortification_level)

        if is_own_castle:
            riduzione = int(cell.fortification_level * CASTLE_FORT_DAMAGE_REDUCTION_PER_LEVEL * 100)
            log_entry = (
                f"[Turno {self.game_map.turn}] 🏰 PLAYER fortifica il CASTELLO con la legione "
                f"'{legion['name']}' → livello {cell.fortification_level}/"
                f"{CASTLE_MAX_FORTIFICATION_LEVEL} (costo {cost} grux, "
                f"-{riduzione}% danni da assedio)"
            )
        else:
            remote = "" if (row, col) == tuple(legion.get("pos", ())) else " (cantiere a distanza)"
            log_entry = (
                f"[Turno {self.game_map.turn}] 🧱 PLAYER fortifica ({row},{col}) con la legione "
                f"'{legion['name']}' → livello {cell.fortification_level} (costo {cost} grux){remote}"
            )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "cell": cell.to_dict(),
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "player_grux": self.grux_balance[PLAYER],
            "next_fortification_cost": next_cost,
        }

    def _place_best_ai_mine(self) -> Optional[str]:
        """L'IA piazza una miniera sulla miglior cella controllata disponibile."""
        ai_can_build_anywhere = self._is_ability_unlocked(AI, DOMAIN_ENGINEERING_ID)
        ai_build_positions = set(self._active_legion_positions(AI))

        best_cell = None
        best_score = float("-inf")
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != AI or cell.is_castle or cell.is_mine or cell.terrain == "Fiume":
                    continue
                if not ai_can_build_anywhere and (cell.row, cell.col) not in ai_build_positions:
                    continue
                score = 2.0 if cell.is_strategic else 0.0
                if cell.terrain in {"Pianura", "Montagna"}:
                    score += 1.0
                if score > best_score:
                    best_score = score
                    best_cell = cell

        if best_cell is None:
            return None

        self.game_map.place_mine(AI, best_cell.row, best_cell.col)
        return f"[Turno {self.game_map.turn}] ⛏ IA costruisce una miniera su ({best_cell.row},{best_cell.col})"

    def _ai_castle_ring_cells(self) -> List[Any]:
        """Celle immediatamente adiacenti al castello IA e da essa controllate."""
        castle_pos = self.game_map.castle_positions.get(AI)
        if castle_pos is None:
            return []

        ring: List[Any] = []
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            cell = self.game_map.get_cell(castle_pos[0] + dr, castle_pos[1] + dc)
            if cell is None or cell.is_castle:
                continue
            if cell.occupation != AI:
                continue
            ring.append(cell)
        return ring

    def _garrison_ai_castle(self) -> List[str]:
        """L'IA presidia il proprio castello, come può fare il giocatore.

        Le legioni non difendono più il castello: senza questo, solo il player
        avrebbe potuto guarnirlo e il bilanciamento penderebbe da una parte.
        Quante truppe schierare è una manopola per difficoltà
        (`castle_garrison_target`): i profili che non la espongono non presidiano.
        """
        target = int(getattr(self.ai_policy, "castle_garrison_target", 0) or 0)
        if target <= 0:
            return []

        castle_pos = self.game_map.castle_positions.get(AI)
        cell = self.game_map.get_cell(*castle_pos) if castle_pos else None
        if cell is None:
            return []

        target = min(target, self._garrison_capacity(cell))
        if len(cell.garrison_unit_ids) >= target:
            return []

        affordable = [
            unit for unit in self.data["units"]
            if self.unit_costs[unit["id"]] <= self.grux_balance[AI]
        ]
        if not affordable:
            return []

        best_unit = max(
            affordable,
            key=lambda unit: self._garrison_unit_defense_value(unit["id"], cell.terrain),
        )
        cost = self.unit_costs[best_unit["id"]]
        self.grux_balance[AI] -= cost
        cell.garrison_unit_ids.append(best_unit["id"])
        cell.garrison_strength = max(cell.garrison_strength, len(cell.garrison_unit_ids))
        return [
            f"[Turno {self.game_map.turn}] 🛡 IA arruola {best_unit['name']} a presidio "
            f"del CASTELLO — {cost} grux ({len(cell.garrison_unit_ids)}/{target})"
        ]

    def _reinforce_ai_castle_ring(self) -> List[str]:
        """Trincera l'IA sulle caselle adiacenti al proprio castello.

        Fortifica l'anello e vi compra truppe di presidio con il budget extra:
        sono unità acquistate apposta, quindi NON tolgono forza alla legione
        in campo (`ai_units` resta intatto).
        """
        plan_getter = getattr(self.ai_policy, "castle_ring_plan", None)
        if not callable(plan_getter):
            return []

        plan = plan_getter()
        # Il piano dell'anello non può sfondare il tetto generale delle celle.
        max_fort = min(int(plan.get("max_fort_level", 0)), GameMap.MAX_FORTIFICATION_LEVEL)
        target_garrison = int(plan.get("target_garrison", 0))
        reserve = int(plan.get("reserve_grux", 0))

        logs: List[str] = []
        ring = self._ai_castle_ring_cells()
        if not ring:
            return logs

        # 1. Fortificazioni sull'anello, dalla cella più scoperta.
        for cell in sorted(ring, key=lambda c: c.fortification_level):
            if cell.fortification_level >= max_fort:
                continue
            cost = self._fortification_cost(int(cell.fortification_level), AI)
            if self.grux_balance[AI] < cost + reserve:
                break
            self.grux_balance[AI] -= cost
            placed = self.game_map.place_fortification(AI, cell.row, cell.col)
            logs.append(
                f"[Turno {self.game_map.turn}] 🧱 IA blinda l'anello del castello "
                f"({placed.row},{placed.col}) → livello {placed.fortification_level} "
                f"(costo {cost} grux)"
            )
            break   # una costruzione per turno, non svuota le casse in un colpo

        # 2. Presidi comprati apposta per l'anello, entro la capienza della cella.
        for cell in sorted(ring, key=lambda c: len(c.garrison_unit_ids)):
            capacity = min(target_garrison, self._garrison_capacity(cell))
            if len(cell.garrison_unit_ids) >= capacity:
                continue

            affordable = [
                unit for unit in self.data["units"]
                if self.unit_costs[unit["id"]] + reserve <= self.grux_balance[AI]
            ]
            if not affordable:
                break

            best_unit = max(
                affordable,
                key=lambda unit: self._garrison_unit_defense_value(unit["id"], cell.terrain),
            )
            cost = self.unit_costs[best_unit["id"]]
            self.grux_balance[AI] -= cost
            cell.garrison_unit_ids.append(best_unit["id"])
            cell.garrison_strength = max(cell.garrison_strength, len(cell.garrison_unit_ids))
            logs.append(
                f"[Turno {self.game_map.turn}] 🛡 IA arruola {best_unit['name']} a presidio "
                f"di ({cell.row},{cell.col}) — {cost} grux, anello del castello"
            )
            break   # un presidio per turno

        return logs

    def _place_best_ai_fortification(self) -> Optional[str]:
        """L'IA fortifica la miglior cella controllata disponibile, rispettando costo e vincoli abilità."""
        ai_can_build_anywhere = self._is_ability_unlocked(AI, DOMAIN_ENGINEERING_ID)
        ai_build_positions = set(self._active_legion_positions(AI))

        player_anchor: Optional[Tuple[int, int]] = None
        if self.player_legions:
            first_player_legion = next(iter(self.player_legions.values()))
            pos = tuple(first_player_legion.get("pos", ()))
            if len(pos) == 2:
                player_anchor = (int(pos[0]), int(pos[1]))

        best: Optional[Tuple[float, Any, int]] = None
        for row in self.game_map.grid:
            for cell in row:
                if cell.occupation != AI:
                    continue
                # Il castello ora è fortificabile e riduce i danni da assedio:
                # l'IA deve poterlo fare come il player, o l'asimmetria falserebbe
                # tutto il bilanciamento delle difficoltà. Valgono per lei gli
                # stessi tetti: una cella al massimo non è più un bersaglio.
                cell_cap = (
                    CASTLE_MAX_FORTIFICATION_LEVEL if cell.is_castle
                    else GameMap.MAX_FORTIFICATION_LEVEL
                )
                if cell.fortification_level >= cell_cap:
                    continue
                if not ai_can_build_anywhere and (cell.row, cell.col) not in ai_build_positions:
                    continue

                current_level = int(cell.fortification_level)
                cost = self._fortification_cost(current_level, AI)
                if self.grux_balance[AI] < cost:
                    continue

                score = 0.0
                if cell.is_castle:
                    # Difendere il proprio castello è la priorità: è la condizione
                    # di sconfitta, e i livelli disponibili sono solo 4.
                    score += 4.0
                if cell.is_strategic:
                    score += 2.4
                if cell.is_mine:
                    score += 1.7
                score += max(0.0, 1.2 - (current_level * 0.45))

                if player_anchor is not None:
                    score += max(0.0, 1.4 - (self._order_distance((cell.row, cell.col), player_anchor) * 0.18))

                if best is None or score > best[0]:
                    best = (score, cell, cost)

        if best is None:
            return None

        _, cell, cost = best
        self.grux_balance[AI] -= cost
        max_level = CASTLE_MAX_FORTIFICATION_LEVEL if cell.is_castle else None
        placed = self.game_map.place_fortification(AI, cell.row, cell.col, max_level=max_level)
        if placed.is_castle:
            riduzione = int(placed.fortification_level * CASTLE_FORT_DAMAGE_REDUCTION_PER_LEVEL * 100)
            return (
                f"[Turno {self.game_map.turn}] 🏰 IA fortifica il CASTELLO → livello "
                f"{placed.fortification_level}/{CASTLE_MAX_FORTIFICATION_LEVEL} "
                f"(costo {cost} grux, -{riduzione}% danni da assedio)"
            )
        return (
            f"[Turno {self.game_map.turn}] 🧱 IA fortifica ({placed.row},{placed.col}) "
            f"→ livello {placed.fortification_level} (costo {cost} grux)"
        )

    def recruit_player_unit(self, unit_id: str) -> Dict[str, Any]:
        """Compra una unità per il giocatore e aggiorna l'esercito."""
        log_entry = self._recruit_unit(PLAYER, unit_id, auto=False)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def start_player_auto_recruit(self, unit_id: str, turns: int) -> Dict[str, Any]:
        """Avvia il piano di autoreclutamento del player per un numero di turni."""
        if self.state != SessionState.ACTIVE:
            raise ValueError("La partita è terminata.")
        if unit_id not in self.unit_costs:
            raise ValueError(f"Unità sconosciuta: {unit_id}")

        turns_value = int(turns)
        if turns_value <= 0:
            raise ValueError("I turni di autoreclutamento devono essere almeno 1.")
        if turns_value > 40:
            raise ValueError("I turni di autoreclutamento non possono superare 40.")

        unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
        self.player_auto_recruit.update(
            {
                "enabled": True,
                "unit_id": unit_id,
                "unit_name": unit_name,
                "turns_total": turns_value,
                "turns_remaining": turns_value,
                "attempted_turns": 0,
                "successful_recruits": 0,
                "last_result": "scheduled",
            }
        )

        log_entry = (
            f"[Turno {self.game_map.turn}] 🤖 PLAYER avvia autoreclutamento: "
            f"{unit_name} per {turns_value} turni"
        )
        self.battle_log.append(log_entry)
        return {
            "ok": True,
            "message": log_entry,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def stop_player_auto_recruit(self, reason: str = "manual") -> Dict[str, Any]:
        """Ferma il piano di autoreclutamento del player."""
        was_enabled = bool(self.player_auto_recruit.get("enabled"))
        unit_name = self.player_auto_recruit.get("unit_name") or "unità"

        self.player_auto_recruit["enabled"] = False
        self.player_auto_recruit["turns_remaining"] = 0
        self.player_auto_recruit["last_result"] = "stopped"

        if was_enabled:
            reason_label = "manuale" if reason == "manual" else reason
            log_entry = (
                f"[Turno {self.game_map.turn}] 🤖 PLAYER ferma autoreclutamento "
                f"({unit_name}) - motivo: {reason_label}"
            )
            self.battle_log.append(log_entry)
            message = log_entry
        else:
            message = "Autoreclutamento non attivo."

        return {
            "ok": True,
            "message": message,
            "state": self.state.value,
            "map": self.game_map.to_dict(),
            "session": self.to_dict(),
        }

    def _run_player_auto_recruit(self) -> List[str]:
        """Esegue una iterazione del piano di autoreclutamento player al termine del round."""
        logs: List[str] = []
        if self.state != SessionState.ACTIVE:
            return logs

        if not self.player_auto_recruit.get("enabled"):
            return logs

        unit_id = self.player_auto_recruit.get("unit_id")
        unit_name = self.player_auto_recruit.get("unit_name") or (unit_id or "unità")
        turns_remaining = int(self.player_auto_recruit.get("turns_remaining") or 0)

        if not unit_id or unit_id not in self.unit_costs:
            self.player_auto_recruit["enabled"] = False
            self.player_auto_recruit["last_result"] = "invalid_unit"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento interrotto: unità non valida"
            )
            return logs

        if turns_remaining <= 0:
            self.player_auto_recruit["enabled"] = False
            self.player_auto_recruit["last_result"] = "completed"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento completato ({unit_name})"
            )
            return logs

        self.player_auto_recruit["attempted_turns"] = int(self.player_auto_recruit.get("attempted_turns") or 0) + 1
        self.player_auto_recruit["turns_remaining"] = turns_remaining - 1

        # Il motivo va calcolato PRIMA del tentativo: `_recruit_unit` in modalità
        # automatica restituisce None sia per cooldown sia per grux, e il log
        # finiva per dire "cooldown o grux insufficienti" anche con le casse piene.
        block_reason = self._recruit_block_reason(PLAYER, unit_id)
        recruit_log = None if block_reason else self._recruit_unit(PLAYER, unit_id, auto=True)

        if recruit_log:
            self.player_auto_recruit["successful_recruits"] = int(self.player_auto_recruit.get("successful_recruits") or 0) + 1
            self.player_auto_recruit["last_result"] = "success"
            self.player_auto_recruit["last_reason"] = None
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento riuscito: {unit_name}"
            )
        else:
            self.player_auto_recruit["last_result"] = "skipped"
            self.player_auto_recruit["last_reason"] = block_reason or "motivo sconosciuto"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Autoreclutamento in pausa ({unit_name}): "
                f"{block_reason or 'motivo sconosciuto'}"
            )

        if int(self.player_auto_recruit.get("turns_remaining") or 0) <= 0:
            self.player_auto_recruit["enabled"] = False
            self.player_auto_recruit["last_result"] = "completed"
            logs.append(
                f"[Turno {self.game_map.turn}] 🤖 Piano autoreclutamento terminato ({unit_name})"
            )

        return logs

    def _recruit_block_reason(self, entity: Occupation, unit_id: str) -> Optional[str]:
        """Perché il reclutamento non è possibile adesso, o None se lo è.

        Serve all'autoreclutamento per dire nel log cosa lo sta fermando davvero:
        il tentativo automatico fallisce in silenzio e non distingue i due casi.
        """
        if unit_id not in self.unit_costs:
            return f"unità sconosciuta ({unit_id})"

        if not self._can_recruit_now(entity):
            last_turn = self.last_recruit_turn.get(entity)
            turns_passed = 0 if last_turn is None else (self.game_map.turn - last_turn)
            remaining = max(0, self._recruit_cooldown_for(entity) - turns_passed)
            return f"reclutamento in cooldown, ancora {remaining} turno/i"

        cost = self._recruit_cost(entity, unit_id)
        balance = self.grux_balance.get(entity, 0)
        if balance < cost:
            return f"grux insufficienti: servono {cost}, disponibili {balance}"

        return None

    def _recruit_unit(self, entity: Occupation, unit_id: str, auto: bool) -> Optional[str]:
        """Recluta una unità, scala il costo e ricalcola il vettore esercito."""
        if self.state != SessionState.ACTIVE:
            if auto:
                return None
            raise ValueError("La partita è terminata.")

        if unit_id not in self.unit_costs:
            raise ValueError(f"Unità sconosciuta: {unit_id}")

        if not self._can_recruit_now(entity):
            last_turn = self.last_recruit_turn.get(entity)
            turns_passed = 0 if last_turn is None else (self.game_map.turn - last_turn)
            remaining = max(0, self._recruit_cooldown_for(entity) - turns_passed)
            if auto:
                return None
            raise ValueError(
                f"Reclutamento in cooldown: attendi ancora {remaining} turno/i prima di reclutare di nuovo."
            )

        cost = self._recruit_cost(entity, unit_id)
        if self.grux_balance[entity] < cost:
            if auto:
                return None
            raise ValueError(f"Grux insufficienti: servono {cost}, disponibili {self.grux_balance[entity]}")

        home_terrain = self.player_home_terrain if entity == PLAYER else self.ai_home_terrain
        before_breakdown = self._strength_breakdown(entity, home_terrain)

        self.grux_balance[entity] -= cost

        # La recluta entra riposata e abbassa la stanchezza media della riserva:
        # è il modo lento ma legittimo di rimettere in sesto un esercito logoro.
        tc.dilute_pool(self.reserve_condition[entity], len(self._entity_units(entity)))

        if entity == PLAYER:
            self.player_units.append(unit_id)
            self.player_army = aggregate_army(self.player_units, self.data["units"])
            self.player_modified, _ = apply_modifiers(
                army_vector=self.player_army,
                terrain_name=self.player_home_terrain,
                weather_name=self.weather,
                troop_status_name=self.player_troop_status,
                modifiers_data=self.data,
            )
            self.player_army_cost += cost
        else:
            self.ai_units.append(unit_id)
            self.ai_army = aggregate_army(self.ai_units, self.data["units"])
            self.ai_modified, _ = apply_modifiers(
                army_vector=self.ai_army,
                terrain_name=self.ai_home_terrain,
                weather_name=self.weather,
                troop_status_name=self.ai_troop_status,
                modifiers_data=self.data,
            )
            self.ai_army_cost += cost

        side = entity.value.upper()
        unit_name = self.units_map.get(unit_id, {}).get("name", unit_id)
        log_entry = f"[Turno {self.game_map.turn}] 💰 {side} recluta {unit_name} per {cost} grux"
        self.battle_log.append(log_entry)

        # La recluta IA deve raggiungere le legioni in campo, non restare a castello.
        if entity == AI and self._sync_ai_legion_units() and self.ai_legions:
            detail = " · ".join(
                f"'{lg.get('name', lid)}' {len(lg.get('units', []))}"
                for lid, lg in sorted(self.ai_legions.items())
            )
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] 🤖 IA rinforza le legioni → {detail} unità"
            )
        self.last_recruit_turn[entity] = self.game_map.turn

        after_breakdown = self._strength_breakdown(entity, home_terrain)
        log_strength_debug(
            "recruit_strength_delta",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "entity": entity.value,
                "unit_id": unit_id,
                "unit_cost": cost,
                "grux_balance_after": self.grux_balance[entity],
                "before": before_breakdown,
                "after": after_breakdown,
                "delta_effective_strength": round(
                    after_breakdown["effective_strength"] - before_breakdown["effective_strength"],
                    4,
                ),
            },
        )
        return log_entry

    # ──────────────────────────────────────────────────────────
    # RISOLUZIONE BATTAGLIA (privato)
    # ──────────────────────────────────────────────────────────

    def _resolve_encounter(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Risolve armata, guarnigione o assalto al castello."""
        encounter_type = move_result["encounter_type"]
        if encounter_type == "field_army":
            return self._resolve_field_battle(move_result, attacker)
        return self._resolve_static_defense(move_result, attacker)

    def _effective_army_strength(self, entity: Occupation, terrain: str) -> float:
        """Forza effettiva dell'armata sul terreno corrente, penalizzata se ha staccato troppi presidi."""
        return self._strength_breakdown(entity, terrain)["effective_strength"]

    def _strength_breakdown(self, entity: Occupation, terrain: str) -> Dict[str, Any]:
        """Breakdown DEBUG della forza usata in combattimento."""
        army_vector = self.player_army if entity == PLAYER else self.ai_army
        troop_status = self.player_troop_status if entity == PLAYER else self.ai_troop_status
        modified, warnings = apply_modifiers(
            army_vector=army_vector,
            terrain_name=terrain,
            weather_name=self.weather,
            troop_status_name=troop_status,
            modifiers_data=self.data,
        )

        composition = self._army_composition(entity)
        unit_power_rows: List[Dict[str, Any]] = []
        base_total = 0.0
        stack_bonus_total = 0.0
        total_legions = 0
        for unit_id, count in composition.items():
            value = self._unit_battle_value(unit_id)
            base_part = value * count
            # Bonus stack controllato: utile ma meno esplosivo in late game.
            stack_bonus = value * 0.22 * ((count - 1) ** 1.08) if count > 1 else 0.0
            stack_bonus = min(stack_bonus, base_part * 0.55)
            unit_power_rows.append(
                {
                    "unit_id": unit_id,
                    "unit_name": self.units_map.get(unit_id, {}).get("name", unit_id),
                    "count": count,
                    "unit_value": round(value, 3),
                    "base_part": round(base_part, 3),
                    "stack_bonus": round(stack_bonus, 3),
                }
            )
            base_total += base_part
            stack_bonus_total += stack_bonus
            total_legions += count

        strategy_compatibility = self._strategy_compatibility(entity, modified)
        strategy_factor = self._strategy_factor(entity, terrain, modified)
        detached = self.game_map.count_garrisons(entity)
        detach_penalty = max(0.7, 1.0 - (max(0, detached) * 0.06))

        # Fattore contesto ricavato dai modificatori su attributi: centro su 1.0
        context_factor = max(0.75, min(1.25, (sum(modified.values()) / 4.6)))

        base_strength = base_total + stack_bonus_total
        effective_strength = base_strength * strategy_factor * context_factor * detach_penalty
        return {
            "entity": entity.value,
            "terrain": terrain,
            "weather": self.weather,
            "troop_status": troop_status,
            "composition": composition,
            "composition_text": self._format_composition(entity),
            "legions_total": total_legions,
            "unit_power_rows": unit_power_rows,
            "detached_garrisons_over_base": max(0, detached),
            "detach_penalty": round(detach_penalty, 4),
            "strategy_factor": round(strategy_factor, 4),
            "strategy_compatibility": round(strategy_compatibility, 4),
            "context_factor": round(context_factor, 4),
            "base_strength": round(base_strength, 4),
            "effective_strength": int(round(effective_strength)),
            "modified_vector": {k: round(v, 4) for k, v in modified.items()},
            "modifier_warnings": warnings,
        }

    def _retreat_to_castle(self, entity: Occupation) -> None:
        """Ritira un'armata sulla linea davanti al castello, se ancora controllato."""
        castle_pos = self.game_map.get_castle_position(entity)
        if castle_pos is None:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        castle_cell = self.game_map.get_cell(*castle_pos)
        if castle_cell is None or castle_cell.occupation != entity:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        rally_cells: List[Tuple[int, int]] = []
        for neighbor in self.game_map.get_neighbors(*castle_pos):
            if neighbor.is_castle:
                continue
            if neighbor.occupation == entity:
                rally_cells.append((neighbor.row, neighbor.col))

        if not rally_cells:
            for neighbor in self.game_map.get_neighbors(*castle_pos):
                if neighbor.is_castle:
                    continue
                if neighbor.occupation == Occupation.NEUTRAL:
                    rally_cells.append((neighbor.row, neighbor.col))

        if not rally_cells:
            for neighbor in self.game_map.get_neighbors(*castle_pos):
                if not neighbor.is_castle:
                    rally_cells.append((neighbor.row, neighbor.col))

        if not rally_cells:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        if entity == PLAYER:
            rally_cells.sort(key=lambda pos: (-pos[0], abs(pos[1] - castle_pos[1])))
        else:
            rally_cells.sort(key=lambda pos: (pos[0], abs(pos[1] - castle_pos[1])))

        rally_pos = rally_cells[0]
        rally_cell = self.game_map.get_cell(*rally_pos)
        if rally_cell is None:
            self.state = SessionState.GAME_OVER
            self.winner = entity.opposite().value
            return

        rally_cell.occupation = entity
        self.game_map.positions[entity] = rally_pos

    def _resolve_field_battle(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Scontro tra le due armate principali. Il perdente si ritira al castello."""
        defender = attacker.opposite()
        terrain = move_result["terrain"]
        to_pos = tuple(move_result["to_pos"])
        attacker_units_before = len(self._entity_units(attacker))
        defender_units_before = len(self._entity_units(defender))

        enemy_castle = self.game_map.get_castle_position(defender)
        battle_label = self._format_battle_location(terrain)
        if enemy_castle == to_pos:
            battle_label = "🏰 Assalto al castello centrale"

        # Caso bordo: una delle due armate e vuota. Evita "battaglie" fittizie con forza 0.
        if attacker_units_before <= 0 or defender_units_before <= 0:
            if attacker_units_before > defender_units_before:
                winner = attacker
                loser = defender
            elif defender_units_before > attacker_units_before:
                winner = defender
                loser = attacker
            else:
                winner = defender
                loser = attacker

            contested_cell = self.game_map.get_cell(*to_pos)
            if contested_cell is not None:
                contested_cell.garrison_strength = 0
                contested_cell.garrison_unit_ids = []
                contested_cell.fortification_level = 0
                contested_cell.occupation = winner

            self.game_map.positions[winner] = to_pos
            self._retreat_to_castle(loser)

            if enemy_castle == to_pos and winner == attacker:
                self.state = SessionState.GAME_OVER
                self.winner = attacker.value

            attacker_comp = self._format_composition(attacker)
            defender_comp = self._format_composition(defender)
            attacker_strength = (
                self._strength_breakdown(attacker, terrain)["effective_strength"]
                if attacker_units_before > 0
                else 0
            )
            defender_strength = (
                self._strength_breakdown(defender, terrain)["effective_strength"]
                if defender_units_before > 0
                else 0
            )

            if attacker_units_before <= 0 and defender_units_before <= 0:
                outcome_text = f"Nessuno scontro: armate assenti, prevale {winner.value.upper()}"
            elif attacker_units_before <= 0:
                outcome_text = f"Nessuno scontro: armata {attacker.value.upper()} assente, prevale {winner.value.upper()}"
            else:
                outcome_text = f"Nessuno scontro: armata {defender.value.upper()} assente, prevale {winner.value.upper()}"

            log_entry = (
                f"[Turno {self.game_map.turn}] {battle_label}: "
                f"{attacker.value.upper()} [{attacker_comp}] forza {attacker_strength} "
                f"vs {defender.value.upper()} [{defender_comp}] forza {defender_strength} "
                f"→ {outcome_text}"
            )
            self.battle_log.append(log_entry)

            return {
                "type": "field_army",
                "terrain": terrain,
                "winner": winner.value,
                "loser": loser.value,
                "attacker_strength": round(attacker_strength, 3),
                "defender_strength": round(defender_strength, 3),
                "log": log_entry,
            }

        attacker_breakdown = self._strength_breakdown(attacker, terrain)
        defender_breakdown = self._strength_breakdown(defender, terrain)
        attacker_strength = attacker_breakdown["effective_strength"]
        defender_strength = defender_breakdown["effective_strength"]
        defender_movement_modifier = self.movement_system.get_defense_modifier(defender)

        if defender_movement_modifier.get("active"):
            defender_strength_before_penalty = defender_strength
            defender_strength = int(round(defender_strength * float(defender_movement_modifier["factor"])))
            defender_breakdown["effective_strength_before_movement_penalty"] = defender_strength_before_penalty
            defender_breakdown["movement_defense_penalty"] = {
                "active": True,
                "reduction_ratio": round(float(defender_movement_modifier["reduction_ratio"]), 4),
                "factor": round(float(defender_movement_modifier["factor"]), 4),
                "blocked_turns": int(defender_movement_modifier["blocked_turns"]),
                "last_terrain": defender_movement_modifier.get("last_terrain"),
                "last_cost": defender_movement_modifier.get("last_cost"),
            }
            defender_breakdown["effective_strength"] = defender_strength

        if attacker_strength > defender_strength:
            winner = attacker
            loser = defender
        elif defender_strength > attacker_strength:
            winner = defender
            loser = attacker
        else:
            winner = defender
            loser = attacker

        contested_cell = self.game_map.get_cell(*to_pos)
        if contested_cell is not None:
            contested_cell.garrison_strength = 0
            contested_cell.garrison_unit_ids = []
            contested_cell.fortification_level = 0
            contested_cell.occupation = winner

        self.game_map.positions[winner] = to_pos
        self._retreat_to_castle(loser)

        if enemy_castle == to_pos and winner == attacker:
            self.state = SessionState.GAME_OVER
            self.winner = attacker.value

        attacker_comp = attacker_breakdown["composition_text"]
        defender_comp = defender_breakdown["composition_text"]

        attacker_losses = self._calculate_losses_for_battle(
            attacker_units_before,
            attacker_strength,
            defender_strength,
        )
        defender_losses = self._calculate_losses_for_battle(
            defender_units_before,
            defender_strength,
            attacker_strength,
        )
        attacker_loss_result = self._apply_attacker_losses(attacker, attacker_losses)
        defender_loss_result = self._apply_attacker_losses(defender, defender_losses)

        log_entry = (
            f"[Turno {self.game_map.turn}] {battle_label}: "
            f"{attacker.value.upper()} [{attacker_comp}] forza {attacker_strength} "
            f"vs {defender.value.upper()} [{defender_comp}] forza {defender_strength} "
            f"→ Ritirata di {loser.value.upper()}"
        )
        if defender_movement_modifier.get("active"):
            penalty_pct = int(round(float(defender_movement_modifier["reduction_ratio"]) * 100))
            log_entry += (
                f" | Difesa {defender.value.upper()} ridotta del {penalty_pct}% "
                f"(movimento incompleto)"
            )
        if attacker_loss_result["losses"] > 0 or defender_loss_result["losses"] > 0:
            log_entry += (
                f" | Perdite {attacker.value.upper()}: {attacker_loss_result['losses']}"
                f" | Perdite {defender.value.upper()}: {defender_loss_result['losses']}"
            )
        self.battle_log.append(log_entry)
        if attacker_loss_result["losses"] > 0 and attacker_loss_result["removed_text"]:
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] ☠ {attacker.value.upper()} perde {attacker_loss_result['removed_text']}"
            )
        if defender_loss_result["losses"] > 0 and defender_loss_result["removed_text"]:
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] ☠ {defender.value.upper()} perde {defender_loss_result['removed_text']}"
            )
        log_strength_debug(
            "field_battle_strength",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "terrain": terrain,
                "attacker": attacker.value,
                "defender": defender.value,
                "attacker_breakdown": attacker_breakdown,
                "defender_breakdown": defender_breakdown,
                "attacker_units_before": attacker_units_before,
                "defender_units_before": defender_units_before,
                "attacker_losses": attacker_loss_result["losses"],
                "defender_losses": defender_loss_result["losses"],
                "winner": winner.value,
                "loser": loser.value,
                "encounter_pos": list(to_pos),
            },
        )

        return {
            "type": "field_army",
            "terrain": terrain,
            "winner": winner.value,
            "loser": loser.value,
            "attacker_strength": round(attacker_strength, 3),
            "defender_strength": round(defender_strength, 3),
            "log": log_entry,
        }

    def _resolve_static_defense(self, move_result: Dict[str, Any], attacker: Occupation) -> Dict[str, Any]:
        """Risoluzione di guarnigioni e castelli."""
        defender = attacker.opposite()
        terrain = move_result["terrain"]
        from_pos = tuple(move_result.get("from_pos", self.game_map.positions.get(attacker, (0, 0))))
        to_pos = tuple(move_result["to_pos"])
        dest_cell = self.game_map.get_cell(*to_pos)
        encounter_type = move_result["encounter_type"]
        attacker_units_before = len(self._entity_units(attacker))

        attacker_breakdown = self._strength_breakdown(attacker, terrain)
        attacker_strength = attacker_breakdown["effective_strength"]
        garrison_strength = dest_cell.garrison_strength if dest_cell else 0
        garrison_units = list(dest_cell.garrison_unit_ids) if dest_cell else []
        fortification_level = dest_cell.fortification_level if dest_cell else 0
        fortification_bonus = 0.0
        garrison_component = 0.0
        garrison_unit_quality_bonus = 0.0
        synergy_bonus = 0.0

        if garrison_strength > 0:
            # Presidio più incisivo, con componente che scala sull'intensità dell'assalto.
            garrison_component = (
                (garrison_strength * 18.0)
                + (attacker_strength * min(0.22, garrison_strength * 0.025))
            )

        if garrison_units:
            # Le unità realmente distaccate modificano la resa difensiva del presidio.
            garrison_unit_quality_bonus = (
                sum(self._garrison_unit_defense_value(unit_id, terrain) for unit_id in garrison_units) * 11.5
            )

        if fortification_level > 0:
            # Fortificazioni con impatto crescente anche in late game:
            # base fissa + componente scalata sulla forza dell'assalto.
            scaling_component = attacker_strength * min(0.32, 0.12 + (fortification_level * 0.05))
            stack_component = max(0, fortification_level - 1) * 16.0
            fortification_bonus = (fortification_level * 18.0) + scaling_component + stack_component

        if garrison_strength > 0 and fortification_level > 0:
            # Sinergia: presidio dentro fortificazione rende la difesa molto più efficiente.
            synergy_bonus = (
                (fortification_level * garrison_strength * 7.0)
                + (attacker_strength * min(0.12, 0.015 * fortification_level * garrison_strength))
            )

        if dest_cell and dest_cell.is_castle:
            # Difesa castello rinforzata per evitare cadute immediate
            defender_units = len(self.player_units if defender == PLAYER else self.ai_units)
            terrain_bonus = 8.0 if terrain in {"Foresta", "Montagna", "Palude"} else 5.0
            castle_bonus = 38.0 + (defender_units * 3.2)
        else:
            terrain_bonus = 5.0 if terrain in {"Foresta", "Montagna", "Palude"} else 2.0
            castle_bonus = 0.0

        defender_score = (
            garrison_component
            + garrison_unit_quality_bonus
            + terrain_bonus
            + castle_bonus
            + fortification_bonus
            + synergy_bonus
        )
        attacker_losses = self._calculate_losses_for_battle(
            attacker_units_before,
            attacker_strength,
            defender_score,
            fortification_level=fortification_level,
            garrison_strength=garrison_strength,
        )
        castle_damage = 0
        castle_hp_before = None
        castle_hp_after = None

        if attacker_strength > defender_score:
            winner = attacker
            loser = defender
            if dest_cell is not None and dest_cell.is_castle:
                castle_hp_before = self.castle_hp.get(defender, self.castle_hp_max.get(defender, CASTLE_BASE_HP))
                castle_damage = self._compute_castle_damage(attacker_strength, defender_score)
                castle_hp_after = max(0, castle_hp_before - castle_damage)
                self.castle_hp[defender] = castle_hp_after

                if castle_hp_after <= 0:
                    dest_cell.garrison_strength = 0
                    dest_cell.garrison_unit_ids = []
                    dest_cell.fortification_level = 0
                    dest_cell.occupation = attacker
                    self.state = SessionState.GAME_OVER
                    self.winner = attacker.value
                else:
                    # Il castello regge l'assalto: l'attaccante viene respinto alla linea di partenza.
                    self._retreat_to_castle(attacker)
                    dest_cell.occupation = defender
                    winner = defender
                    loser = attacker
            else:
                if dest_cell is not None:
                    dest_cell.garrison_strength = 0
                    dest_cell.garrison_unit_ids = []
                    dest_cell.fortification_level = 0
                    dest_cell.occupation = attacker
                self.game_map.positions[attacker] = to_pos
        else:
            winner = defender
            loser = attacker
            if encounter_type == "castle":
                # Assalto respinto: niente spam in adiacenza, rientro alla linea di partenza.
                self._retreat_to_castle(attacker)
            else:
                self._retreat_to_castle(attacker)
            if dest_cell is not None:
                dest_cell.occupation = defender

        loss_result = self._apply_attacker_losses(attacker, attacker_losses)

        if encounter_type == "castle":
            label = "🏰 Assalto al castello centrale"
        elif dest_cell is not None and dest_cell.is_mine:
            label = "⛏ Battaglia per la conquista della miniera"
        elif encounter_type == "garrison" and fortification_level > 0:
            label = "🧱🛡 Assalto a presidio fortificato"
        elif encounter_type == "fortified":
            label = "🧱 Assalto a territorio fortificato"
        elif encounter_type == "garrison":
            label = "🛡 Scontro contro presidio territoriale"
        else:
            label = "⚔ Scontro territoriale"

        attacker_comp = attacker_breakdown["composition_text"]

        log_entry = (
            f"[Turno {self.game_map.turn}] {label} su {terrain}: "
            f"{attacker.value.upper()} [{attacker_comp}] forza {attacker_strength} "
            f"vs difesa statica {int(round(defender_score))} "
            f"→ Vince {winner.value.upper()}"
        )
        if loss_result["losses"] > 0:
            log_entry += f" | Perdite {attacker.value.upper()}: {loss_result['losses']}"
        if castle_hp_before is not None and castle_hp_after is not None:
            log_entry += (
                f" | Danno castello: {castle_damage} "
                f"(HP {castle_hp_before}->{castle_hp_after})"
            )
        self.battle_log.append(log_entry)
        if loss_result["losses"] > 0 and loss_result["removed_text"]:
            self.battle_log.append(
                f"[Turno {self.game_map.turn}] ☠ {attacker.value.upper()} perde {loss_result['removed_text']}"
            )
        log_strength_debug(
            "static_defense_battle_strength",
            {
                "debug_notice": "DEBUG TEMPORANEO - rimuovere cartella debug in produzione",
                "turn": self.game_map.turn,
                "terrain": terrain,
                "encounter_type": encounter_type,
                "attacker": attacker.value,
                "defender": defender.value,
                "attacker_breakdown": attacker_breakdown,
                "defense_breakdown": {
                    "garrison_strength": garrison_strength,
                    "fortification_level": fortification_level,
                    "fortification_bonus": round(fortification_bonus, 4),
                    "synergy_bonus": round(synergy_bonus, 4),
                    "garrison_component": round(garrison_component, 4),
                    "garrison_unit_quality_bonus": round(garrison_unit_quality_bonus, 4),
                    "garrison_unit_ids": garrison_units,
                    "terrain_bonus": terrain_bonus,
                    "castle_bonus": castle_bonus,
                    "castle_hp_before": castle_hp_before,
                    "castle_hp_after": castle_hp_after,
                    "castle_damage": castle_damage,
                    "defender_score": round(defender_score, 4),
                    "attacker_units_before": attacker_units_before,
                    "attacker_losses": loss_result["losses"],
                },
                "winner": winner.value,
                "loser": loser.value,
                "encounter_pos": list(to_pos),
            },
        )

        return {
            "type": encounter_type,
            "terrain": terrain,
            "winner": winner.value,
            "loser": loser.value,
            "attacker_strength": round(attacker_strength, 3),
            "defender_strength": round(defender_score, 3),
            "log": log_entry,
        }

    # ──────────────────────────────────────────────────────────
    # SERIALIZZAZIONE
    # ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Stato completo della sessione (per l'API)."""
        return {
            "state":   self.state.value,
            "winner":  self.winner,
            "weather": self.weather,
            # Stato ambientale completo per l'indicatore: i due assi separati,
            # emoji, colori, effetti in chiaro e quanti turni mancano al cambio.
            "weather_state": self.weather_state(),
            "player": {
                "units":         self.player_units,
                "strategy_id":   self.player_strategy_id,
                "strategy_name": self.strategies_map.get(self.player_strategy_id, {}).get("name", self.player_strategy_id),
                "army":          self.player_army,
                "modified":      self.player_modified,
                # Stato della riserva nel castello: non è più il valore fisso
                # scelto a inizio partita (che restava "n/d" se non sceglievi),
                # ma la condizione viva delle truppe ferme in castello.
                "troop_status":  tc.resolve_status(self.reserve_condition[PLAYER]),
                "troop_condition": tc.describe(self.reserve_condition[PLAYER]),
                "initial_troop_status": self.player_troop_status,
                "legions":       self._legions_with_strategy(PLAYER),
                "castle": {
                    "hp": self.castle_hp.get(PLAYER, self.castle_hp_max.get(PLAYER, CASTLE_BASE_HP)),
                    "max_hp": self.castle_hp_max.get(PLAYER, CASTLE_BASE_HP),
                },
                "auto_recruit": {
                    "enabled": bool(self.player_auto_recruit.get("enabled")),
                    "unit_id": self.player_auto_recruit.get("unit_id"),
                    "unit_name": self.player_auto_recruit.get("unit_name"),
                    "turns_total": int(self.player_auto_recruit.get("turns_total") or 0),
                    "turns_remaining": int(self.player_auto_recruit.get("turns_remaining") or 0),
                    "attempted_turns": int(self.player_auto_recruit.get("attempted_turns") or 0),
                    "successful_recruits": int(self.player_auto_recruit.get("successful_recruits") or 0),
                    "last_result": self.player_auto_recruit.get("last_result") or "inactive",
                    "last_reason": self.player_auto_recruit.get("last_reason"),
                },
                "available_garrisons": self._available_garrisons(PLAYER),
                "grux_balance":  self.grux_balance[PLAYER],
                "army_cost":     self.player_army_cost,
                "available_mine_slots": self._available_mine_slots(PLAYER),
                "fortification_base_cost": self.base_fortification_cost,
                "movement": self.movement_system.export_entity_state(PLAYER),
                "abilities": ab.states_payload(
                    self.ability_states[PLAYER], self.game_map.turn, self.grux_balance[PLAYER]
                ),
                "ability_paths": ab.path_order(),
                # Cosa concedono adesso le abilità di costruzione. La UI accende
                # le celle da qui invece di ragionare sugli id delle abilità.
                "build_rules": {
                    "anywhere": self._ability_flag(PLAYER, ab.FLAG_BUILD_ANYWHERE),
                    "any_legion": self._ability_flag(PLAYER, ab.FLAG_BUILD_ANY_LEGION),
                },
                "black_market": self.black_market[PLAYER].to_dict(
                    self.game_map.turn, self._black_market_open(PLAYER)
                ),
                "recruit_cooldown_turns": self._recruit_cooldown_for(PLAYER),
                # Prezzi effettivi di reclutamento: il listino di /config non
                # sa niente delle abilità, e senza questi il menu mostrerebbe
                # un prezzo diverso da quello che poi viene scalato.
                "recruit_costs": {
                    unit_id: self._recruit_cost(PLAYER, unit_id) for unit_id in self.unit_costs
                },
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.player_units},
            },
            "ai": {
                "units":         self.ai_units,
                "strategy_id":   self.ai_strategy_id,
                "strategy_name": self.ai_strategy_name,
                "difficulty":    self.ai_difficulty,
                "difficulty_labels": get_ai_difficulty_labels(),
                "legions":       self._legions_with_strategy(AI),
                "castle": {
                    "hp": self.castle_hp.get(AI, self.castle_hp_max.get(AI, CASTLE_BASE_HP)),
                    "max_hp": self.castle_hp_max.get(AI, CASTLE_BASE_HP),
                },
                "army":          self.ai_army,
                "modified":      self.ai_modified,
                "troop_status":  tc.resolve_status(self.reserve_condition[AI]),
                "troop_condition": tc.describe(self.reserve_condition[AI]),
                "initial_troop_status": self.ai_troop_status,
                "available_garrisons": self._available_garrisons(AI),
                "grux_balance":  self.grux_balance[AI],
                "army_cost":     self.ai_army_cost,
                "available_mine_slots": self._available_mine_slots(AI),
                "movement": self.movement_system.export_entity_state(AI),
                "abilities": ab.states_payload(
                    self.ability_states[AI], self.game_map.turn, self.grux_balance[AI]
                ),
                "black_market": self.black_market[AI].to_dict(
                    self.game_map.turn, self._black_market_open(AI)
                ),
                "unit_costs":    {unit_id: self.unit_costs[unit_id] for unit_id in self.ai_units},
            },
            "movement": self.movement_system.export_config(),
            "map":        self.game_map.to_dict(),
            "battle_log": self.battle_log,
            # [ENDGAME-STATS] Numeri per la schermata di fine partita. Il tempo
            # sta qui e non nel browser perché deve sopravvivere a un ricarico
            # della pagina: la sessione vive nel server, la scheda no.
            "stats": {
                "elapsed_seconds": max(0, int(time.time() - self.started_at)),
                "troops_lost": {
                    "player": int(self.troops_lost.get(PLAYER, 0)),
                    "ai": int(self.troops_lost.get(AI, 0)),
                },
            },
            # [DEBUG-MODULE] Letto dal pannello debug per mostrare lo stato dello
            # switch. Rimuovibile con il modulo: nessun'altra parte lo consuma.
            "debug": {
                "ai_kill_switch_active": self.debug_ai_kill_switch,
            },
        }
