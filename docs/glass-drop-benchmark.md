# Published 6 mm toughened-glass ball-drop benchmark

This benchmark records a real destructive experiment before Banjo attempts to
reproduce it. It is a reference for **fracture onset in a repeated, increasing
drop-height test**. It is not evidence that Banjo's current material network is
validated, and the source does not establish complete shattering or a fragment
distribution.

The machine-readable record is
[`assets/benchmarks/glass-drop-reference.json`](../assets/benchmarks/glass-drop-reference.json).

## Selected experiment

The primary publication is M. Kozłowski, K. Zemła and M. Kosmal,
"Exploratory Finite Element Analysis of Monolithic Toughened Glass Panes
Subjected to Hard-Body Impact," *IOP Conference Series: Materials Science and
Engineering* 1203 (2021) 022145,
[doi:10.1088/1757-899X/1203/2/022145](https://doi.org/10.1088/1757-899X/1203/2/022145)
([publisher page](https://iopscience.iop.org/article/10.1088/1757-899X/1203/2/022145)).
Its experimental sections, Table 1 and Figures 1-5 report 105 tests covering
6, 8 and 10 mm panes.

An expanded primary report is M. Kozłowski, K. Zemła, M. Kosmal and
O. Kopyłow, "Experimental and FE Study on Impact Strength of Toughened
Glass–Retrospective Approach," *Materials* 14(24) (2021) 7658,
[doi:10.3390/ma14247658](https://doi.org/10.3390/ma14247658)
([publisher full text](https://www.mdpi.com/1996-1944/14/24/7658),
[PubMed Central full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC8704005/)). It expands
the campaign to 185 panes from 5 to 15 mm and confirms the selected setup and
6 mm summary. The measurements originated in a 2009 Institute of Ceramics and
Building Materials internal technical report cited by both papers; that report
is not linked publicly by either paper.

The selected series is:

- regular soda-lime silicate float glass;
- monolithic, fully tempered panes with polished edges;
- nominal dimensions 500 x 360 x 6 mm;
- 35 specimens;
- a 4.11 kg **steel** ball, released above the pane;
- two revolving steel support cylinders, each 50 mm in diameter and 365 mm
  long, covered by a thin elastic-rubber layer;
- room temperature and 50% relative humidity; and
- an initial 0.10 m drop followed by 0.10 m increases on the same specimen
  until fracture was observed.

The papers call the panes simply supported. They do not publish the distance
between the roller axes, the rubber layer thickness or properties, individual
measured pane thicknesses, the pause/reset procedure between drops, or an
unambiguous experimental ball diameter. The schematic and the numerical
reproduction put the impact at the pane centre, but the experimental-method
text does not state a measured impact-point tolerance.

## Measured fracture evidence

For the 6 mm series, Table 1 reports a mean destructive height of 0.76 m, a
sample standard deviation of 0.24 m and a coefficient of variation of 31% for
35 specimens. Figure 2 plots every specimen at the 0.10 m protocol resolution.
Transcribing those bars gives this terminal-height frequency table:

| First observed fracture height | Specimens | Cumulative fractured | Not yet fractured after step |
|---:|---:|---:|---:|
| 0.50 m | 7 | 7 | 28 |
| 0.60 m | 8 | 15 | 20 |
| 0.70 m | 6 | 21 | 14 |
| 0.80 m | 2 | 23 | 12 |
| 0.90 m | 6 | 29 | 6 |
| 1.00 m | 0 | 29 | 6 |
| 1.10 m | 1 | 30 | 5 |
| 1.20 m | 5 | 35 | 0 |

The transcription has mean 0.760 m and sample standard deviation
0.236643 m, reproducing the rounded published summary. The JSON retains all
35 values and identifies Figure 2 as the transcription source.

The closest protocol step to the published mean is 0.80 m. Two specimens first
fractured at that step, while 23 of 35 had fractured by that step. This does
not mean a fresh 6 mm pane has a measured 23/35 probability of failing in one
0.80 m drop: each pane had already received every lower-height impact. Repeated
subcritical impacts and any accumulated surface damage are part of the source
history.

The experiment records the first observed fracture only. It does not report
whether the whole pane fragmented, fragment number or size, crack extent,
residual connectivity, force, impulse, strain, displacement, contact duration
or high-speed timing. The IOP paper explicitly says that no data besides the
critical drop height were recorded. "Fractured" is therefore the supported
outcome; "shattered completely" is not.

The other IOP series provide useful thickness controls but only the published
summaries are retained here: 8 mm fractured at 0.91 +/- 0.29 m and 10 mm at
1.37 +/- 0.39 m, with 35 specimens in each series.

## Impact quantities and projectile uncertainty

Using the reported mass, `g = 9.81 m/s^2`, no release velocity and no losses
before contact, the 0.76 m mean corresponds to `m g h = 30.6425 J` and
`sqrt(2 g h) = 3.86150 m/s`. These are derived ideal free-fall quantities, not
measurements. The proposed 0.30, 0.50, 0.80 and 1.20 m checkpoints correspond
to 12.0957, 20.1596, 32.2553 and 48.3829 J respectively.

The experimental sections publish a 4.11 kg steel ball but no diameter or
steel grade. The IOP numerical section later says that its ball and roller
surface are both 50 mm in diameter, yet a solid 50 mm steel sphere at the
expanded paper's numerical steel density of 7850 kg/m3 has a mass of about
0.514 kg. A 4.11 kg sphere at that density has a diameter of about 99.998 mm.
The numerical section also uses 0.51375 kg as one eighth of 4.11 kg, so its
50 mm statement cannot safely establish the physical projectile diameter.

Banjo's catalog `iron` is pure-iron-like material data, not the unspecified
experimental steel. At Banjo's 7870 kg/m3 density, a 100 mm iron sphere would
weigh 4.12072 kg, 0.2609% above the reported impactor mass. A reproduction
should make 4.11 kg authoritative and label a 100 mm diameter as an inferred
geometry sensitivity until an archival apparatus record supplies the diameter.
Matching mass and nominal diameter does not equate steel and pure iron contact
properties.

## Banjo comparison contract

The first reference run should preserve the source protocol: retain the same
pane state, start at 0.10 m, and increase the height by 0.10 m after every
nonfracturing impact. Run an ensemble of at least 35 independently generated,
material-derived surface/flaw realizations; repeating one deterministic network
does not represent the measured scatter. Compare the terminal-height frequency
distribution, mean and sample standard deviation rather than fitting a single
strength to 0.76 or 0.80 m.

The 0.30, 0.50, 0.80 and 1.20 m steps are useful near-threshold checkpoints.
In the published staircase history, respectively 0, 7, 23 and 35 of 35 panes
had fractured by those steps. Fresh-pane, one-drop runs at the same heights are
valuable controls, but they are a proposed Banjo experiment without a directly
matching published probability.

Before a physical comparison is claimed:

1. converge timestep, solver iterations, contact capacity and spatial network
   resolution without changing material strengths;
2. report contact impulse, peak response, energy/work closure, first fracture
   time, broken-bond topology and connected components even though the paper
   cannot validate all of those observables;
3. bracket the unreported support span, rubber layer and projectile diameter,
   and show the outcome's sensitivity to each;
4. retain glass, oak and iron runs under identical geometry as material-law
   controls, while labeling the published fracture evidence as glass-only; and
5. do not force fine cells, preset shards, name-based thresholds or tuned
   strengths to obtain the plotted outcome.

The current Banjo network has unresolved contact, energy and fracture
convergence defects. This reference defines a future validation target; it does
not upgrade that status.
