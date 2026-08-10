"""
War Advisor - Balance Testing System (forza truppe)

Fratello di `rapidtest.py`, ma su un'altra domanda. Rapidtest risponde a
"quale strategia consiglio a questo esercito?"; questo risponde a
"quanto pesa davvero questa truppa in battaglia, e quanto mi costa?".

Due modi di lavorare:

    guidato    chiedo io composizione, terreno e condizioni (o sorteggio solo
               il meteo), una composizione alla volta
    casuale    dico quanti test voglio e sorteggia tutto: serve a coprire
               tanto terreno in fretta e far emergere gli sbilanciamenti

Ogni esecuzione scrive un file NUOVO in `reports/`, con:

    · il valore di ogni singola unità, scomposto in base / meteo / terreno
    · quanto rende ciascuna rispetto a quanto costa (valore per grux)
    · la forza della legione in attacco e in difesa
    · come cambia quella forza in tutte e sei le condizioni e su tutti i terreni
    · il danno che farebbe a un castello
    · avvisi automatici di sbilanciamento
    · in coda, se le prove sono più di una, la classifica delle unità per
      resa media: è lì che si vede quale truppa costa troppo poco

I numeri NON sono ricalcolati qui: vengono chiesti alla sessione di gioco
vera (`GameSession`), le stesse funzioni che girano in partita. Se cambi il
bilanciamento nel gioco, questo report cambia di conseguenza — è il punto.
"""

import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from engine import load_data, aggregate_army, apply_modifiers, compute_ranking
from gamecore.gameflow import start_game_session
from gamecore.session.session import (
    PLAYER,
    AI,
    UNIT_BATTLE_WEIGHTS,
    CASTLE_BASE_HP,
)
import gamecore.session.troop_condition as tc
import gamecore.session.weather_cycle as wc

# [BALANCE-LAYER] Il report deve misurare il gioco com'è davvero: se il layer
# di bilanciamento c'è, la forza d'assedio passa da lì come in partita.
try:
    from gamecore import troop_balance as balance
except ImportError:                                           # layer rimosso
    balance = None

# Le emoji su una console cp1252 fanno esplodere il print: meglio degradare
# il singolo carattere che perdere tutto il report.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                             # pragma: no cover
    pass

REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

#: Difesa di riferimento per il confronto in difesa: cella fortificata di
#: livello 2 con 2 presidi. È uno scenario "normale", non estremo.
BENCHMARK_FORT_LEVEL = 2
BENCHMARK_GARRISON = 2
#: Presidi sul castello nemico per la stima del danno d'assedio.
BENCHMARK_CASTLE_GARRISON = 2

SEPARATOR = "=" * 78
THIN = "-" * 78

#: Quante unità mette in campo un test casuale, se non lo decidi tu.
RANDOM_UNITS_MIN = 3
RANDOM_UNITS_MAX = 10
#: Quanti tipi diversi mescola un test casuale.
RANDOM_TYPES_MAX = 3


def report_stamp() -> str:
    """Nome del file: giorno-mese--ora-minuti-secondi."""
    return datetime.now().strftime("%d-%m--%H-%M-%S")


# ══════════════════════════════════════════════════════════════════
# SESSIONE DI CALCOLO
# ══════════════════════════════════════════════════════════════════

def build_calculator_session(data: Dict[str, Any]) -> Any:
    """Sessione usata solo come calcolatrice.

    Nasce con l'esercito più economico possibile perché la partenza ha un
    tetto di budget: la composizione da testare non passa da lì, viene
    valutata come legione sintetica. Così si possono provare 30 unità senza
    che il budget iniziale dica di no.
    """
    cheapest = min(data["units"], key=lambda u: u.get("cost_grux", 0))["id"]
    units = [cheapest]
    army = aggregate_army(units, data["units"])
    modified, _ = apply_modifiers(army, "Pianura", "Sereno", tc.STATUS_FRESH, data)

    started = start_game_session(
        data=data,
        player_units=units,
        terrain="Pianura",
        weather=wc.combined_key(wc.CYCLE_DAY, wc.WEATHER_CLEAR),
        troop_status=tc.STATUS_FRESH,
        strategy_id=data["strategies"][0]["id"],
        army_profile=army,
        modified_profile=modified,
        map_seed=1234,
        ai_difficulty="normal",
    )
    return started["session"]


def set_conditions(session: Any, cycle: str, weather: str) -> None:
    """Impone ciclo e meteo alla sessione di calcolo."""
    session.day_cycle = cycle
    session.weather_base = weather
    session._refresh_weather_key()


def make_legion(composition: Dict[str, int], status: str, strategy_id: str) -> Dict[str, Any]:
    """Legione sintetica con la composizione da testare."""
    units: List[str] = []
    for unit_id, count in composition.items():
        units.extend([unit_id] * count)
    return {
        "id": "BALANCE",
        "name": "Test",
        "units": units,
        "pos": (10, 5),
        "strategy_id": strategy_id,
        "condition": tc.new_condition(status),
    }


def benchmark_cell(session: Any, terrain: str, garrison_unit: str) -> Any:
    """Cella di riferimento per la prova in difesa: fortificata e presidiata."""
    cell = session.game_map.get_cell(8, 5)
    cell.terrain = terrain
    cell.fortification_level = BENCHMARK_FORT_LEVEL
    cell.garrison_strength = BENCHMARK_GARRISON
    cell.garrison_unit_ids = [garrison_unit] * BENCHMARK_GARRISON
    return cell


# ══════════════════════════════════════════════════════════════════
# MISURE
# ══════════════════════════════════════════════════════════════════

def unit_rows(session: Any, composition: Dict[str, int], terrain: str) -> List[Dict[str, Any]]:
    """Valore di ogni unità scomposto nei suoi tre pezzi."""
    rows = []
    for unit_id, count in composition.items():
        unit = session.units_map[unit_id]
        attrs = unit["attributes"]

        base = sum(attrs[key] * weight for key, weight in UNIT_BATTLE_WEIGHTS.items())
        weather_factor = session._weather_unit_factor(unit_id)
        battle_value = session._unit_battle_value(unit_id)          # base × meteo
        terrain_value = session._garrison_unit_defense_value(unit_id, terrain)
        terrain_factor = terrain_value / battle_value if battle_value else 1.0
        cost = session.unit_costs.get(unit_id, 0)

        rows.append({
            "unit_id": unit_id,
            "name": unit.get("name", unit_id),
            "count": count,
            "base": base,
            "weather_factor": weather_factor,
            "terrain_factor": terrain_factor,
            "value": terrain_value,
            "total": terrain_value * count,
            "cost": cost,
            "cost_total": cost * count,
            "per_grux": (terrain_value / cost) if cost else 0.0,
        })
    rows.sort(key=lambda r: -r["total"])
    return rows


def strength(session: Any, legion: Dict[str, Any], terrain: str, *, cell=None) -> Dict[str, Any]:
    return session._legion_battle_strength(
        PLAYER, legion, terrain,
        defending=cell is not None, cell=cell, enemy_strength=0.0, movement_key=None,
    )


def siege_force(session: Any, unit_ids: List[str]) -> float:
    """Forza d'assedio, passando dal layer di bilanciamento se c'è.

    Senza questo il report ignorerebbe il ruolo d'assedio dell'artiglieria e
    darebbe numeri diversi da quelli che poi si vedono in partita.
    """
    if balance is not None:
        return balance.siege_strength(unit_ids, session._unit_battle_value)
    return sum(session._unit_battle_value(uid) for uid in unit_ids)


def castle_estimate(session: Any, legion: Dict[str, Any]) -> Dict[str, Any]:
    """Danno che questa legione farebbe al castello nemico.

    Stessa formula del gioco: la forza d'assedio è la somma dei valori unità
    (pesata dal layer, se presente), non la forza tattica della legione.
    """
    castle_pos = session.game_map.castle_positions[AI]
    cell = session.game_map.get_cell(*castle_pos)
    cell.garrison_unit_ids = ["heavy_infantry"] * BENCHMARK_CASTLE_GARRISON
    cell.garrison_strength = BENCHMARK_CASTLE_GARRISON
    cell.fortification_level = 0

    attacker = max(20.0, siege_force(session, legion["units"]))
    defense = session._castle_defense(AI, castle_pos)
    damage = session._compute_castle_damage(attacker, defense["score"])
    damage = max(8, int(round(damage * defense["damage_multiplier"])))
    hp = session.castle_hp_max.get(AI, CASTLE_BASE_HP)
    return {
        "attacker": attacker,
        "defense": defense["score"],
        "damage": damage,
        "hp": hp,
        "assaults": (hp + damage - 1) // damage if damage else 0,
    }


def troop_value(session: Any, legion: Dict[str, Any], terrain: str) -> float:
    """Valore nudo delle truppe, prima di strategia e contesto."""
    return sum(session._garrison_unit_defense_value(uid, terrain) for uid in legion["units"])


def sweep_conditions(
    session: Any, legion: Dict[str, Any], terrain: str, current: Tuple[str, str]
) -> List[Dict[str, Any]]:
    """Forza della stessa legione in tutte e sei le condizioni.

    Si misurano due cose diverse e vanno tenute separate: quanto valgono le
    truppe (che è il meteo sulle unità) e quanto vale la legione (dove entra
    anche quanto la strategia si adatta al vettore modificato). Possono
    muoversi in direzioni opposte, ed è un'informazione, non un errore.
    """
    rows = []
    for cycle in wc.CYCLES:
        for weather in wc.WEATHERS:
            set_conditions(session, cycle, weather)
            rows.append({
                "label": wc.combined_key(cycle, weather),
                "troops": troop_value(session, legion, terrain),
                "strength": strength(session, legion, terrain)["strength"],
                "current": (cycle, weather) == current,
            })
    set_conditions(session, *current)
    return rows


def sweep_terrains(session: Any, legion: Dict[str, Any], current_terrain: str) -> List[Dict[str, Any]]:
    """Forza della stessa legione su ogni terreno, condizioni ferme."""
    rows = []
    for terrain in session.data["terrain"].keys():
        rows.append({
            "terrain": terrain,
            "troops": troop_value(session, legion, terrain),
            "strength": strength(session, legion, terrain)["strength"],
            "current": terrain == current_terrain,
        })
    return rows


def balance_warnings(
    rows: List[Dict[str, Any]],
    conditions: List[Dict[str, Any]],
    terrains: List[Dict[str, Any]],
    breakdown: Dict[str, Any],
    total_strength: float,
) -> List[str]:
    """Le anomalie che varrebbe la pena guardare, in parole povere."""
    warnings: List[str] = []

    # 1. Resa per grux fuori scala rispetto alla media dello schieramento.
    paganti = [r for r in rows if r["cost"]]
    if len(paganti) >= 2:
        media = sum(r["per_grux"] for r in paganti) / len(paganti)
        for row in paganti:
            scarto = (row["per_grux"] / media - 1.0) * 100 if media else 0.0
            if scarto <= -25:
                warnings.append(
                    f"{row['name']}: rende {row['per_grux']:.2f} per grux contro una media di "
                    f"{media:.2f} ({scarto:+.0f}%) — cara per quello che porta"
                )
            elif scarto >= 30:
                warnings.append(
                    f"{row['name']}: rende {row['per_grux']:.2f} per grux contro una media di "
                    f"{media:.2f} ({scarto:+.0f}%) — conviene troppo, è la scelta ovvia"
                )

    # 2. Una sola unità che porta quasi tutta la forza.
    somma = sum(r["total"] for r in rows) or 1.0
    for row in rows:
        quota = row["total"] / somma
        if quota >= 0.55 and len(rows) > 1:
            warnings.append(
                f"{row['name']}: da sola vale il {quota*100:.0f}% della forza della legione — "
                f"la composizione dipende da lei"
            )

    # 3. Condizioni che spostano troppo, o troppo poco.
    valori = [c["strength"] for c in conditions]
    if valori and max(valori) > 0:
        escursione = (max(valori) - min(valori)) / max(valori) * 100
        peggiore = min(conditions, key=lambda c: c["strength"])
        migliore = max(conditions, key=lambda c: c["strength"])
        if escursione >= 25:
            warnings.append(
                f"il meteo sposta il {escursione:.0f}% della forza "
                f"(meglio con {migliore['label']}, peggio con {peggiore['label']}) — "
                f"composizione molto esposta alle condizioni"
            )
        elif escursione <= 4:
            warnings.append(
                f"il meteo sposta appena il {escursione:.0f}%: per questa composizione "
                f"le condizioni sono quasi ininfluenti"
            )

    # 4. Truppe e legione che vanno in direzioni opposte: succede quando il
    #    meteo peggiora le unità ma avvicina il vettore all'ideale della
    #    strategia. È lecito, ma è bene saperlo prima di tarare i numeri.
    riferimento = next((c for c in conditions if c["current"]), None)
    if riferimento and riferimento["troops"] and riferimento["strength"]:
        for cond in conditions:
            if cond["current"]:
                continue
            d_truppe = cond["troops"] / riferimento["troops"] - 1.0
            d_forza = cond["strength"] / riferimento["strength"] - 1.0
            if d_truppe <= -0.04 and d_forza >= 0.02:
                warnings.append(
                    f"con {cond['label']} le truppe perdono il {abs(d_truppe)*100:.0f}% "
                    f"ma la legione guadagna il {d_forza*100:.0f}%: a compensare è la "
                    f"strategia, che con quel meteo si adatta meglio al vettore"
                )
            elif d_truppe >= 0.04 and d_forza <= -0.02:
                warnings.append(
                    f"con {cond['label']} le truppe guadagnano il {d_truppe*100:.0f}% "
                    f"ma la legione perde il {abs(d_forza)*100:.0f}%: la strategia scelta "
                    f"regge peggio in quelle condizioni"
                )

    # 5. Terreni che cambiano la partita.
    valori_t = [t["strength"] for t in terrains]
    if valori_t and max(valori_t) > 0:
        escursione_t = (max(valori_t) - min(valori_t)) / max(valori_t) * 100
        if escursione_t >= 25:
            peggiore = min(terrains, key=lambda t: t["strength"])
            warnings.append(
                f"il terreno sposta il {escursione_t:.0f}% della forza: "
                f"da evitare {peggiore['terrain']}"
            )

    # 6. Strategia palesemente sbagliata per questa composizione.
    fattore = breakdown.get("strategy_factor", 1.0)
    if fattore <= 0.6:
        warnings.append(
            f"fattore strategia {fattore:.2f}: la strategia scelta non c'entra nulla "
            f"con questa composizione, la forza è quasi dimezzata"
        )
    elif fattore >= 2.0:
        warnings.append(
            f"fattore strategia {fattore:.2f}: accoppiata molto premiata, "
            f"buona parte della forza viene da lì e non dalle truppe"
        )

    if not warnings:
        warnings.append("nessuna anomalia evidente: composizione equilibrata rispetto a costo e contesto")
    return warnings


# ══════════════════════════════════════════════════════════════════
# REPORT
# ══════════════════════════════════════════════════════════════════

def bar(value: float, maximum: float, width: int = 22) -> str:
    if maximum <= 0:
        return "░" * width
    filled = int(round((value / maximum) * width))
    return "█" * max(0, min(width, filled)) + "░" * max(0, width - filled)


def write_report(path: Path, result: Dict[str, Any], append: bool) -> None:
    rows = result["rows"]
    setup = result["setup"]

    with open(path, "a" if append else "w", encoding="utf-8") as f:
        w = f.write

        w(SEPARATOR + "\n")
        w(f"BILANCIAMENTO FORZA TRUPPE - {result['timestamp']}\n")
        w(SEPARATOR + "\n\n")

        # ── Schieramento ────────────────────────────────────────────
        w("🗡️  SCHIERAMENTO\n")
        for row in rows:
            w(f"   • {row['count']}x {row['name']} ({row['unit_id']})\n")
        w(f"\n   Unità totali:  {setup['total_units']}\n")
        w(f"   Costo totale:  {setup['total_cost']} grux\n")
        w(f"   Terreno:       {setup['terrain']}\n")
        w(f"   Condizioni:    {setup['weather_label']}  ({setup['weather_origin']})\n")
        w(f"   Stato truppe:  {setup['status']}\n")
        w(f"   Strategia:     {setup['strategy_name']}  "
          f"(compatibilità {setup['strategy_compat']:.1f}%, {setup['strategy_origin']})\n\n")

        if result["critical_warnings"]:
            w("⚠️  AVVISI CRITICI DELL'ENGINE\n")
            for warning in result["critical_warnings"]:
                w(f"   ! {warning}\n")
            w("\n")

        # ── Valore delle singole unità ──────────────────────────────
        w("📊 VALORE DELLE SINGOLE UNITÀ (nelle condizioni scelte)\n")
        w(f"   {'unità':<20}{'n':>3}{'base':>9}{'meteo':>9}{'terreno':>9}"
          f"{'valore':>9}{'costo':>8}{'val/grux':>10}\n")
        w("   " + "·" * 74 + "\n")
        for row in rows:
            w(f"   {row['name'][:19]:<20}{row['count']:>3}{row['base']:>9.1f}"
              f"{row['weather_factor']:>8.2f}x{row['terrain_factor']:>8.2f}x"
              f"{row['value']:>9.1f}{row['cost']:>8}{row['per_grux']:>10.2f}\n")
        w("\n   base    = valore nudo dagli attributi\n")
        w("   meteo   = moltiplicatore delle condizioni correnti\n")
        w("   terreno = moltiplicatore del terreno scelto\n")
        w("   valore  = quanto conta UNA di queste unità in battaglia\n\n")

        # ── Peso nella legione ──────────────────────────────────────
        somma = sum(r["total"] for r in rows) or 1.0
        costo = sum(r["cost_total"] for r in rows) or 1.0
        w("⚖️  PESO DI OGNI UNITÀ NELLA LEGIONE\n")
        for row in rows:
            quota_f = row["total"] / somma * 100
            quota_c = row["cost_total"] / costo * 100
            resa = "rende più di quanto costa" if quota_f > quota_c + 5 else (
                   "costa più di quanto rende" if quota_c > quota_f + 5 else "in pari")
            w(f"   {row['name'][:19]:<20}{bar(quota_f, 100)} forza {quota_f:5.1f}%  "
              f"costo {quota_c:5.1f}%  → {resa}\n")
        w("\n")

        # ── Forza della legione ─────────────────────────────────────
        att = result["attack"]
        dif = result["defense"]
        w("💪 FORZA DELLA LEGIONE\n")
        w(f"   valore unità (somma)      {result['base_total']:>10.1f}\n")
        w(f"   moltiplicatore totale     {result['total_multiplier']:>10.2f}x\n")
        w(f"      di cui strategia       {att['strategy_factor']:>10.2f}x"
          f"   (quanto la manovra si adatta a queste truppe)\n")
        w(f"      il resto               {result['rest_multiplier']:>10.2f}x"
          f"   (contesto meteo/stato + sinergia fra unità uguali)\n")
        w("   " + "·" * 60 + "\n")
        w(f"   FORZA IN ATTACCO          {att['strength']:>10.1f}\n")
        w(f"   forza in difesa           {dif['strength']:>10.1f}"
          f"   (su cella fort. liv.{BENCHMARK_FORT_LEVEL} con {BENCHMARK_GARRISON} presidi)\n")
        w(f"   di cui bonus difensivo    {dif['defense_bonus']:>10.1f}\n\n")

        # ── Assalto al castello ─────────────────────────────────────
        castle = result["castle"]
        w("🏰 ASSALTO AL CASTELLO\n")
        w(f"   forza d'assedio           {castle['attacker']:>10.1f}\n")
        w(f"   difesa castello           {castle['defense']:>10.1f}"
          f"   ({BENCHMARK_CASTLE_GARRISON} presidi, nessuna fortificazione)\n")
        w(f"   danno per assalto         {castle['damage']:>10} HP\n")
        w(f"   assalti per abbatterlo    {castle['assaults']:>10}"
          f"   (castello da {castle['hp']} HP)\n\n")

        # ── Confronto condizioni ────────────────────────────────────
        conditions = result["conditions"]
        massimo = max(c["strength"] for c in conditions) or 1.0
        rif = next((c["strength"] for c in conditions if c["current"]), massimo)
        rif_t = next((c["troops"] for c in conditions if c["current"]), 1.0) or 1.0
        w("🌤️  LA STESSA LEGIONE IN OGNI CONDIZIONE (terreno fermo)\n")
        w(f"   {'condizione':<18}{'':<22} {'truppe':>9} {'forza':>10}\n")
        for cond in conditions:
            delta = (cond["strength"] / rif - 1.0) * 100 if rif else 0.0
            delta_t = (cond["troops"] / rif_t - 1.0) * 100
            marker = "  ←  scelta" if cond["current"] else ""
            w(f"   {cond['label']:<18}{bar(cond['strength'], massimo)} "
              f"{delta_t:+7.1f}% {cond['strength']:8.1f} {delta:+6.1f}%{marker}\n")
        w("\n   truppe = valore delle sole unità (il meteo sulle truppe)\n")
        w("   forza  = valore della legione, strategia e contesto compresi\n")
        w("   se le due colonne vanno in direzioni opposte è la strategia che compensa\n\n")

        # ── Confronto terreni ───────────────────────────────────────
        terrains = result["terrains"]
        massimo_t = max(t["strength"] for t in terrains) or 1.0
        rif_terr = next((t["strength"] for t in terrains if t["current"]), massimo_t)
        rif_terr_t = next((t["troops"] for t in terrains if t["current"]), 1.0) or 1.0
        w("🌍 LA STESSA LEGIONE SU OGNI TERRENO (condizioni ferme)\n")
        w(f"   {'terreno':<18}{'':<22} {'truppe':>9} {'forza':>10}\n")
        for terr in terrains:
            delta = (terr["strength"] / rif_terr - 1.0) * 100 if rif_terr else 0.0
            delta_t = (terr["troops"] / rif_terr_t - 1.0) * 100
            marker = "  ←  scelto" if terr["current"] else ""
            w(f"   {terr['terrain']:<18}{bar(terr['strength'], massimo_t)} "
              f"{delta_t:+7.1f}% {terr['strength']:8.1f} {delta:+6.1f}%{marker}\n")
        w("\n")

        # ── Strategie ───────────────────────────────────────────────
        w("🏆 STRATEGIE PER QUESTA COMPOSIZIONE\n")
        for i, strat in enumerate(result["ranking"][:5], 1):
            w(f"   {i}. {strat['name']:<28}{strat['compatibility']:>6.1f}%"
              f"   (distanza {strat['distance']:.4f})\n")
        w("\n")

        # ── Avvisi ──────────────────────────────────────────────────
        w("🔎 AVVISI DI BILANCIAMENTO\n")
        for warning in result["warnings"]:
            w(f"   ! {warning}\n")
        w("\n" + THIN + "\n\n")


# ══════════════════════════════════════════════════════════════════
# INPUT INTERATTIVO
# ══════════════════════════════════════════════════════════════════

def ask_int(prompt: str, low: int, high: int, default: Optional[int] = None) -> int:
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("   ❌ inserisci un numero")
            continue
        if low <= value <= high:
            return value
        print(f"   ❌ inserisci un numero tra {low} e {high}")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = " (S/n): " if default else " (s/N): "
    while True:
        raw = input(prompt + suffix).strip().lower()
        if not raw:
            return default
        if raw in ("s", "si", "sì", "y"):
            return True
        if raw in ("n", "no"):
            return False
        print("   ❌ rispondi s oppure n")


def ask_composition(units: List[Dict[str, Any]]) -> Dict[str, int]:
    """Chiede quali truppe e quante, nel formato numero:quantità."""
    print("\n🗡️  TRUPPE DISPONIBILI")
    for i, unit in enumerate(units, 1):
        print(f"   [{i:>2}] {unit['name']:<22} {unit.get('cost_grux', 0):>3} grux")

    while True:
        raw = input("\n👉 Cosa schieri? numero:quantità separati da virgola (es: 1:4,6:2): ").strip()
        composition: Dict[str, int] = {}
        valido = True

        for pezzo in raw.split(","):
            pezzo = pezzo.strip()
            if not pezzo:
                continue
            numero, _, quantita = pezzo.partition(":")
            try:
                indice = int(numero)
                count = int(quantita) if quantita.strip() else 1
            except ValueError:
                print(f"   ❌ non capisco '{pezzo}' — usa il formato numero:quantità")
                valido = False
                break
            if not (1 <= indice <= len(units)):
                print(f"   ❌ non esiste l'unità numero {indice}")
                valido = False
                break
            if not (1 <= count <= 100):
                print("   ❌ la quantità deve stare tra 1 e 100")
                valido = False
                break
            unit_id = units[indice - 1]["id"]
            composition[unit_id] = composition.get(unit_id, 0) + count

        if valido and composition:
            righe = ", ".join(
                f"{count}x {next(u['name'] for u in units if u['id'] == uid)}"
                for uid, count in composition.items()
            )
            print(f"   ✅ {righe}")
            return composition
        if valido:
            print("   ❌ non hai schierato niente")


def ask_choice(title: str, options: List[str], default_index: int = 0) -> str:
    print(f"\n{title}")
    for i, option in enumerate(options, 1):
        marcatore = "  (invio)" if i - 1 == default_index else ""
        print(f"   [{i}] {option}{marcatore}")
    scelta = ask_int("\n👉 Numero: ", 1, len(options), default=default_index + 1)
    print(f"   ✅ {options[scelta - 1]}")
    return options[scelta - 1]


def random_setup(data: Dict[str, Any], units_wanted: Optional[int] = None) -> Dict[str, Any]:
    """Schieramento e condizioni completamente sorteggiati."""
    units = data["units"]
    tipi = random.randint(1, min(RANDOM_TYPES_MAX, len(units)))
    scelte = random.sample(units, tipi)

    totale = units_wanted or random.randint(RANDOM_UNITS_MIN, RANDOM_UNITS_MAX)
    totale = max(totale, tipi)                      # almeno una per tipo

    # Distribuzione casuale del totale fra i tipi estratti, senza lasciarne
    # fuori nessuno: prima una a testa, poi il resto a caso.
    composition = {unit["id"]: 1 for unit in scelte}
    for _ in range(totale - tipi):
        scelta = random.choice(scelte)["id"]
        composition[scelta] += 1

    return {
        "composition": composition,
        "terrain": random.choice(list(data["terrain"].keys())),
        "cycle": random.choice(list(wc.CYCLES)),
        "weather": random.choice(list(wc.WEATHERS)),
        "weather_origin": "sorteggiate",
        "status": random.choice(list(tc.ALL_STATUSES)),
    }


def ask_setup(data: Dict[str, Any]) -> Dict[str, Any]:
    units = data["units"]
    composition = ask_composition(units)
    terrain = ask_choice("🌍 TERRENO", list(data["terrain"].keys()))

    # Meteo: sorteggiato oppure scelto asse per asse.
    if ask_yes_no("\n🎲 Meteo casuale?", default=False):
        cycle = random.choice(list(wc.CYCLES))
        weather = random.choice(list(wc.WEATHERS))
        origin = "sorteggiate"
        print(f"   🎲 uscito: {wc.combined_key(cycle, weather)}")
    else:
        cycle = ask_choice("🕒 CICLO GIORNO/NOTTE", list(wc.CYCLES))
        weather = ask_choice("🌤️  METEO", list(wc.WEATHERS))
        origin = "scelte a mano"

    status = ask_choice("💪 STATO DELLE TRUPPE", list(tc.ALL_STATUSES))

    return {
        "composition": composition,
        "terrain": terrain,
        "cycle": cycle,
        "weather": weather,
        "weather_origin": origin,
        "status": status,
    }


# ══════════════════════════════════════════════════════════════════
# ESECUZIONE
# ══════════════════════════════════════════════════════════════════

def run_test(session: Any, setup: Dict[str, Any], strategy_id: Optional[str] = None) -> Dict[str, Any]:
    """Misura tutto e restituisce il risultato pronto per il report."""
    data = session.data
    composition = setup["composition"]
    terrain = setup["terrain"]
    unit_ids = [uid for uid, count in composition.items() for _ in range(count)]

    set_conditions(session, setup["cycle"], setup["weather"])

    # Vettore della composizione, come lo vede l'engine.
    army = aggregate_army(unit_ids, data["units"])
    modified, critical = apply_modifiers(
        army_vector=army,
        terrain_name=terrain,
        weather_name=session.weather,
        troop_status_name=setup["status"],
        modifiers_data=data,
    )

    # Il ranking usa il meteo semplice: la tabella delle affinità unità-ambiente
    # conosce Sereno/Pioggia/Nebbia, non le chiavi composte con il ciclo.
    ranking = compute_ranking(
        army_vector=modified,
        strategies_list=data["strategies"],
        unit_ids=unit_ids,
        terrain_name=terrain,
        weather_name=setup["weather"],
        affinities_data=data.get("unit_affinities", {}),
    )

    if strategy_id is None:
        strategy_id = ranking[0]["id"]
        strategy_origin = "la migliore per questa composizione"
    else:
        strategy_origin = "scelta a mano"
    strategy = next(s for s in data["strategies"] if s["id"] == strategy_id)
    strategy_compat = next(
        (s["compatibility"] for s in ranking if s["id"] == strategy_id), 0.0
    )

    legion = make_legion(composition, setup["status"], strategy_id)
    rows = unit_rows(session, composition, terrain)

    attack = strength(session, legion, terrain)
    principale = max(rows, key=lambda r: r["total"])["unit_id"]
    defense = strength(session, legion, terrain,
                       cell=benchmark_cell(session, terrain, principale))
    castle = castle_estimate(session, legion)

    conditions = sweep_conditions(session, legion, terrain, (setup["cycle"], setup["weather"]))
    terrains = sweep_terrains(session, legion, terrain)

    # Scomposizione della forza, ricavata SOLO da misure (niente formule
    # ricopiate qui: se il motore cambia, questi numeri cambiano da soli).
    #   forza = valore unità × moltiplicatore totale
    #   moltiplicatore totale = strategia × (contesto + sinergia unità uguali)
    base_total = sum(r["total"] for r in rows)
    strategy_factor = attack["strategy_factor"] or 1.0
    total_multiplier = attack["strength"] / base_total if base_total else 1.0
    rest_multiplier = total_multiplier / strategy_factor if strategy_factor else 1.0

    return {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "setup": {
            **setup,
            "total_units": len(unit_ids),
            "total_cost": sum(r["cost_total"] for r in rows),
            "weather_label": session.weather,
            "strategy_name": strategy["name"],
            "strategy_compat": strategy_compat,
            "strategy_origin": strategy_origin,
        },
        "rows": rows,
        "critical_warnings": critical,
        "attack": attack,
        "defense": defense,
        "castle": castle,
        "conditions": conditions,
        "terrains": terrains,
        "ranking": ranking,
        "base_total": base_total,
        "total_multiplier": total_multiplier,
        "rest_multiplier": rest_multiplier,
        "warnings": balance_warnings(rows, conditions, terrains, attack, attack["strength"]),
    }


def write_summary(path: Path, results: List[Dict[str, Any]]) -> None:
    """Riepilogo su più prove: è qui che si vede quale truppa è tarata male.

    Un singolo test dice come va una composizione in un contesto; la media su
    molti contesti diversi dice quanto rende una truppa in generale, che è la
    domanda del bilanciamento.
    """
    if len(results) < 2:
        return

    per_unit: Dict[str, Dict[str, Any]] = {}
    for result in results:
        for row in result["rows"]:
            acc = per_unit.setdefault(row["unit_id"], {
                "name": row["name"], "cost": row["cost"],
                "tests": 0, "value": 0.0, "per_grux": 0.0, "deployed": 0,
            })
            acc["tests"] += 1
            acc["value"] += row["value"]
            acc["per_grux"] += row["per_grux"]
            acc["deployed"] += row["count"]

    righe = []
    for unit_id, acc in per_unit.items():
        tests = acc["tests"] or 1
        righe.append({
            "name": acc["name"],
            "cost": acc["cost"],
            "tests": acc["tests"],
            "deployed": acc["deployed"],
            "value": acc["value"] / tests,
            "per_grux": acc["per_grux"] / tests,
        })
    righe.sort(key=lambda r: -r["per_grux"])
    media = sum(r["per_grux"] for r in righe) / len(righe) if righe else 0.0

    # Composizioni ordinate per resa: forza in attacco per grux speso.
    compositions = sorted(
        (
            {
                "label": ", ".join(f"{r['count']}x {r['name']}" for r in res["rows"]),
                "context": f"{res['setup']['terrain']} · {res['setup']['weather_label']} · {res['setup']['status']}",
                "strength": res["attack"]["strength"],
                "cost": res["setup"]["total_cost"],
                "per_grux": res["attack"]["strength"] / max(1, res["setup"]["total_cost"]),
            }
            for res in results
        ),
        key=lambda c: -c["per_grux"],
    )

    with open(path, "a", encoding="utf-8") as f:
        w = f.write
        w(SEPARATOR + "\n")
        w(f"RIEPILOGO SU {len(results)} PROVE\n")
        w(SEPARATOR + "\n\n")

        w("🥇 RESA MEDIA DELLE UNITÀ (media su tutti i contesti provati)\n")
        w(f"   {'unità':<20}{'prove':>7}{'schierate':>11}{'valore':>9}"
          f"{'costo':>8}{'val/grux':>10}{'scarto':>9}\n")
        w("   " + "·" * 74 + "\n")
        for row in righe:
            scarto = (row["per_grux"] / media - 1.0) * 100 if media else 0.0
            w(f"   {row['name'][:19]:<20}{row['tests']:>7}{row['deployed']:>11}"
              f"{row['value']:>9.1f}{row['cost']:>8}{row['per_grux']:>10.2f}{scarto:>8.0f}%\n")
        w(f"\n   media generale: {media:.2f} valore per grux\n")
        w("   scarto = quanto quella truppa rende rispetto alla media delle altre.\n")
        w("   Molto sopra = costa poco per quello che fa; molto sotto = non conviene mai.\n\n")

        w("📈 COMPOSIZIONI PIÙ REDDITIZIE (forza in attacco per grux)\n")
        for comp in compositions[:5]:
            w(f"   {comp['per_grux']:>6.2f}  {comp['label'][:44]:<45} {comp['context']}\n")
        if len(compositions) > 5:
            w("\n📉 COMPOSIZIONI MENO REDDITIZIE\n")
            for comp in compositions[-3:]:
                w(f"   {comp['per_grux']:>6.2f}  {comp['label'][:44]:<45} {comp['context']}\n")
        w("\n" + THIN + "\n\n")


def print_summary(result: Dict[str, Any]) -> None:
    setup = result["setup"]
    print("\n" + THIN)
    print(f"   Forza in attacco:  {result['attack']['strength']:.1f}")
    print(f"   Forza in difesa:   {result['defense']['strength']:.1f}")
    print(f"   Costo:             {setup['total_cost']} grux "
          f"({result['attack']['strength'] / max(1, setup['total_cost']):.2f} forza per grux)")
    print(f"   Danno al castello: {result['castle']['damage']} HP "
          f"({result['castle']['assaults']} assalti)")
    print("   Avvisi:")
    for warning in result["warnings"]:
        print(f"      ! {warning}")
    print(THIN)


def guided_run(session: Any, data: Dict[str, Any], output: Path) -> List[Dict[str, Any]]:
    """Una composizione alla volta, decisa da te."""
    results: List[Dict[str, Any]] = []
    while True:
        setup = ask_setup(data)

        strategy_id = None
        if ask_yes_no("\n🏆 Vuoi scegliere la strategia?", default=False):
            nomi = [s["name"] for s in data["strategies"]]
            scelto = ask_choice("🏆 STRATEGIA", nomi)
            strategy_id = next(s["id"] for s in data["strategies"] if s["name"] == scelto)

        print("\n⚙️  Calcolo in corso...")
        result = run_test(session, setup, strategy_id)
        write_report(output, result, append=bool(results))
        results.append(result)
        print_summary(result)
        print(f"\n✅ Report scritto in: {output}")

        if not ask_yes_no("\n🔁 Provare un'altra composizione?", default=False):
            return results


def random_run(session: Any, data: Dict[str, Any], output: Path) -> List[Dict[str, Any]]:
    """Sorteggia tutto e macina prove in serie."""
    print("\n🎲 TUTTO CASUALE")
    quanti = ask_int("\n👉 Quanti test? (invio = 20): ", 1, 500, default=20)
    quante = ask_int(
        f"👉 Quante unità per schieramento? (invio = casuale {RANDOM_UNITS_MIN}-{RANDOM_UNITS_MAX}): ",
        0, 100, default=0,
    )

    print(f"\n⚙️  Eseguo {quanti} test...\n")
    results: List[Dict[str, Any]] = []
    for indice in range(1, quanti + 1):
        setup = random_setup(data, quante or None)
        result = run_test(session, setup)
        write_report(output, result, append=bool(results))
        results.append(result)

        composizione = ", ".join(f"{r['count']}x {r['name']}" for r in result["rows"])
        forza = result["attack"]["strength"]
        costo = max(1, result["setup"]["total_cost"])
        print(f"   [{indice:>3}/{quanti}] {composizione[:42]:<43} "
              f"{setup['terrain'][:8]:<9} {result['setup']['weather_label']:<17} "
              f"{setup['status'][:13]:<14} forza {forza:8.1f}  {forza / costo:5.2f}/grux")
    return results


def print_aggregate(results: List[Dict[str, Any]]) -> None:
    """Classifica a video, la stessa che finisce in coda al file."""
    per_unit: Dict[str, Dict[str, Any]] = {}
    for result in results:
        for row in result["rows"]:
            acc = per_unit.setdefault(row["unit_id"], {"name": row["name"], "tests": 0, "per_grux": 0.0})
            acc["tests"] += 1
            acc["per_grux"] += row["per_grux"]

    righe = sorted(
        ({"name": a["name"], "per_grux": a["per_grux"] / max(1, a["tests"]), "tests": a["tests"]}
         for a in per_unit.values()),
        key=lambda r: -r["per_grux"],
    )
    media = sum(r["per_grux"] for r in righe) / len(righe) if righe else 0.0

    print("\n" + THIN)
    print(f"   RESA MEDIA SU {len(results)} PROVE (valore per grux)")
    for row in righe:
        scarto = (row["per_grux"] / media - 1.0) * 100 if media else 0.0
        prove = "prova" if row["tests"] == 1 else "prove"
        print(f"      {row['name']:<22}{row['per_grux']:>6.2f}   {scarto:+5.0f}% "
              f"rispetto alla media   ({row['tests']} {prove})")
    print(THIN)


def main() -> None:
    print("\n" + SEPARATOR)
    print("⚖️  WAR ADVISOR - BILANCIAMENTO FORZA TRUPPE")
    print(SEPARATOR)
    print("Misura quanto pesano davvero le truppe usando le stesse funzioni")
    print("che girano in partita. Ogni esecuzione scrive un file nuovo in reports/.")

    data = load_data()
    session = build_calculator_session(data)
    output = REPORTS_DIR / f"forza_truppe_{report_stamp()}.txt"

    print("\n🎯 MODALITÀ")
    print("   [1] Guidato — scelgo io truppe, terreno e condizioni  (invio)")
    print("   [2] Tutto casuale — sorteggia tutto e macina N test")
    modalita = ask_int("\n👉 Numero: ", 1, 2, default=1)

    results = guided_run(session, data, output) if modalita == 1 else random_run(session, data, output)

    write_summary(output, results)
    if len(results) > 1:
        print_aggregate(results)

    print(f"\n✅ {len(results)} prove analizzate. Report completo: {output}\n")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n\n⏹  Interrotto.\n")
