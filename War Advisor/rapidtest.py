"""
War Advisor - Rapid Testing System
Sistema di testing rapido per truppe e strategie
Scrive i risultati dei test in un file TXT
"""

import json
import random
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from engine import (
    load_data,
    aggregate_army,
    apply_modifiers,
    compute_ranking,
    get_available_units,
    get_available_terrains,
    get_available_weather,
    get_available_troop_status
)

# File di output per i risultati
OUTPUT_FILE = Path(__file__).parent / "test_results.txt"


def run_test(
    unit_ids: List[str],
    terrain: str,
    weather: Optional[str] = None,
    troop_status: Optional[str] = None,
    append: bool = True
) -> dict:
    """
    Esegue un test di strategia e scrive i risultati nel file TXT.
    
    Args:
        unit_ids: Lista di ID delle unità da testare
        terrain: Nome del terreno
        weather: Condizione meteo (opzionale)
        troop_status: Stato delle truppe/morale (opzionale)
        append: Se True, aggiunge al file. Se False, sovrascrive.
    
    Returns:
        Dizionario con i risultati del test
    """
    # Carica i dati
    DATA = load_data()
    
    # Mappa per ottenere nomi delle unità
    units_map = {unit["id"]: unit["name"] for unit in DATA["units"]}
    
    # Calcola il vettore dell'esercito
    army_profile = aggregate_army(unit_ids, DATA["units"])
    
    # Applica i modificatori
    modified_profile, critical_warnings = apply_modifiers(
        army_vector=army_profile,
        terrain_name=terrain,
        weather_name=weather,
        troop_status_name=troop_status,
        modifiers_data=DATA
    )
    
    # Calcola il ranking delle strategie
    ranking_data = compute_ranking(
        army_vector=modified_profile,
        strategies_list=DATA["strategies"],
        unit_ids=unit_ids,
        terrain_name=terrain,
        weather_name=weather,
        affinities_data=DATA.get("unit_affinities", {})
    )
    
    # Prima strategia suggerita
    top_strategy = ranking_data[0] if ranking_data else None
    
    # Prepara i risultati
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "units": [(uid, units_map.get(uid, uid)) for uid in unit_ids],
        "terrain": terrain,
        "weather": weather,
        "troop_status": troop_status,
        "army_profile": army_profile,
        "modified_profile": modified_profile,
        "critical_warnings": critical_warnings,
        "top_strategy": top_strategy
    }
    
    # Scrivi nel file TXT
    _write_results(result, append)
    
    return result


def _write_results(result: dict, append: bool = True):
    """
    Scrive i risultati del test nel file TXT in formato leggibile.
    """
    mode = "a" if append else "w"
    
    with open(OUTPUT_FILE, mode, encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write(f"TEST RAPIDO - {result['timestamp']}\n")
        f.write("=" * 70 + "\n\n")
        
        # Truppe scelte
        f.write("📋 TRUPPE SCELTE:\n")
        for uid, name in result["units"]:
            f.write(f"   • {name} ({uid})\n")
        f.write("\n")
        
        # Modificatori
        f.write("🌍 MODIFICATORI:\n")
        f.write(f"   Terreno: {result['terrain'] or 'Nessuno'}\n")
        f.write(f"   Clima:   {result['weather'] or 'Nessuno'}\n")
        f.write(f"   Morale:  {result['troop_status'] or 'Nessuno'}\n")
        f.write("\n")
        
        # Warning critici
        if result["critical_warnings"]:
            f.write("⚠️  AVVISI CRITICI:\n")
            for warning in result["critical_warnings"]:
                f.write(f"   ! {warning}\n")
            f.write("\n")
        
        # Profilo esercito modificato
        f.write("📊 PROFILO ESERCITO (dopo modificatori):\n")
        for attr, value in result["modified_profile"].items():
            bar = "█" * int(value * 10) + "░" * (10 - int(value * 10))
            f.write(f"   {attr}: {bar} {value:.2f}\n")
        f.write("\n")
        
        # Prima strategia suggerita
        if result["top_strategy"]:
            strat = result["top_strategy"]
            f.write("🏆 STRATEGIA SUGGERITA:\n")
            f.write(f"   Nome:          {strat['name']}\n")
            f.write(f"   ID:            {strat['id']}\n")
            f.write(f"   Compatibilità: {strat['compatibility']:.1f}%\n")
            f.write(f"   Distanza:      {strat['distance']:.4f}\n")
            f.write(f"   Descrizione:   {strat['description']}\n")
        else:
            f.write("❌ Nessuna strategia trovata\n")
        
        f.write("\n" + "-" * 70 + "\n\n")
    
    print(f"✅ Risultati salvati in: {OUTPUT_FILE}")


def run_batch_tests(tests: List[dict], clear_file: bool = True):
    """
    Esegue una serie di test in batch.
    
    Args:
        tests: Lista di dizionari con parametri del test
               Ogni dict deve avere: unit_ids, terrain
               Opzionali: weather, troop_status
        clear_file: Se True, pulisce il file prima di iniziare
    
    Esempio:
        tests = [
            {"unit_ids": ["infantry_basic"], "terrain": "Pianura", "weather": "Sereno"},
            {"unit_ids": ["cavalry_light"], "terrain": "Foresta", "weather": "Pioggia"},
        ]
        run_batch_tests(tests)
    """
    if clear_file and OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    
    for i, test in enumerate(tests, 1):
        print(f"Esecuzione test {i}/{len(tests)}...")
        run_test(
            unit_ids=test["unit_ids"],
            terrain=test["terrain"],
            weather=test.get("weather"),
            troop_status=test.get("troop_status"),
            append=True
        )
    
    print(f"\n✅ Completati {len(tests)} test. Risultati in: {OUTPUT_FILE}")


def list_available_options():
    """
    Stampa tutte le opzioni disponibili (unità, terreni, meteo, stati truppe).
    Utile per sapere cosa usare nei test.
    """
    DATA = load_data()
    
    print("\n📋 UNITÀ DISPONIBILI:")
    for unit in DATA["units"]:
        print(f"   • {unit['id']}: {unit['name']}")
    
    print("\n🌍 TERRENI DISPONIBILI:")
    for terrain in DATA["terrain"].keys():
        print(f"   • {terrain}")
    
    print("\n🌤️  CONDIZIONI METEO:")
    for weather in DATA["weather"].keys():
        print(f"   • {weather}")
    
    print("\n💪 STATI TRUPPE (MORALE):")
    for status in DATA["troop_status"].keys():
        print(f"   • {status}")
    print()


# ==================== MENU INTERATTIVO ====================

def interactive_menu():
    """
    Menu interattivo per inserire test rapidamente con input numerici.
    """
    DATA = load_data()
    
    # Prepara liste con indici
    units_list = [(i+1, unit["id"], unit["name"]) for i, unit in enumerate(DATA["units"])]
    terrains_list = [(i+1, terrain) for i, terrain in enumerate(DATA["terrain"].keys())]
    weather_list = [(i+1, weather) for i, weather in enumerate(DATA["weather"].keys())]
    status_list = [(i+1, status) for i, status in enumerate(DATA["troop_status"].keys())]
    
    print("\n" + "=" * 60)
    print("🎮 WAR ADVISOR - TESTING RAPIDO INTERATTIVO")
    print("=" * 60)
    
    # Quanti test?
    while True:
        try:
            num_tests = int(input("\n📝 Quanti test vuoi eseguire? "))
            if num_tests > 0:
                break
            print("❌ Inserisci un numero maggiore di 0")
        except ValueError:
            print("❌ Inserisci un numero valido")
    
    tests_results = []
    
    for test_num in range(1, num_tests + 1):
        print(f"\n{'─' * 60}")
        print(f"📋 TEST {test_num}/{num_tests}")
        print("─" * 60)
        
        # === SELEZIONE TRUPPE ===
        print("\n🗡️  SELEZIONA TRUPPE (puoi sceglierne più di una):")
        for idx, uid, name in units_list:
            print(f"   [{idx}] {name}")
        
        selected_units = []
        while True:
            try:
                units_input = input("\n👉 Inserisci numeri separati da virgola (es: 1,3,5): ").strip()
                indices = [int(x.strip()) for x in units_input.split(",")]
                
                for idx in indices:
                    unit = next((u for u in units_list if u[0] == idx), None)
                    if unit:
                        selected_units.append(unit[1])  # Aggiungi l'ID
                    else:
                        print(f"⚠️  Numero {idx} non valido, ignorato")
                
                if selected_units:
                    print(f"✅ Truppe selezionate: {', '.join(selected_units)}")
                    break
                else:
                    print("❌ Seleziona almeno una truppa valida")
            except ValueError:
                print("❌ Formato non valido. Usa numeri separati da virgola (es: 1,2,3)")
        
        # === SELEZIONE TERRENO ===
        print("\n🌍 SELEZIONA TERRENO:")
        for idx, terrain in terrains_list:
            print(f"   [{idx}] {terrain}")
        
        selected_terrain = None
        while True:
            try:
                terrain_input = int(input("\n👉 Inserisci numero: ").strip())
                terrain = next((t for t in terrains_list if t[0] == terrain_input), None)
                if terrain:
                    selected_terrain = terrain[1]
                    print(f"✅ Terreno: {selected_terrain}")
                    break
                else:
                    print("❌ Numero non valido")
            except ValueError:
                print("❌ Inserisci un numero valido")
        
        # === SELEZIONE METEO ===
        print("\n🌤️  SELEZIONA CONDIZIONE METEO (0 = nessuna):")
        print("   [0] Nessuna")
        for idx, weather in weather_list:
            print(f"   [{idx}] {weather}")
        
        selected_weather = None
        while True:
            try:
                weather_input = int(input("\n👉 Inserisci numero: ").strip())
                if weather_input == 0:
                    print("✅ Meteo: Nessuno")
                    break
                weather = next((w for w in weather_list if w[0] == weather_input), None)
                if weather:
                    selected_weather = weather[1]
                    print(f"✅ Meteo: {selected_weather}")
                    break
                else:
                    print("❌ Numero non valido")
            except ValueError:
                print("❌ Inserisci un numero valido")
        
        # === SELEZIONE STATO TRUPPE/MORALE ===
        print("\n💪 SELEZIONA STATO TRUPPE/MORALE (0 = nessuno):")
        print("   [0] Nessuno")
        for idx, status in status_list:
            print(f"   [{idx}] {status}")
        
        selected_status = None
        while True:
            try:
                status_input = int(input("\n👉 Inserisci numero: ").strip())
                if status_input == 0:
                    print("✅ Stato truppe: Nessuno")
                    break
                status = next((s for s in status_list if s[0] == status_input), None)
                if status:
                    selected_status = status[1]
                    print(f"✅ Stato truppe: {selected_status}")
                    break
                else:
                    print("❌ Numero non valido")
            except ValueError:
                print("❌ Inserisci un numero valido")
        
        # Esegui il test
        print(f"\n⚙️  Esecuzione test {test_num}...")
        result = run_test(
            unit_ids=selected_units,
            terrain=selected_terrain,
            weather=selected_weather,
            troop_status=selected_status,
            append=(test_num > 1)  # Primo test sovrascrive, gli altri aggiungono
        )
        tests_results.append(result)
        
        # Mostra risultato rapido
        if result["top_strategy"]:
            print(f"\n🏆 STRATEGIA: {result['top_strategy']['name']} ({result['top_strategy']['compatibility']:.1f}%)")
    
    # Riepilogo finale
    print("\n" + "=" * 60)
    print("📊 RIEPILOGO TEST COMPLETATI")
    print("=" * 60)
    
    for i, res in enumerate(tests_results, 1):
        units_names = ", ".join([name for _, name in res["units"]])
        strat_name = res["top_strategy"]["name"] if res["top_strategy"] else "N/A"
        compat = res["top_strategy"]["compatibility"] if res["top_strategy"] else 0
        print(f"\n   Test {i}:")
        print(f"      Truppe:    {units_names}")
        print(f"      Terreno:   {res['terrain']}")
        print(f"      Meteo:     {res['weather'] or 'Nessuno'}")
        print(f"      Morale:    {res['troop_status'] or 'Nessuno'}")
        print(f"      → Strategia: {strat_name} ({compat:.1f}%)")
    
    print(f"\n✅ Tutti i risultati salvati in: {OUTPUT_FILE}")


# ==================== MAIN ====================

if __name__ == "__main__":
    print("\n🎯 WAR ADVISOR - RAPID TEST")
    print("─" * 40)
    print("   [1] Test interattivo (inserisci dati)")
    print("   [2] Test automatico randomico")
    print("   [3] Mostra opzioni disponibili")
    print("─" * 40)
    
    choice = input("\n👉 Scegli modalità (1/2/3): ").strip()
    
    if choice == "1":
        interactive_menu()
    
    elif choice == "2":
        # Test automatico randomico
        DATA = load_data()
        
        units_ids = [unit["id"] for unit in DATA["units"]]
        terrains = list(DATA["terrain"].keys())
        weathers = list(DATA["weather"].keys())
        statuses = list(DATA["troop_status"].keys())
        
        print("\n🎲 TEST AUTOMATICO RANDOMICO")
        print("─" * 40)
        
        # Quanti test?
        while True:
            try:
                num_tests = int(input("\n📝 Quanti test vuoi eseguire? "))
                if num_tests > 0:
                    break
                print("❌ Inserisci un numero maggiore di 0")
            except ValueError:
                print("❌ Inserisci un numero valido")
        
        # Quante truppe per test?
        max_units = len(units_ids)
        while True:
            try:
                num_units = int(input(f"🗡️  Quante truppe per test? (1-{max_units}): "))
                if 1 <= num_units <= max_units:
                    break
                print(f"❌ Inserisci un numero tra 1 e {max_units}")
            except ValueError:
                print("❌ Inserisci un numero valido")
        
        # Includere meteo random?
        include_weather = input("🌤️  Includere meteo random? (s/n): ").strip().lower() == "s"
        
        # Includere stato truppe random?
        include_status = input("💪 Includere stato truppe random? (s/n): ").strip().lower() == "s"
        
        print(f"\n⚙️  Esecuzione {num_tests} test randomici...")
        print("─" * 40)
        
        tests_results = []
        
        for i in range(1, num_tests + 1):
            # Selezione random
            random_units = random.sample(units_ids, num_units)
            random_terrain = random.choice(terrains)
            random_weather = random.choice(weathers) if include_weather else None
            random_status = random.choice(statuses) if include_status else None
            
            result = run_test(
                unit_ids=random_units,
                terrain=random_terrain,
                weather=random_weather,
                troop_status=random_status,
                append=(i > 1)
            )
            tests_results.append(result)
            
            # Output rapido
            units_names = ", ".join([name for _, name in result["units"]])
            strat_name = result["top_strategy"]["name"] if result["top_strategy"] else "N/A"
            compat = result["top_strategy"]["compatibility"] if result["top_strategy"] else 0
            print(f"\n   Test {i}: {units_names}")
            print(f"      🌍 {random_terrain} | 🌤️ {random_weather or '-'} | 💪 {random_status or '-'}")
            print(f"      🏆 {strat_name} ({compat:.1f}%)")
        
        # Riepilogo finale
        print("\n" + "=" * 60)
        print("📊 RIEPILOGO TEST RANDOMICI")
        print("=" * 60)
        
        # Statistiche strategie
        strategy_counts = {}
        for res in tests_results:
            if res["top_strategy"]:
                strat = res["top_strategy"]["name"]
                strategy_counts[strat] = strategy_counts.get(strat, 0) + 1
        
        print("\n🏆 Strategie suggerite:")
        for strat, count in sorted(strategy_counts.items(), key=lambda x: -x[1]):
            percentage = (count / num_tests) * 100
            bar = "█" * int(percentage / 5) + "░" * (20 - int(percentage / 5))
            print(f"   {strat}: {bar} {count}x ({percentage:.0f}%)")
        
        print(f"\n✅ Tutti i risultati salvati in: {OUTPUT_FILE}")
    
    elif choice == "3":
        list_available_options()
    
    else:
        print("❌ Scelta non valida")
