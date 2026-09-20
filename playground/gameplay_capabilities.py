"""One published priority/status list; incomplete acceptance gates stay visible."""
import json
from pathlib import Path

def catalog():
    path = Path(__file__).resolve().parents[1]/"progression/physics-capabilities.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if {item["id"] for item in data["items"]} != set(range(1,31)) or len(data["items"]) != 30:
        raise ValueError("The gameplay checklist must retain all 30 capability IDs")
    counts = {status:sum(item["status"]==status for item in data["items"])
              for status in ("complete","partial","planned")}
    if sum(counts.values()) != 30: raise ValueError("Unknown gameplay completion status")
    return {**data,"counts":counts}
