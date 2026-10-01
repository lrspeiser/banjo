"""Atomically pair a native source operation with its host receiving receipt."""
import uuid
from mcp import ground_transfers as ledger
import world_access


def transfer(app, holder, command):
    op = {"ground_withdraw": "withdraw", "ground_return": "return"}[command["op"]]
    amounts = {k: command.get(k, 0.0) for k in ledger.KEYS}
    # Runtime metadata is server-only. Named clients cannot pick another
    # holder; adapters supply that identity from the authenticated actor.
    with world_access.state_lock(app), app.live._lock:
        room, session = app.room, app.live.session
        if session is None:
            raise ValueError("Open a world before moving bulk material")
        with session._lock:
            if getattr(app, "live_inprocess", False):
                raise ValueError("Bulk receiving receipts require the native subprocess adapter")
            if session.state.get("bulk_transfer_receipts") != 1:
                raise ValueError("Rebuild the native engine before transferring machine bulk material")
            ident = uuid.uuid4().hex
            candidate = ledger.prepare(getattr(room, "ground_transfers", None), holder, op, amounts, ident)
            reply = app.live.act({"session": session.id, **command})
            room.ground_transfers = ledger.accept(candidate, holder, op, ident, reply)
            return reply
