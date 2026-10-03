"""Receiving receipts for native bulk transfers to arbitrary named holders.

This ledger is independent of fabrication jobs. A machine hopper, player store
or another future receiver must identify itself and retain the native packet.
It records transfers, not terrain edits or a constitutive material law.
"""
from copy import deepcopy
import math

SCHEMA = "banjo.ground-transfers.v1"
KEYS = ("sand_m3", "soil_m3", "rock_m3")
MAX_RECEIPTS = 4096


def empty():
    return {"schema": SCHEMA, "receipts": []}


def quantities(value):
    if not isinstance(value, dict) or set(value) - set(KEYS):
        raise ValueError("Invalid bulk transfer quantities")
    result = {k: value.get(k, 0.0) for k in KEYS}
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100
           for v in result.values()):
        raise ValueError("Bulk transfer requires finite nonnegative volumes")
    if sum(result.values()) <= 0:
        raise ValueError("Bulk transfer requires a positive volume")
    return result


def totals(book=None):
    book = empty() if book is None else book
    if not isinstance(book, dict) or set(book) != {"schema", "receipts"} or book["schema"] != SCHEMA:
        raise ValueError("Invalid ground transfer ledger")
    receipts = book["receipts"]
    if not isinstance(receipts, list) or len(receipts) > MAX_RECEIPTS:
        raise ValueError("Invalid ground transfer history")
    exported, returned, holders, ids = dict.fromkeys(KEYS, 0.0), dict.fromkeys(KEYS, 0.0), {}, set()
    for receipt in receipts:
        if not isinstance(receipt, dict) or set(receipt) != {"id", "holder", "op", "packet", "quantities"}:
            raise ValueError("Invalid ground transfer receipt")
        ident, holder, op = receipt["id"], receipt["holder"], receipt["op"]
        if not isinstance(ident, str) or not 1 <= len(ident) <= 128 or ident in ids:
            raise ValueError("Duplicate or invalid ground transfer id")
        if not isinstance(holder, str) or not 1 <= len(holder) <= 256:
            raise ValueError("Ground transfer needs a named holder")
        ids.add(ident)
        amounts = quantities(receipt["quantities"])
        held = holders.setdefault(holder, dict.fromkeys(KEYS, 0.0))
        if op == "withdraw":
            # The actual source packet, including density/mass, must match the
            # declared receipt. Fabrication accepts the same packet format.
            from .fabrication import bulk_packet
            packet = bulk_packet(receipt["packet"])
            if packet["source"] != "excavated_ground":
                raise ValueError("Ground receiver needs an excavated native packet")
            actual = dict.fromkeys(KEYS, 0.0)
            for item in packet["contents"]:
                from .fabrication import GROUND_DENSITIES
                if item["substance"] not in GROUND_DENSITIES:
                    raise ValueError("Unsupported excavated substance")
                if not math.isclose(item["mass_kg"], item["volume_m3"] * GROUND_DENSITIES[item["substance"]],
                                    rel_tol=1e-12, abs_tol=1e-10):
                    raise ValueError("Ground transfer mass does not match native volume")
                actual[item["substance"] + "_m3"] += item["volume_m3"]
            if actual != amounts:
                raise ValueError("Ground packet and receiving quantities differ")
            destination = exported
            for k in KEYS: held[k] += amounts[k]
        elif op == "return":
            if receipt["packet"] is not None:
                raise ValueError("A ground return must reference existing holder stock")
            destination = returned
            for k in KEYS:
                if amounts[k] > held[k] + 1e-10:
                    raise ValueError("Ground return exceeds this holder's received stock")
                held[k] -= amounts[k]
        else:
            raise ValueError("Invalid ground transfer operation")
        for k in KEYS: destination[k] += amounts[k]
    return {"exported": exported, "returned": returned, "holders": holders}


def prepare(book, holder, op, amounts, ident):
    """Validate before touching the native source; no history can be discarded."""
    state = totals(book)
    amounts = quantities(amounts)
    if not isinstance(ident, str) or not 1 <= len(ident) <= 128:
        raise ValueError("Invalid ground transfer id")
    if not isinstance(holder, str) or not 1 <= len(holder) <= 256:
        raise ValueError("Ground transfer needs a named holder")
    if len((book or empty())["receipts"]) >= MAX_RECEIPTS:
        raise ValueError("Ground transfer history is full; archive it before further transfers")
    if any(r["id"] == ident for r in (book or empty())["receipts"]):
        raise ValueError("Ground transfer id has already been used")
    if op == "return" and any(amounts[k] > state["holders"].get(holder, {}).get(k, 0.0) + 1e-10 for k in KEYS):
        raise ValueError("Ground return exceeds this holder's received stock")
    if op not in ("withdraw", "return"):
        raise ValueError("Invalid ground transfer operation")
    return deepcopy(book or empty())


def accept(prepared, holder, op, ident, reply):
    if op == "withdraw":
        packet = deepcopy(reply["material_packet"])
        from .fabrication import bulk_packet
        bulk_packet(packet)
        amounts = dict.fromkeys(KEYS, 0.0)
        for item in packet["contents"]:
            from .fabrication import GROUND_DENSITIES
            if item["substance"] not in GROUND_DENSITIES: raise ValueError("Unsupported excavated substance")
            amounts[item["substance"] + "_m3"] += item["volume_m3"]
    else:
        packet, amounts = None, dict(reply["ground_returned"])
    prepared["receipts"].append({"id": ident, "holder": holder, "op": op,
                                "packet": packet, "quantities": amounts})
    totals(prepared)
    return prepared


def accumulate(prepared, holder, ident, reply):
    """Keep exact native totals for repeated single-material pile receipts.

    Each compacted row stays within the existing 100 m³ receipt bound. This
    stores source quantities, never a predicted yield or a terrain animation.
    """
    out = accept(prepared, holder, 'withdraw', ident, reply)
    newest = out['receipts'][-1]
    for old in out['receipts'][:-1]:
        if (old['holder'] == holder and old['op'] == 'withdraw'
            and len(old['packet']['contents']) == len(newest['packet']['contents']) == 1
            and old['packet']['contents'][0]['substance'] == newest['packet']['contents'][0]['substance']
            and all(old['quantities'][k] + newest['quantities'][k] <= 100 for k in KEYS)):
            for key in KEYS: old['quantities'][key] += newest['quantities'][key]
            for key in ('volume_m3', 'mass_kg'):
                old['packet']['contents'][0][key] += newest['packet']['contents'][0][key]
            out['receipts'].pop()
            break
    totals(out)
    return out
