"""
War Advisor - Mercato Nero

Il banco che si apre quando l'abilità omonima è sbloccata: blocchi di truppe
già equipaggiate a prezzo di saldo, disponibili per pochi turni e in copia
unica. Chi arriva tardi trova il posto vuoto.

Cosa lo rende diverso dal reclutamento normale:

  * si compra a blocchi (2-6 unità in un colpo), non una alla volta;
  * lo sconto è vero, dal 18% al 45% sul listino;
  * non passa dal cooldown di reclutamento — è il vero motivo per cui uno
    ci va, e il motivo per cui l'abilità costa cara;
  * l'offerta scade. Il banco cambia merce ogni pochi turni e quello che
    c'era prima non torna.

Lo stato vive nella sessione (`session.black_market[entity]`) e viene
aggiornato una volta per turno. Se l'abilità non è sbloccata il banco resta
chiuso e non genera nulla: nessun costo, nessun rumore nel log.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

#: Quante offerte tiene il banco insieme.
OFFER_SLOTS = 3

#: Ogni quanti turni il merciaio cambia la merce.
REFRESH_EVERY_TURNS = 6

#: Durata di una singola offerta, estremi compresi. Sotto il refresh apposta:
#: qualche buco fra un giro e l'altro è quello che rende l'offerta "del momento".
OFFER_LIFETIME_RANGE = (3, 6)

#: Quante unità in un blocco.
QUANTITY_RANGE = (2, 5)

#: Sconto minimo e massimo sul listino.
DISCOUNT_RANGE = (0.18, 0.38)

#: Ogni tanto passa l'affare grosso: sconto più alto ma vita corta.
STEAL_CHANCE = 0.22
STEAL_DISCOUNT_RANGE = (0.40, 0.48)
STEAL_LIFETIME = 2

#: Il contorno. Non tocca i numeri, serve al banco per avere una voce.
FLAVORS: Tuple[str, ...] = (
    "Caduto da un carro. Un carro molto grosso.",
    "Non chiedere di chi era. Non chiederlo proprio.",
    "Contratto scaduto, uomini rimasti. Capita.",
    "Ex guardie di un conte che non paga più nessuno.",
    "Merce ferma in dogana da tre stagioni. Adesso non lo è più.",
    "Il precedente proprietario ha smesso di avere opinioni.",
    "Roba pulita. Pulita da poco, ma pulita.",
    "Disertori con l'equipaggiamento ancora addosso.",
    "Sono in regola. I documenti pure, li ho fatti stamattina.",
    "Prezzo così per te. Domani è un altro prezzo.",
)

SOURCES: Tuple[str, ...] = (
    "provenienza incerta",
    "senza timbro",
    "fuori registro",
    "merce sciolta",
    "partita irregolare",
)


@dataclass
class MarketOffer:
    """Un blocco di truppe in vendita al banco."""

    offer_id: str
    unit_id: str
    unit_name: str
    quantity: int
    unit_price: int
    list_price: int
    total_price: int
    list_total: int
    discount_pct: int
    created_turn: int
    expires_turn: int
    flavor: str
    source: str
    sold: bool = False

    def is_expired(self, turn: int) -> bool:
        return turn > self.expires_turn

    def is_available(self, turn: int) -> bool:
        return not self.sold and not self.is_expired(turn)

    def to_dict(self, turn: int) -> Dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "unit_id": self.unit_id,
            "unit_name": self.unit_name,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "list_price": self.list_price,
            "total_price": self.total_price,
            "list_total": self.list_total,
            "saving": max(0, self.list_total - self.total_price),
            "discount_pct": self.discount_pct,
            "expires_turn": self.expires_turn,
            "turns_left": max(0, self.expires_turn - turn + 1),
            "flavor": self.flavor,
            "source": self.source,
            "sold": self.sold,
            "expired": self.is_expired(turn),
            "available": self.is_available(turn),
        }


@dataclass
class BlackMarketState:
    """Il banco di un'entità: merce esposta e quando cambia."""

    offers: List[MarketOffer] = field(default_factory=list)
    next_refresh_turn: int = 0
    opened: bool = False
    purchases: int = 0
    units_bought: int = 0
    grux_spent: int = 0
    grux_saved: int = 0
    _counter: int = 0

    # ── ciclo di vita ────────────────────────────────────────────

    def tick(
        self,
        turn: int,
        unit_costs: Dict[str, int],
        units_map: Dict[str, Dict[str, Any]],
        rng: random.Random,
    ) -> Optional[str]:
        """Aggiorna il banco per questo turno.

        Ritorna una riga di log quando la merce cambia, altrimenti None: il
        cambio di offerte è un evento che il giocatore deve poter vedere
        scorrere nel registro senza tenere aperta la finestra.
        """
        if not self.opened:
            self.opened = True
            self.next_refresh_turn = turn

        # Il banco cambia merce SOLO quando è ora, mai perché si è svuotato.
        #
        # Prima si rimetteva in moto anche quando non restava niente di
        # disponibile, e questo apriva un rubinetto infinito: chi poteva
        # permettersi di comprare tutte e tre le offerte se le ritrovava
        # rifornite il turno dopo. Misurato a grux illimitati faceva 1058
        # truppe in 100 turni, venti volte il reclutamento normale.
        # Se hai svuotato il banco aspetti il giro come tutti.
        if turn < self.next_refresh_turn:
            return None

        self._restock(turn, unit_costs, units_map, rng)
        best = max((o.discount_pct for o in self.offers), default=0)
        return (
            f"[Turno {turn}] 🕯 Il Mercato Nero cambia banco: {len(self.offers)} offerte "
            f"(fino a -{best}%)"
        )

    def _restock(
        self,
        turn: int,
        unit_costs: Dict[str, int],
        units_map: Dict[str, Dict[str, Any]],
        rng: random.Random,
    ) -> None:
        candidates = [uid for uid in unit_costs if uid in units_map]
        if not candidates:
            self.offers = []
            return

        rng.shuffle(candidates)
        picked = candidates[:OFFER_SLOTS]
        self.offers = [
            self._make_offer(unit_id, turn, unit_costs, units_map, rng) for unit_id in picked
        ]
        self.next_refresh_turn = turn + REFRESH_EVERY_TURNS

    def _make_offer(
        self,
        unit_id: str,
        turn: int,
        unit_costs: Dict[str, int],
        units_map: Dict[str, Dict[str, Any]],
        rng: random.Random,
    ) -> MarketOffer:
        self._counter += 1
        list_price = int(unit_costs[unit_id])
        quantity = rng.randint(*QUANTITY_RANGE)

        steal = rng.random() < STEAL_CHANCE
        if steal:
            discount = rng.uniform(*STEAL_DISCOUNT_RANGE)
            lifetime = STEAL_LIFETIME
        else:
            discount = rng.uniform(*DISCOUNT_RANGE)
            lifetime = rng.randint(*OFFER_LIFETIME_RANGE)

        unit_price = max(5, int(round(list_price * (1.0 - discount) / 5.0)) * 5)
        # Lo sconto mostrato è quello che si paga davvero, non quello estratto:
        # l'arrotondamento ai 5 grux lo sposta sempre di un punto o due.
        real_discount = int(round((1.0 - (unit_price / max(1, list_price))) * 100))

        return MarketOffer(
            offer_id=f"bm{self._counter}",
            unit_id=unit_id,
            unit_name=units_map.get(unit_id, {}).get("name", unit_id),
            quantity=quantity,
            unit_price=unit_price,
            list_price=list_price,
            total_price=unit_price * quantity,
            list_total=list_price * quantity,
            discount_pct=real_discount,
            created_turn=turn,
            expires_turn=turn + lifetime,
            flavor=rng.choice(FLAVORS),
            source=rng.choice(SOURCES),
        )

    # ── acquisto ─────────────────────────────────────────────────

    def get_offer(self, offer_id: str) -> Optional[MarketOffer]:
        for offer in self.offers:
            if offer.offer_id == offer_id:
                return offer
        return None

    def take(self, offer_id: str, turn: int) -> MarketOffer:
        """Segna l'offerta come venduta. Solleva ValueError se non si può."""
        offer = self.get_offer(offer_id)
        if offer is None:
            raise ValueError("Offerta non più al banco.")
        if offer.sold:
            raise ValueError("Merce già venduta: il banco non tiene doppioni.")
        if offer.is_expired(turn):
            raise ValueError("Offerta scaduta: il merciaio ha già cambiato banco.")

        offer.sold = True
        self.purchases += 1
        self.units_bought += offer.quantity
        self.grux_spent += offer.total_price
        self.grux_saved += max(0, offer.list_total - offer.total_price)
        return offer

    def best_affordable(self, turn: int, grux: int) -> Optional[MarketOffer]:
        """L'affare migliore alla portata: il maggiore risparmio assoluto.

        È il criterio con cui compra l'IA — le interessa quanto porta a casa,
        non quanto è alta la percentuale su un'unità da poco.
        """
        best: Optional[MarketOffer] = None
        for offer in self.offers:
            if not offer.is_available(turn) or offer.total_price > grux:
                continue
            saving = offer.list_total - offer.total_price
            if best is None or saving > (best.list_total - best.total_price):
                best = offer
        return best

    # ── payload ──────────────────────────────────────────────────

    def to_dict(self, turn: int, unlocked: bool) -> Dict[str, Any]:
        return {
            "unlocked": bool(unlocked),
            "refresh_turn": self.next_refresh_turn,
            "turns_to_refresh": max(0, self.next_refresh_turn - turn),
            "offers": [offer.to_dict(turn) for offer in self.offers] if unlocked else [],
            "purchases": self.purchases,
            "units_bought": self.units_bought,
            "grux_spent": self.grux_spent,
            "grux_saved": self.grux_saved,
        }
