# Adaptive ground with a digging speed gate

Owner direction, October 5, 2026: larger ground components and smaller tool
components may reduce calculations, but digging must stay quick. This is design
and an acceptance plan, not an implemented adaptive solver or a measured speedup.
Current main is `ab6d266c`; its [physical ground checkpoint](physical-ground-gameplay-checkpoint.md)
and unsupported-law boundaries continue to apply.

## Player contract

- Compression groups identical solid matter; it creates no alternating air gaps.
- A larger storage block does not enlarge the bite a player must remove. Preserve
  a 25 cm selectable excavation scale while refining only the physical contact
  and affected material. Future adaptive levels must preserve existing voids,
  material beds, source identity, damage history and support geometry.
- One deliberate collection receives a connected released component and its
  constituent cells. Do not require one click per tiny constituent or add a
  weight-limit chore. Actual native reach and ownership remain authoritative.
- Work, hardness and actual topology decide removal. No fixed hit count, free
  work, assigned fragment velocity, global time acceleration or physics changes
  based solely on camera distance. LLM calls stay outside the digging loop.

## Proposed usability gates (not yet qualified)

1. Target feedback within 100 ms of input on the reference desktop; refusal
   explains reach, point suitability or missing power immediately.
2. Established starter soil/sand use sustains at least two successful actions
   per second, with p95 complete-response latency at most 400 ms. Measure first
   preparation separately; aim for at most one second, retaining native motion.
3. Verify actual material removal, visible hole progress and collection through
   real mouse/touch input. Do not count accepted requests with no removed matter
   as successful digging. Holding/releasing input must not leave a long queue.
4. A declared 1 m by 1 m, 3 m deep dry excavation should take at most five minutes
   using its intended progression tool and obtainable finite power. Record soil
   and rock separately, including acquisition/collection actions and actual
   work. This is a product target, not a claim that the current wooden pick can
   mine rock or that the present opening supplies satisfy it.

## Implementation order

Measure ordinary preparation, repeat cutting, native work/removal, collection,
collision rebuild and save cost first. Remove repeated controller/host waits
only where measured physical state permits. Then compress uniform inactive
ground; retain local fine contact/cut patches and invalidate only affected
chunks. Tool geometry controls its required precision; LLM-authored names do not.

Compare identical experiments on glass, oak and iron across supported grids.
Track mass/volume, source work, momentum/energy residuals, contact error,
timestep, live components and p95 frame/action cost. Test coarse/fine seams,
repeat cuts, private collection, failed save/retry, restart and two players.
Reject adaptive handoff that adds energy, heals damage or closes an existing hole.

## Baseline measurement status

The October 5 isolated browser probe used a flat 25 cm column fixture and the
original oak field pick. It stopped before tool use: its camera/ray setup did
not establish named native pickup. No `/api/world/tool/use` request ran, so no
first-use latency, repeat rate or compression benefit is inferred. The ignored
`build/measure-column-clicks.py` harness/log/screenshot retain the observation;
the owner demo and source physics were untouched. Establish a valid ordinary
input fixture before evaluating the gates above. Existing 77.3 ms native stroke
timing and 2.771 s simulated elapsed time are not browser gameplay acceptance.
