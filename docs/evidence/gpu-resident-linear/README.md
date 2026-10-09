# Evidence provenance

- `native-linear.json`: direct registered-suite run on coupled source `31105d759be71507d256aac805caf643c5cf21e9895669e3d122819e96a0b33d`.
- `ctest-native-linear.json`: separate actual CTest run of that suite; timings differ because they are independent measurements.
- `checks.json`: complete 15-suite scoped CTest transcript, Windows runtime, base main revision and source registration. This is not the historical full repository suite.
- `sanitizers.json`: exact executed smoke script, its digest and final CUDA sanitizer transcripts. CUDA command graphs process new matrix data on every replay.
- `profile.json` and `profile.py`: runtime instrumentation of **preceding published source** `18716413cf18147bd79f4730fcce32c493e2ff0b9c296da4ba4a91775c809c0c` at main `f1f1f251b24ddead5bb94bb5d32960d59ed4bd9a`. Run from the repository root with the pinned GPU Python on that revision. The retained script writes `build/gpu-local-solve/profile.json`; that output was copied here without changing its contents. Event/host measurements overlap and instrumentation adds overhead. This is bottleneck evidence, not uninstrumented throughput.
- `initial-comparison.json`: preliminary bridge revision `456faeeab0f3f031de1ed2ed6eeb6e9022cc5499a31f00507c5a8c57ad9dcb5e`, before the final pinned ABI and refusal tests. Retained to disclose mixed timing observations; it is not final source qualification.
- `browser.json`: normal UI selector/control and actual journal comparison on the final working source before publication. Published server/revision/source verification is repeated after push and retained locally with the final screenshot.

Matrix/reference equality and conservation residuals do not independently qualify connected material trajectories, fracture/plastic realism or realtime. The nonlinear controller still runs on the host.
