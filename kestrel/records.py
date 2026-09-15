"""Records are the observation. Every business document is a Record with a state machine and a history (SPEC §5)."""
from dataclasses import dataclass, field

class IllegalTransition(Exception): pass

@dataclass
class Record:
    id: str; type: str; created_day: int; state: str
    history: list = field(default_factory=list); data: dict = field(default_factory=dict)

def _chain(*states):
    return {(a, b) for a, b in zip(states, states[1:])}

LEGAL = {
    "po": _chain("draft","confirmed","in_production","shipped","received","inspected","invoiced","matched","paid")
          | {("draft","cancelled"),("confirmed","cancelled"),("in_production","cancelled"),("received","short_closed"),("inspected","short_closed")},
    "asn": set(), "receipt": set(),
    "lot": {("sampling","accepted"),("sampling","rejected"),("rejected","sorted"),("rejected","returned")},
    "invoice_in": {("open","blocked"),("open","accepted"),("blocked","accepted"),("blocked","disputed"),("disputed","accepted"),("accepted","paid")},
    "booking": _chain("booked","cut_off","loaded","at_sea","arrived","customs","cleared","delivered")
               | {("cut_off","rolled"),("rolled","loaded"),("booked","blanked"),("blanked","cut_off"),("booked","cancelled"),("cut_off","cancelled")},
    "contract": {("active","expired")},
    "work_order": _chain("planned","released","running","complete") | {("planned","cancelled"),("released","cancelled")},
    "transfer": _chain("created","in_transit","delivered"),
    "order": _chain("received","allocated","shipped","delivered") | {("received","declined")},
    "invoice_out": {("open","paid")}, "chargeback": {("open","paid")}, "credit_note": {("open","paid")},
    "ret": {("in_transit","restocked"),("in_transit","written_off")},
    "qualification": {("pending","done")}, "audit": {("pending","done")},
}
CLOSED = {
    # asn/receipt have no LEGAL transitions at all (procurement.py creates them once, in
    # "sent"/"received" respectively, and never moves them again -- see procurement.py's
    # asn/receipt records.new calls). That single creation state IS their terminal state;
    # naming it here is what makes Records.open() finite for these two kinds instead of
    # silently degenerating to "every record of this type ever created" (D3).
    "po": {"paid","cancelled","short_closed"}, "asn": {"sent"}, "receipt": {"received"}, "lot": {"accepted","sorted","returned"},
    "invoice_in": {"paid"}, "booking": {"delivered","cancelled"}, "contract": {"expired"},
    "work_order": {"complete","cancelled"}, "transfer": {"delivered"}, "order": {"delivered","declined"},
    "invoice_out": {"paid"}, "chargeback": {"paid"}, "credit_note": {"paid"}, "ret": {"restocked","written_off"},
    "qualification": {"done"}, "audit": {"done"},
}
PREFIX = {"po":"PO","asn":"ASN","receipt":"GR","lot":"LOT","invoice_in":"INV","booking":"BK","contract":"FC","work_order":"WO",
          "transfer":"TR","order":"SO","invoice_out":"AR","chargeback":"CB","credit_note":"CN","ret":"RET","qualification":"QL","audit":"AU"}

def transition(rec: Record, new_state: str, day: int, detail: str = "") -> None:
    if (rec.state, new_state) not in LEGAL[rec.type]:
        raise IllegalTransition(f"{rec.id}: {rec.state} -> {new_state}")
    rec.state = new_state
    rec.history.append((day, new_state, detail))

class RecordStore:
    def __init__(self):
        self._recs: dict[str, Record] = {}; self._counts: dict[str, int] = {}
    def new(self, type: str, day: int, state: str, **data) -> Record:
        n = self._counts.get(type, 0) + 1; self._counts[type] = n
        rec = Record(f"{PREFIX[type]}-{n:04d}", type, day, state, [(day, state, "created")], dict(data))
        self._recs[rec.id] = rec; return rec
    def get(self, id: str) -> Record: return self._recs[id]
    def all(self, type: str) -> list: return [r for r in self._recs.values() if r.type == type]
    def open(self, type: str) -> list: return [r for r in self.all(type) if r.state not in CLOSED[type]]
    def ids(self): return list(self._recs)
