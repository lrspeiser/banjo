# World physics language

Status: implementation reference for the current `WorldPackage` loader, 2026-09-05. This is a strict JSON, SI-unit intermediate format for human or LLM authored declarations. It is the foundation of a future authoring language, not yet a general programming language. The same engine contract is intended for CLI, headless, and lab entry points; none may give an LLM a physics tick or bypass validation.

## Package contract

`loadWorldPackage(const std::string&)` accepts a complete JSON document and publishes a `SparseThermalWorld` only after parsing and validation succeed. The top-level ABI is `"banjo-thermal-world-1"`, `units` must be `"SI"`, and the required fields are `physics_abi`, `units`, `voxel_size_m`, `materials`, `chunks`, and `regions`. Optional `heaters` apply bounded external work to active cells.

The loader rejects duplicate or unknown fields, non-finite values, control characters, unsupported ABI/units, missing references, duplicate IDs/addresses, and out-of-range values. The document is at most 4 MiB and 24 levels deep. It accepts at most 256 materials, 1,000,000 chunks, 256 regions, 512 cells per region, 32,768 total active cells, and 32,768 heaters. Voxel size is 0.001–10 m; region steps are 0.001–1 s. Chunk coordinates are bounded to ±1,000,000 and local coordinates to the 16³ chunk. These are admission bounds, not a claim that a world at the maximum is realtime.

Material declarations contain positive `id`, metadata `name`, `density_kg_m3`, `heat_capacity_j_kg_k`, and `conductivity_w_m_k`. Optional `fuel_fraction` and `oxygen_per_kg_solid` describe finite reservoirs. Optional `reaction` requires `activation_temperature_k`, `rate_per_s`, `heat_of_combustion_j_kg`, and `oxygen_per_kg_fuel`. Optional `phase_change` requires liquid heat capacity, melting temperature, and latent heat. Combining reaction and phase-change laws is rejected by the current implementation. A chunk declares `position`, `material`, and `temperature_k`; a phase-change chunk may also declare `liquid_fraction_at_melt`. A region declares a positive `id`, `step_s`, and unique cell addresses `{chunk, local}`. A heater declares an active `cell`, nonnegative `energy_j`, and nonnegative `maximum_energy_j`.

The runtime stores compact uniform 16³ chunks and explicitly activated insulated regions. `SparseThermalWorld::advance` is bounded by `WorldStepBudget` (`maximum_jobs`, `maximum_cell_operations`, and `maximum_wall_ms`) and reports completed work, late regions, lag, and budget exhaustion. A stale heater timestamp or backlogged region is rejected before mutation. Cold storage, bounded jobs, and backlog are proof limits that must be reported; they do not silently substitute cached outcomes.

## Energy model

The architecture distinguishes the following energy stores. These are conceptual names, not additional accepted JSON fields; this thermal ABI currently reports chemical energy and thermal enthalpy, while mechanical backends remain separate:

```text
chemical_j
sensible_j
latent_j
elastic_j
kinetic_j
gravitational_reference_j
```

Chemical energy may become reaction heat and retained product mass. Sensible thermal enthalpy is referenced to 0 K in the current constant-capacity approximation. Latent energy is represented by enthalpy and phase fraction. Mechanical backends own elastic, kinetic, contact-work, and gravitational-reference transfers. A falling stone therefore uses gravity and kinetic energy in the mechanical API; it does not expose a thermal “falling force” or put force in a material declaration. External heaters are explicit work transfers with a configured cap.

Heat exchange is equal and opposite. The current constant-property kernel has an exact isolated two-lump pair oracle; the enthalpy kernel uses bounded backward-Euler conduction and is first-order in time. Applying edge updates across a graph is symmetric operator splitting, not an exact graph solution. Precision, timestep, spatial resolution, and operator-splitting convergence must be measured before a physical claim is made.

## Water and phase boundaries

Water retains one material identity while its phase state changes. A phase boundary is isothermal: enthalpy added at the melting temperature changes liquid fraction and latent energy before temperature rises. Freezing reverses that transfer and releases latent heat into the receiving thermal state. Material IDs must not be swapped to manufacture energy.

This slice has no fluid flow, density-change advection, convection, pressure solve, smoke transport, or full-fluid requirement. Airflow, smoke, and full fluid behavior remain user-deferred capabilities. A phase law is therefore a local enthalpy/state law, not a claim that an ice block will move like water.

## Valid compact example

The following is a valid one-cell water package. The 1 cm voxel has volume 10⁻⁶ m³, so density 1000 kg/m³ gives 0.001 kg (1 gram). At the 273.15 K phase boundary, `liquid_fraction_at_melt: 0.5` stores half the latent heat: 0.001 × 334000 × 0.5 = 167 J, in addition to the sensible energy. The constants illustrate the law; conductivity, volume and pressure do not evolve with phase in this prototype.

```json
{
  "physics_abi": "banjo-thermal-world-1",
  "units": "SI",
  "voxel_size_m": 0.01,
  "materials": [{
    "id": 1,
    "name": "water",
    "density_kg_m3": 1000.0,
    "heat_capacity_j_kg_k": 2100.0,
    "conductivity_w_m_k": 0.6,
    "phase_change": {
      "liquid_heat_capacity_j_kg_k": 4200.0,
      "melting_temperature_k": 273.15,
      "latent_heat_j_kg": 334000.0
    }
  }],
  "chunks": [{
    "position": [0, 0, 0],
    "material": 1,
    "temperature_k": 273.15,
    "liquid_fraction_at_melt": 0.5
  }],
  "regions": [{
    "id": 1,
    "step_s": 0.05,
    "cells": [{"chunk": [0, 0, 0], "local": [0, 0, 0]}]
  }]
}
```

A heater experiment may add `heaters: [{"cell": {"chunk": [0,0,0], "local": [0,0,0]}, "energy_j": 10.0, "maximum_energy_j": 10.0}]`; the work is capped and applied only to that active cell. The extra 10 J raises the melt fraction from 0.5 to approximately 0.52994 while temperature remains 273.15 K.

## Capability boundary

The owner-approved [physical-cell and skin contract](object-skin-contract.md) adds a planned derived render surface, with new material interiors after damage. Skin topology, material-coordinate bindings and mesh revisions are not currently accepted fields of `banjo-thermal-world-1`; unknown fields continue to reject. A future shared authoring ABI must distinguish cosmetic appearance from physical material layers and preserve physical state when rebuilding a skin.

This document describes the current loader and thermal foundation, not all-world implementation or measured performance. Unsupported declarations must reject with a capability error or remain outside the package schema. Consult [`world-runtime-plan.md`](world-runtime-plan.md) for staged solver selection, conservation gates, bounded sparse execution, and deferred smoke/full-fluid work. No declaration, material name, cache, or LLM-generated text may claim calibrated glass, wood grain, tissue, fire, fluid flow, or realtime behavior without the corresponding reference test and convergence evidence.
