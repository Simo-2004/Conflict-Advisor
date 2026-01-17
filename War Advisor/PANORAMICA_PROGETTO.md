# WAR ADVISOR - Conflict Strategy Recommender System
**Sistema di Raccomandazione Strategica per Wargame Tattici**

---

## Obiettivo del Progetto

**War Advisor** è un sistema intelligente di raccomandazione strategica che analizza la composizione di un esercito e le condizioni ambientali per suggerire la strategia militare ottimale da adottare in battaglia.

Il sistema utilizza **algoritmi di Machine Learning** (distanza euclidea in spazi vettoriali multi-dimensionali) combinati con un **sistema esperto basato su regole** per valutare la compatibilità tra composizione delle truppe e tattiche disponibili.

---

## Architettura del Sistema

### **Stack Tecnologico**
- **Backend**: Python 3 con FastAPI (API REST)
- **Frontend**: HTML5, CSS3, JavaScript + Chart.js
- **Engine**: Algoritmo proprietario di distanza semantica euclidea
- **Packaging**: PyInstaller per distribuzione standalone (.exe)
- **Server**: Uvicorn (Server)

### **Struttura del Progetto**
```
War Advisor/
├── engine.py              # Motore di raccomandazione (core logic)
├── main.py                # API FastAPI (endpoints REST)
├── run_app.py             # Launcher eseguibile (avvio automatico)
├── index.html             # Frontend web interattivo
├── WarAdvisor.spec        # Configurazione PyInstaller
├── requirements.txt       # Dipendenze Python
└── data/                  # Database JSON
    ├── units.json         # Database unità militari
    ├── strategies.json    # Database strategie tattiche
    ├── modifiers.json     # Modificatori ambientali
    └── unit_affinities.json  # Affinità unità-ambiente
```

---

## Algoritmo di Raccomandazione

### **Fase 1: Aggregazione Esercito**
- Input: Lista di unità militari selezionate dall'utente
- Output: **Vettore 8-dimensionale** rappresentante l'esercito

Ogni unità è codificata con 8 attributi normalizzati [0.0 - 1.0]:
1. **U1_attack**: Potenza offensiva
2. **U2_defense**: Capacità difensiva
3. **U3_mobility**: Mobilità e velocità
4. **U4_stealth**: Furtività e capacità di manovra occulta
5. **U5_discipline**: Coesione e morale delle truppe
6. **U6_terrain_adapt**: Adattabilità al terreno
7. **U7_range_power**: Potenza d'attacco a distanza
8. **U8_support**: Capacità di supporto logistico/tattico

**Formula di aggregazione**: Media aritmetica degli attributi delle unità selezionate.

```python
army_vector[attributo] = Σ(unità[attributo]) / numero_unità
```

---

### **Fase 2: Applicazione Modificatori Ambientali**

Il vettore dell'esercito viene modificato in base a:
- **Terreno** (Pianura, Foresta, Montagna, Fiume, Palude)
- **Meteo** (Sereno, Pioggia, Nebbia, Notte)
- **Stato Truppe** (Fresche, Stanche, Demoralizzate, Veterane)

#### **Sistema CRITICAL**
Se un modificatore è marcato come `"CRITICAL"`:
- Se `valore_attributo < 0.5` → **Penalità massiccia** (×0.5)
- Se `valore_attributo ≥ 0.5` → **Nessun malus**

Esempio: Montagna richiede `U6_terrain_adapt CRITICAL`
- Esercito con terrain_adapt = 0.3 → Penalità del 50%
- Esercito con terrain_adapt = 0.7 → Nessuna penalità

**Clamping**: Tutti i valori vengono mantenuti nel range [0.0, 1.0] dopo modifiche.

---

### **Fase 3: Sistema di Affinità Unità-Ambiente (Bidirezionale)**

Meccanismo avanzato che modella le **relazioni naturali** tra unità e condizioni ambientali:

- **Affinità > 0.5** → **BONUS** (riduce distanza = migliora compatibilità)
- **Affinità = 0.5** → **Neutro** (nessun effetto)
- **Affinità < 0.5** → **MALUS** (aumenta distanza = peggiora compatibilità)

**Esempio Pratico - Assassini**:
```json
Foresta + Notte:
  - terrain_affinity: 1.0 (bonus massimo)
  - weather_affinity: 1.0 (bonus massimo)
  → Strategia "Imboscata" fortemente favorita

Pianura + Sereno:
  - terrain_affinity: 0.1 (malus forte)
  - weather_affinity: 0.15 (malus forte)
  → Strategia "Imboscata" penalizzata
```

Formula di adjustment:
```python
adjustment = (0.5 - avg_affinity) × 2 × max_adjustment
```

---

### **Fase 4: Calcolo Distanza Euclidea**

Per ogni strategia disponibile, si calcola la **distanza semantica** tra:
- **Vettore esercito modificato** (output Fase 2)
- **Vettore ideale della strategia** (profilo ottimale)

**Formula**:
```
Distance = √(Σ(Army_i - Strategy_i)²)
```

**Interpretazione**:
- **Distanza bassa** → Strategia molto compatibile
- **Distanza alta** → Strategia poco adatta

La distanza viene poi **aggiustata** dal sistema di affinità (Fase 3).

---

### **Fase 5: Ranking e Output**

Le strategie vengono ordinate per **distanza crescente** (migliore = distanza minore).

Output finale include:
- **Ranking completo** di tutte le strategie
- **Percentuale di compatibilità** per ogni strategia
- **Warning CRITICAL** se condizioni non soddisfatte
- **Visualizzazione radar chart** del profilo esercito vs strategia consigliata

---

## Database Strutturato (JSON)

### **units.json** - 9 Unità Militari
Esempi:
- **Fanteria Pesante**: Alta difesa/attacco, bassa mobilità
- **Cavalleria Leggera**: Altissima mobilità, bassa difesa
- **Arcieri**: Massimo range_power, media furtività
- **Assassini**: Furtività estrema, bassa difesa

### **strategies.json** - 7 Strategie Tattiche
- **Assalto Frontale**: Attacco diretto e massiccio
- **Imboscata**: Sorpresa da posizioni nascoste
- **Difesa in Profondità**: Resistenza passiva
- **Manovra sui Fianchi**: Aggiramento rapido
- **Guerriglia**: Hit-and-run in terreno complesso
- **Assedio**: Logistica e potenza d'attacco a distanza
- **Ricognizione**: Mobilità e intelligence

### **modifiers.json** - Modificatori Ambientali
- **5 terreni**: Pianura, Foresta, Montagna, Fiume, Palude
- **4 condizioni meteo**: Sereno, Pioggia, Nebbia, Notte
- **4 stati truppe**: Fresche, Stanche, Demoralizzate, Veterane

### **unit_affinities.json** - Mappatura Affinità
Sistema esperto che codifica relazioni naturali (es. Assassini + Foresta = forte bonus).

---

## API REST (FastAPI)

### **Endpoint 1: GET /config**
Ritorna configurazione completa per popolare il frontend:
- Lista unità disponibili con attributi
- Lista terreni
- Lista condizioni meteo
- Lista stati truppe

### **Endpoint 2: POST /calculate**
Esegue il calcolo della strategia ottimale.

**Input**:
```json
{
  "units": ["heavy_infantry", "archers"],
  "terrain": "Foresta",
  "weather": "Notte",
  "troop_status": "Fresche"
}
```

**Output**:
```json
{
  "army_profile": { /* vettore originale */ },
  "modified_profile": { /* vettore modificato */ },
  "critical_warnings": [ /* warning CRITICAL */ ],
  "ranking": [ /* lista strategie ordinate */ ],
  "top_strategy": {
    "name": "Imboscata",
    "compatibility": 87.5,
    "distance": 0.45
  }
}
```

### **Endpoint 3: GET /**
Serve il frontend HTML (index.html) automaticamente.

---

## Frontend Web Interattivo

### **Funzionalità**
1. **Selezione multi-scelta** delle unità (dropdown)
2. **Configurazione ambiente** (terreno, meteo, stato truppe)
3. **Calcolo in tempo reale** (click su "Calcola Strategia")
4. **Visualizzazione risultati**:
   - Tabella ranking con compatibilità percentuale
   - **Radar chart** (Chart.js) che confronta:
     - Profilo esercito standard (rosso)
     - Profilo esercito modificato (blu)
     - Profilo strategia consigliata (verde)
   - Card dettagliata strategia, principale e secondaria
   - Sconsiglia la strategia con distanza semantica più alta (la peggiore)
   - Warning CRITICAL evidenziati

---

## Distribuzione (.exe Standalone)

### **PyInstaller Configuration**
Il file `WarAdvisor.spec` configura:
- **Modalità --onefile**: Un singolo eseguibile autonomo
- **Inclusione dati**: HTML, JSON, moduli Python
- **Hidden imports**: FastAPI, Uvicorn, Pydantic
- **Ottimizzazione UPX**: Compressione eseguibile

### **Launcher (run_app.py)**
Sistema intelligente di avvio:
1. **Rilevamento ambiente**: Rileva se eseguito come .exe o script
2. **Configurazione path**: Gestisce `sys._MEIPASS` per PyInstaller
3. **Thread browser**: Apre automaticamente il browser dopo 1.5s
4. **Server FastAPI**: Avvia Uvicorn su `http://127.0.0.1:8000`
5. **Log user-friendly**: Output pulito per utente finale

### **Deployment**
- **Un solo file**: `WarAdvisor.exe` (~10 - 30 MB)
- **Zero dipendenze**: Non richiede Python installato
- **Portabile**: Eseguibile su qualsiasi Windows 10/11 (64-bit)
- **Plug & Play**: Doppio click → browser si apre automaticamente

---

## Caso d'Uso Esempio (potrebbe contenere imprecisioni)

**Scenario**: Attacco notturno in foresta con truppe fresche

**Input Utente**:
- **Unità**: Assassini, Arcieri
- **Terreno**: Foresta
- **Meteo**: Notte
- **Stato**: Fresche

**Elaborazione**:
1. **Aggregazione**: Media degli attributi delle 5 unità
2. **Modificatori**:
   - Foresta: +30% U4_stealth, -20% U3_mobility
   - Notte: +50% U4_stealth, U5_discipline CRITICAL check
   - Fresche: +10% a tutti gli attributi
3. **Affinità**: 
   - Assassini + Foresta + Notte = bonus massimo verso "Imboscata"
4. **Ranking**: "Imboscata" emerge come strategia TOP
5. **Visualizzazione**: Radar chart mostra sovrapposizione quasi perfetta

**Output**: 
```
Strategia Consigliata: IMBOSCATA (Compatibilità 92.3%)
Descrizione: Attacco a sorpresa da posizioni nascoste
Distanza Euclidea: 0.28
```

---

## Innovazioni Tecniche

### **1. Distanza Semantica Vettoriale**
- Applicazione di algoritmi ML (distanza euclidea) a contesto non tradizionale (strategia militare)
- Spazio vettoriale 8-dimensionale normalizzato

### **2. Sistema CRITICAL Ibrido**
- Combina logica dinamica con regole hard-coded
- Penalità non lineari per violazione constraint critici

### **3. Affinità Bidirezionale**
- Modellazione simmetrica bonus/malus
- Pesi personalizzati per unità (terrain_weight, weather_weight)

### **4. Frontend-Backend Decoupling**
- API REST completamente stateless
- Frontend può essere sostituito senza modificare logica

### **5. Packaging Intelligente**
- Auto-rilevamento ambiente (exe vs script)
- Gestione automatica percorsi relativi/assoluti
- Zero configurazione utente finale

---


## Requisiti Sistema

### **Per Sviluppo**:
- Python 3.8+
- Dipendenze: `pip install -r requirements.txt`
- PyInstaller per compilazione

### **Per Esecuzione (.exe)**:
- **Solo** Windows 10/11 (64-bit)
- **Nessuna** dipendenza aggiuntiva

---

## Comandi Principali

```powershell
# Installazione dipendenze
pip install -r requirements.txt

# Esecuzione sviluppo
python run_app.py

# Compilazione eseguibile
pyinstaller WarAdvisor.spec --clean

# Eseguibile produzione
.\dist\WarAdvisor.exe

# Mini-Framework per il testing veloce e automatico
python rapidtest.py
```

---

## Conclusioni

**War Advisor** rappresenta un esempio pratico di come algoritmi di Machine Learning e sistemi esperti possano essere combinati per creare un **decision support system** efficace in domini complessi come la strategia militare tattica.

---

**Autore**: [Simone Filippone]  
**Data**: Gennaio 2026  
**Versione**: 1.0.0  
**Licenza**: [MIT license]
