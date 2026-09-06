"""Replayable property-to-native-law trial for fictional isotropic materials.

The default mode is deterministic and makes no network request.  Passing
``--execute-llm`` is an explicit opt-in to one paid OpenAI Responses request.
Generated constants are hypothetical, uncalibrated inputs to the existing
small-strain isotropic reference law; this trial establishes no new law or
real-material claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples" / "authoring"))
sys.path.insert(0, str(ROOT / "playground"))
from material_behavior import MaterialBehavior
from material_behavior_client import evaluate_material_path
from server import local_configuration, strict_json

SEED = 20260906
STRAINS = [[0.0] * 6, [1e-4, 0.0, 0.0, 0.0, 0.0, 0.0], [0.0] * 6]
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["materials"],
    "properties": {"materials": {
        "type": "array", "minItems": 3, "maxItems": 3,
        "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "young_modulus_pa", "poisson_ratio", "density_kg_m3"],
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 80},
                "young_modulus_pa": {"type": "number", "minimum": 1e6, "maximum": 1e11},
                "poisson_ratio": {"type": "number", "minimum": 0.05, "maximum": 0.4},
                "density_kg_m3": {"type": "number", "minimum": 500, "maximum": 9000},
            },
        },
    }},
}
SYSTEM = """Generate exactly three uniquely named fictional materials. Values must be
hypothetical and uncalibrated. Choose diverse SI density, Young modulus, and
Poisson ratio values within the supplied schema. These are inputs to an existing
quasistatic small-strain isotropic elastic reference, not claims about real
substances, contact, dents, fracture, finite strain, or viscoelasticity."""


def seeded_proposal() -> dict:
    rng = random.Random(SEED)
    materials = []
    for index in range(12):
        materials.append({
            "name": f"Fictional replay material {index + 1:02d}-{rng.randrange(1000, 9999)}",
            "young_modulus_pa": 10 ** rng.uniform(6.0, 11.0),
            "poisson_ratio": rng.uniform(0.05, 0.4),
            "density_kg_m3": rng.uniform(500.0, 9000.0),
        })
    return {"source": "deterministic_seed", "seed": SEED, "materials": materials}


def llm_proposal() -> dict:
    api_key, model = local_configuration()
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not configured in the local .env")
    payload = {
        "model": model, "store": False, "max_output_tokens": 900,
        "reasoning": {"effort": "low"},
        "input": [{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": "Propose the three fictional parameter sets."}],
        "text": {"format": {"type": "json_schema", "name": "banjo_material_rules_trial",
                              "strict": True, "schema": SCHEMA}},
    }
    req = request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload, allow_nan=False).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=60) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("LLM response exceeded the 1 MiB budget")
            envelope = strict_json(raw)
    except error.HTTPError as exc:
        raise ValueError(f"LLM request failed (HTTP {exc.code}); no automatic retry was issued") from None
    except (error.URLError, TimeoutError):
        raise ValueError("LLM connection failed or timed out; no automatic retry was issued") from None
    if not isinstance(envelope, dict) or envelope.get("status") != "completed":
        raise ValueError("LLM did not complete the material proposal")
    texts = []
    for output in envelope.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "refusal":
                raise ValueError("LLM declined the material proposal")
            if content.get("type") == "output_text":
                texts.append(content.get("text", ""))
    proposal = strict_json("".join(texts))
    validate_proposal(proposal, expected_count=3)
    return {
        "source": "openai_responses_explicit_paid_opt_in",
        "model": model,
        "request_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
        "request_wall_s": time.perf_counter() - started,
        "usage": envelope.get("usage", {}),
        "materials": proposal["materials"],
    }


def validate_proposal(proposal: dict, expected_count: int) -> None:
    if not isinstance(proposal, dict) or not isinstance(proposal.get("materials"), list):
        raise ValueError("proposal must contain a materials array")
    materials = proposal["materials"]
    if len(materials) != expected_count:
        raise ValueError(f"proposal must contain exactly {expected_count} materials")
    names = []
    expected = {"name", "young_modulus_pa", "poisson_ratio", "density_kg_m3"}
    for item in materials:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("each proposal material must have exactly the schema fields")
        name = item["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("material names must be non-empty strings of at most 80 characters")
        names.append(name)
        _bounded(item["young_modulus_pa"], 1e6, 1e11, "young_modulus_pa")
        _bounded(item["poisson_ratio"], 0.05, 0.4, "poisson_ratio")
        _bounded(item["density_kg_m3"], 500, 9000, "density_kg_m3")
    if len(set(names)) != len(names):
        raise ValueError("material names must be unique")


def _bounded(value: object, low: float, high: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{field} must be finite and in [{low}, {high}]")
    return number


def find_executable() -> Path:
    names = ("banjo_material_behavior_probe.exe", "banjo_material_behavior_probe")
    candidates = [path for name in names for path in (ROOT / "build").glob(f"**/{name}")]
    files = sorted((path.resolve() for path in candidates if path.is_file()), key=lambda p: str(p))
    if not files:
        raise ValueError("banjo_material_behavior_probe is not built under build/")
    return files[-1]


def comparable_response(response: dict) -> dict:
    return {key: response[key] for key in ("schema", "status", "scope", "samples")}


def run_trial(proposal: dict, executable: Path) -> dict:
    materials = proposal["materials"]
    validate_proposal({"materials": materials}, expected_count=len(materials))
    results = []
    for index, values in enumerate(materials):
        behavior = MaterialBehavior(
            material_id=f"trial-{index + 1:02d}", name=values["name"],
            density_kg_m3=values["density_kg_m3"], mechanical_law="isotropic_elastic",
            parameters={"young_modulus_pa": values["young_modulus_pa"],
                        "poisson_ratio": values["poisson_ratio"],
                        "maximum_total_strain_norm": 0.01},
        )
        actual = evaluate_material_path(executable, behavior, STRAINS)
        renamed = MaterialBehavior(
            material_id=f"renamed-{index + 1:02d}", name=f"Renamed fictional {index + 1:02d}",
            density_kg_m3=behavior.density_kg_m3, mechanical_law=behavior.mechanical_law,
            parameters=behavior.parameters,
        )
        renamed_actual = evaluate_material_path(executable, renamed, STRAINS)
        if behavior.physical_hash != renamed.physical_hash:
            raise AssertionError("rename changed physical hash")
        if comparable_response(actual) != comparable_response(renamed_actual):
            raise AssertionError("rename changed native physical outputs")
        young, poisson = values["young_modulus_pa"], values["poisson_ratio"]
        expected_axial = young * (1 - poisson) / ((1 + poisson) * (1 - 2 * poisson)) * 1e-4
        actual_axial = actual["samples"][1]["stress_pa"][0]
        if not math.isclose(actual_axial, expected_axial, rel_tol=2e-12, abs_tol=1e-8):
            raise AssertionError("native axial stress did not match the isotropic analytical oracle")
        results.append({
            "material": behavior.to_dict(), "strain_path": STRAINS,
            "expected_axial_stress_pa": expected_axial,
            "actual": actual,
            "rename_invariance": {"passed": True, "renamed_material": renamed.to_dict()},
        })
    return {"schema": "banjo.material-rules-trial-evidence.v1", "status": "complete",
            "claim": "fictional uncalibrated inputs executed by the existing small-strain isotropic reference",
            "limitations": ["no contact or dent geometry", "no fracture", "no finite strain",
                            "no viscoelasticity", "no real-material calibration"],
            "executable": str(executable), "results": results}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-llm", action="store_true",
                        help="make one paid OpenAI Responses request; never retried automatically")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "material-rules-trial")
    args = parser.parse_args()
    proposal = llm_proposal() if args.execute_llm else seeded_proposal()
    validate_proposal({"materials": proposal["materials"]}, 3 if args.execute_llm else 12)
    evidence = run_trial(proposal, find_executable())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "proposal.json", proposal)
    write_json(output / "evidence.json", evidence)
    summary = {"status": "complete", "mode": proposal["source"],
               "materials_executed": len(evidence["results"]),
               "analytical_oracles_passed": len(evidence["results"]),
               "rename_invariance_passed": len(evidence["results"]),
               "output_directory": str(output)}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, allow_nan=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, AssertionError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
