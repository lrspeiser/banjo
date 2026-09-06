# How contact becomes a crack in the current demo

The glass-versus-wood damage ranking in this demo is not yet a reliable
prediction of real materials. The current solver is an experimental physical
cell network. Its local response and propagation need further accuracy work.

An iron ball does not imply that every glass sample must completely shatter.
Tempered glass has manufacturing-induced stresses and typically breaks into
many small pieces; ordinary annealed glass can leave larger fragments, and
lamination can retain broken glass. Thickness, support, impact energy and
flaws affect the result. [Vitro's explanation of heat-treated glass](https://glassed.vitroglazings.com/heat-strengthened-vs-tempered-glass)
and [Pilkington's glass-selection guidance](https://www.pilkington.com/-/media/pilkington/site-content/usa/window-manufacturers/technical-bulletins/ats122glassselection20130114.pdf)
describe these differences. Banjo's current generic glass preset does not
include a tempered residual-stress field or lamination.

The panel fixture is a 24 x 36 x 4 cm sample with clamped boundary cells.
Inside its visible skin are 108 physical cells, arranged 6 x 9 x 2. Each cell
has material-derived mass and inertia. Its collision shape is a small sphere;
the visible flat surface does not yet supply the contact geometry. The
spheres leave gaps, so the impact patch is a coarse approximation.

1. **Find contacts.** The engine finds where the ball's collision shape meets
   nearby cell shapes. Each contact supplies a location, normal direction and
   relative motion to the collision solver. It computes opposing impulses
   and frictional response; it does not directly declare the board broken.
2. **Load the material.** Contacted cells move relative to neighboring cells.
   Spring-like connections resist changes in separation, according to
   material stiffness, direction and internal damping. The coupled contact
   and spring constraints are solved iteratively within each timestep.
3. **Evaluate local failure.** Each surviving connection uses its calculated
   axial reaction to estimate tensile opening. Glass connections use a
   brittle strength-plus-fracture-work condition. Oak uses a directional
   progressive-softening law. These are distinct constitutive approximations,
   not material names selecting destruction animations.
4. **Continue through the surviving network.** A damaged connection changes
   stiffness; a failed connection is removed. The next accepted step solves
   the changed network. Nearby connections now carry different loads and
   may fail in turn. A crack can continue, branch approximately through the
   available links, or stop. Work and material history persist.
5. **Separate and render.** A few failed connections may leave the entire
   object connected through other paths. Once all connecting paths across
   a region are severed, it becomes a separate component. Its cells retain
   motion and continue colliding under gravity; the skin exposes new faces.
   Broken-link count is not the number of shards.

The current model does not adequately reproduce fast stress waves, thin-plate
bending, full wood grain/shear behavior or tempered-glass residual stress.
The coarse timestep can smear stiff-glass reaction peaks, while the softer
wood network deforms enough to cross many local damage thresholds. This
helps explain the model's behavior, but does not establish that real wood
should fracture more than glass in this experiment.

Endpoint damage substeps now exist, but deeper diagnostic runs can gain
unphysical energy. The API and checked-in new trial scenes therefore default
to strict rejection when a refinement limit is reached. The next physical
gate is a coupled state/work error estimator, contact and spatial refinement,
then calibrated material/manufacturing state. See the
[checkpoint](additional-physics-checkpoint.md) for measured failures and
the retained acceptance criteria.
