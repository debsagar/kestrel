import pytest
from kestrel.records import RecordStore, transition, IllegalTransition, LEGAL

def test_new_and_ids_are_sequential_per_type():
    s = RecordStore()
    a = s.new("po", 0, "draft", supplier="S-BAT", qty=5000)
    b = s.new("po", 1, "draft", supplier="S-SOC", qty=2000)
    assert a.id == "PO-0001" and b.id == "PO-0002" and s.get(a.id).data["qty"] == 5000

def test_transition_records_history_and_enforces_legality():
    s = RecordStore(); po = s.new("po", 0, "draft")
    transition(po, "confirmed", 2, "supplier confirmed 5000")
    assert po.state == "confirmed" and po.history[-1] == (2, "confirmed", "supplier confirmed 5000")
    with pytest.raises(IllegalTransition):
        transition(po, "paid", 3)

def test_open_excludes_closed_states():
    s = RecordStore(); po = s.new("po", 0, "draft"); s.new("po", 0, "draft")
    transition(po, "cancelled", 1)
    assert len(s.open("po")) == 1 and len(s.all("po")) == 2

def test_every_type_has_a_machine():
    for t in ("po","booking","work_order","transfer","order","invoice_in","lot","contract","ret"):
        assert LEGAL[t]
