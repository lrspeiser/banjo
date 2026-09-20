#pragma once

#include "fastlattice/TileImpactScene.hpp"
#include "terrain/Environment.hpp"
#include "thermo/ThermoWorld.hpp"

#include <cstdint>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <vector>

namespace banjo::fastlattice {

struct ToolTerrainHost;

// Where one object is, under the name the request gave it.
struct LiveBodyPose {
    std::string name;
    // What it is made of, by its common name -- "oak", "alumina ceramic". A
    // host showing someone an object has to be able to say what it is, and
    // working it back from the name is guesswork the moment something breaks:
    // "glass plate piece 7" only looks like glass because of how it was named.
    std::string material;
    // "box" and "sphere" are the shape that was asked for and are drawn exactly.
    // "hull" is a piece that broke off something, whose cells are its real
    // surface -- there is no primitive for it and the host draws its cells.
    std::string shape{"hull"};
    // Empty for legacy lattice bodies; explicit no-internal-failure model otherwise.
    std::string mechanical_model;
    struct PreciseBox { Vec3 center_local_m, dimensions_m; };
    std::vector<PreciseBox> rigid_boxes_local;
    // What it measures NOW. For a box or a sphere that has burned, the part of
    // it not burned away: what collides and what is drawn. The box its matter
    // is measured against stays in LiveMaterialState::reference_m.
    Vec3 dimensions_m{};
    // How many times its shape has been changed where it stands -- burning
    // takes a box in from every face, and a piece whose cells burn away is
    // rebuilt from the ones left. A host that drew it redraws it when this
    // moves. Zero for anything nothing has happened to.
    unsigned revision{};
    std::uint32_t color_rgba{};
    Vec3 position_m{};
    // Which way it faces: the box or ball of dimensions_m, turned by this about
    // position_m, is the one that collides, and whatever below is "in its own
    // frame" (dent_at_m, kerfs) is in the frame this turns. A body built with
    // rotation_deg faces that way from the start, although the engine carries
    // that turn inside its collision shape rather than in its rigid pose.
    double orientation_wxyz[4]{1.0, 0.0, 0.0, 0.0};
    Vec3 velocity_m_s{};
    // What it weighs now, in kilograms: what the solver moves, and so what a
    // hand has to hold up and a throw has to accelerate. Read every time
    // rather than kept, because a body that burns gets lighter. Zero for
    // anchored scenery, which the solver never moves.
    double mass_kg{};
    bool anchored{};
    bool held{};
    // Whether this came OFF something, rather than being what it always was.
    //
    // A shape of "hull" is not the same question. A thing that bends takes a
    // permanent set and is rebuilt from where its matter ended up, which makes
    // it a hull too -- but it is still the same object, in a new shape, and
    // nobody expects to pocket it by walking past. A dented iron ball weighs
    // three and a half kilograms and had gone into somebody's pockets as
    // "debris" before this existed.
    bool fragment{};
    // The deepest permanent set this body carries, and where it is in the
    // body's own frame. Zero for anything that has never been dented.
    //
    // A dent is real and it is SMALL. An iron ball hammered into an anvil takes
    // a permanent set of about a fifth of a millimetre on a 120 mm ball -- so
    // the shape barely changes, and rebuilding it out of its cells to "show"
    // that threw away a smooth sphere in exchange for a 136-cube staircase that
    // displays no dent at all, because the cells had moved 90 micrometres.
    //
    // So the number travels instead. A host can draw the shape it was and mark
    // the spot, and say a true depth next to it.
    double dent_m{};
    Vec3 dent_at_m{};
    // The cuts this body carries, in its own frame. A kerf is where a blade has
    // been THROUGH the matter: the bonds across it are severed, and a host
    // draws it so a partial cut can be seen for what it is. Empty for anything
    // no edge has been into. See docs/cutting-model.md.
    struct Kerf {
        // The plane the blade passed through: a point on it, the direction
        // along the edge (`along`), the way the edge faced (`facing`) and the
        // normal to the blade's flats (`normal`).
        Vec3 point_local_m{};
        Vec3 along_local{}, facing_local{}, normal_local{};
        // What the edge has swept through matter, as strips along the edge:
        // each is [along_from, along_to] x [facing_from, facing_to] in metres
        // from the point, in the plane.
        struct Strip {
            double along_from{}, along_to{}, facing_from{}, facing_to{};
        };
        std::vector<Strip> strips;
        double thickness_m{};
    };
    std::vector<Kerf> kerfs;
    // Where this body's cells sit in its own frame. Only filled in when the
    // caller asks for geometry, because it does not change between steps and a
    // bowl has two thousand of them.
    //
    // A body authored as one box or sphere is drawn as that shape and needs
    // none of this. Everything else -- a join, whose union no primitive
    // describes, and a piece that broke off something, whose cells ARE its
    // surface -- has to be drawn as its cells or it is drawn as a lie: a
    // hollow bowl rendered from its bounding box is a solid block.
    std::vector<Vec3> cells_local_m;
};

// One contact from the step just taken, judged against what the struck object
// can actually take.
//
// The verdict is not a guess. `would_break` is the refracture admission test:
// two necessary conditions, stress and energy, derived in Refracture.hpp from
// the acoustic impedances of the two bodies and the smallest removal threshold
// any live bond in the struck one carries. A contact that fails either cannot
// break anything, and one that passes is a contact the lattice has to be run on
// to find out what it did.
// What a ray met, named the way the scene names things.
struct LivePick {
    bool hit{};
    // Empty when the ray stopped on something that is not one of the scene's
    // bodies -- the ground. "It hit the floor" and "it hit nothing" are
    // different answers and a pointer has to tell them apart.
    std::string name;
    double distance_m{};
    Vec3 point_world_m{};
};

// Where a thing would go set down on a surface at a point, turned about the
// vertical -- its underside on the surface, its middle over the point -- and
// whether it fits there. Asked of the engine's own shapes; nothing moves. See
// LiveWorld::placement.
struct LivePlacement {
    bool fits{};
    Vec3 at_m{};                             // its centre of mass, set down there
    double turn_wxyz[4]{1.0, 0.0, 0.0, 0.0}; // its rigid orientation there
    double facing_wxyz[4]{1.0, 0.0, 0.0, 0.0}; // which way it would face: that with its shape's own turn on top
    std::string rests_on;                    // what is under its middle
    int supported_corners{};                 // corners of its footprint with something under them, of four
    std::vector<std::pair<std::string, double>> touching;   // what it would go into, and how far, m
    std::string why;                         // in words, for the person choosing where
};

// A motion the hand makes by itself, step by step, instead of being moved
// through it a frame at a time by whoever is driving. See
// docs/interaction-profiles.md.
//
// What travels along `path_m` is where the hand WANTS the grip. It goes no
// faster than `speed_m_s`, gets up to that at `accel_m_s2`, and is never more
// than `lead_m` ahead of the grip: a hand is on the thing it holds and cannot
// run on without it. The hand pulls with what it has (setHandStrength), so what
// the held body does is the world's answer -- a heavy thing falls behind and a
// light one keeps up, and whatever it meets can slow it or stop it. Nothing
// here is a speed given to the body.
//
// Made at the step's own rate, not at a host's frame rate. A throw is over in a
// tenth of a second, which is three frames at thirty a second: moved by the
// host, the frame rate would decide how hard it was thrown.
struct LiveStroke {
    // Two to sixteen points, world metres: the path of the grip. It is joined
    // wherever the grip is nearest to it, so a path that starts a little away
    // from the grip is not a jump.
    std::vector<Vec3> path_m;
    double speed_m_s{};
    double accel_m_s2{};
    double lead_m{0.05};
    // Open the hand when the GRIP reaches the end: the release of a throw. Not
    // when the hand's target does -- that would let go of a heavy thing half a
    // metre before it had been thrown.
    bool let_go_at_end{};
    // Stop trying after this long. The hand stays shut; the host decides.
    double give_up_s{2.0};
    // Which way the hand wants the thing to face at each point of the path,
    // w first, one per point -- or none, and the wrist keeps whatever it was
    // last asked (aimHeld). Between two points the wish turns from one to the
    // next as the hand goes, and the wrist turns the thing towards it with the
    // torque it has: a swing is the grip going round and the thing turning
    // with it. Nothing here sets how anything is turned.
    std::vector<Quat> facings_wxyz;
};

// What the hand is doing, and what it has done.
struct LiveHand {
    std::string holding;          // "" for nothing
    // How it holds it: "carry" (placed exactly where it is put -- an editor's
    // move, with no force and so no work), "haul" (pulled with a bounded force
    // because it is attached to something), "grip" (wielded: a bounded force at
    // a point on it and a bounded torque), or "" when the hand is empty.
    std::string mode;
    Vec3 target_m{};              // where the hand wants the grip
    Vec3 grip_m{};                // where the grip is
    Vec3 grip_velocity_m_s{};
    Vec3 force_n{};               // what it pulled with in the last step
    // The work the hand has done on what it holds since it took hold, joules:
    // its force times the grip's own displacement, and its torque times the
    // turn, step by kept step. Measured rather than worked out from a speed,
    // so it includes lifting, and whatever went into what the thing rubbed on.
    double work_j{};
    bool stroking{};
    double stroke_along_m{};      // how far the GRIP has got along the path
    double stroke_length_m{};
    // How the last stroke ended: "" while one runs or none has; "reached" (the
    // hand got to the end and holds there), "let go", "blocked" (the grip has
    // stopped while the hand pulls with everything it has: as far as this hand
    // can take it), "gave up" or "cancelled".
    std::string stroke_ended;
    // When a stroke opened the hand: what it let go of, how fast that was
    // going as it left, when, and the work the hand had done on it by then.
    std::string let_go_body;
    Vec3 let_go_velocity_m_s{};
    double let_go_at_s{-1.0};
    double let_go_work_j{};
};

// Where something would go if it flew from here with this velocity, stepped the
// way the solver steps it -- gravity, then the flying body's own damping, at
// the rate the world is being stepped -- and checked against the solver's own
// shapes along the line of its centre. Changes nothing.
struct LiveFlight {
    std::vector<Vec3> points_m;   // the path, a point every 1/60 s
    bool hit{};
    std::string hit_name;         // "" for the ground
    Vec3 hit_point_m{};
    double hit_after_s{};
    double hit_speed_m_s{};
};

// What a stroke would do before it is made: the held body alone, pulled along
// the path by this hand under gravity -- the same law a step pushes with --
// and then where it would fly. What it cannot know is anything the stroke
// itself would bump into on the way, which is why it is a preview.
struct LiveStrokePreview {
    bool possible{};
    std::string why;              // when it is not possible, or does not reach
    bool reaches_end{};           // false: the hand gave up before the grip got there
    double stroke_s{};
    double work_j{};
    Vec3 let_go_at_m{};           // the body's centre as the hand opens
    Vec3 let_go_velocity_m_s{};
    LiveFlight flight;
};

struct LiveImpact {
    std::string struck;              // the object that took the hit
    std::string by;                  // what hit it, or "the ground"
    double closing_speed_m_s{};
    double threshold_speed_m_s{};    // what it would take to break `struck`
    // What it would take to leave a mark on it: the speed below which nothing
    // can take a permanent set. Infinite for a brittle material, which has no
    // yield point and goes from elastic straight to broken.
    //
    // Almost always the lower of the two, and the gap between them is where
    // real damage lives: iron yields in compression at 200 MPa and crushes at
    // 600, so most of what happens to an iron thing happens in between.
    double dent_speed_m_s{};
    double energy_j{};
    bool would_break{};
    bool would_dent{};
};

// A pin two named things turn about, as the scene sees it.
//
// The engine's hinge is between two bodies. This is between two NAMES, which is
// a different thing and the reason this layer exists: bodies do not survive
// breaking. Everything in an island is destroyed and rebuilt when anything in
// it comes apart, so a hinge made against a body id is a hinge that lasts until
// the first hard knock -- and a constraint holding a body that no longer exists
// is not a bug that misbehaves, it is one that crashes.
//
// So a scene joint is remembered as: two names, and where the pin sits in each
// body's OWN frame. The body-local part is what makes it survive: the whole
// assembly can be picked up, carried, turned upside down, and the pin is still
// in the same place in the wood, because that is how it was written down.
struct LiveJoint {
    unsigned id{};
    // "hinge" -- a pin two things turn about.
    // "slider" -- a line two things move along.
    // "link"   -- one link of a rope or chain: it pulls, and it does not push.
    // "pulley" -- a rope rove over two fixed points: pull one end, the other
    //             comes up. The IDEAL pulley -- a cable-length relationship,
    //             not a wheel with a rope wrapped round it.
    // "fixing" -- two things held together as one: a peg, a bracket, a catch, a
    //             locking bar. It has a strength along its axis and another
    //             across it, and either one exceeded parts it.
    // "elastic"-- something that stores energy by being stretched or squashed: a
    //             bow limb, a spring, a bent plank. It pushes as well as pulls,
    //             which is what tells it from a rope.
    //
    // This is also the unit on the three numbers below, because a joint with
    // one degree of freedom has one number and the only question is what it is
    // measured in: radians and newton metres for a pin, metres and newtons for
    // a slide.
    std::string kind{"hinge"};
    std::string a, b;
    // Where it has got to, from where it was made.
    double at{};
    double lower{}, upper{};
    double friction{};
    // What a link or a pulley is carrying, in newtons. Zero for slack, and
    // zero for a pin or a slide, which have no tension in any useful sense.
    double tension_n{};
    // For a fixing: what it is carrying along its axis and across it, and what
    // it can take of each. A peg pulled straight out and a peg sheared sideways
    // fail at different loads, so they are two numbers and not one.
    double tension_n_now{}, shear_n_now{};
    double holds_tension_n{}, holds_shear_n{};
    // Above zero, a ONE-WAY fixing: b sits on a the way an arrow's nock sits on
    // a string, pushed along the axis as hard as anything pushes it and held
    // the other way with no more than this. Its axis points the way b comes off.
    double comes_off_n{};
    // For an elastic: the declared linear model, and what it currently holds.
    //
    //     force_n  = stiffness_n_m * (at - rest_m)
    //     stored_j = stiffness_n_m * (at - rest_m)^2 / 2
    //
    // Both are the MODEL's numbers rather than something measured out of the
    // solver, because the model is what was declared -- and whether the solver
    // actually delivers them is the thing the tests check, by comparing the
    // work put in against the kinetic energy that comes out.
    double rest_m{}, stiffness_n_m{}, damping_n_s_m{};
    double force_n{}, stored_j{};
    // A pulley's mechanical advantage. One for everything else.
    double ratio{1.0};
    // Where a pulley's rope runs over, in world metres. Both zero for every
    // other kind, which has nothing of the sort.
    Vec3 over_a_m{}, over_b_m{};
    // What it takes to part a link. Zero means it never parts.
    double breaks_at_n{};
    // A drum's rope: the radius it lies at, how much of it is on the drum (`at`
    // is how much is off it, and `upper` the whole rope), and where it leaves
    // the drum and meets the load, for a host that draws it. Zero for every
    // other kind.
    double radius_m{}, wound_m{};
    Vec3 leaves_m{}, meets_m{};
    // Which way the drum turns to take its rope on: +1 the positive way about
    // its axle, -1 the other. Zero for every other kind.
    int winds{0};
    // Where it is now, in the world, for a host that wants to draw it. For a
    // slide, the point is where the travel is measured FROM -- where the thing
    // was built -- not where it has got to.
    Vec3 point_world_m{};
    Vec3 axis_world{};
    // True while both ends are real and the pin is doing its job. A joint whose
    // wood was smashed away is reported once, gone, rather than silently
    // vanishing from the list -- a host that drew a gate wants to know the gate
    // came off its hinges.
    bool attached{true};

    // ---- heat and strength (docs/thermal-mechanics.md) ----------------------
    //
    // Which of the two things the joint is MADE of, when that was said: the peg
    // of a fixing, the rope segment a link is tied through, a spring's limb. Its
    // section carries the load, so the joint's strength (a fixing, a link) or
    // its stiffness (an elastic) follows that body's material law, temperature
    // and what is left of it. "" when nothing was named: the joint is then
    // exactly the numbers that were declared, and heat changes nothing about it.
    std::string member;
    // What it could take cold -- declared, or worked out from the member's own
    // section and material where the declared number was zero. holds_*,
    // breaks_at_n and stiffness_n_m above are what it has NOW.
    double rated_tension_n{}, rated_shear_n{}, rated_breaks_at_n{}, rated_stiffness_n_m{};
    // The share of that it still has: 1 cold, falling as the member heats,
    // chars and burns. For a fixing, the lower of its two.
    double capacity_fraction{1.0};
    // How many times a change in the member made the joint be asked again
    // whether it holds -- with both ends woken, so the load is measured by the
    // solver rather than remembered from before the change.
    unsigned rechecks{};
    // Why it let go, once it has: what it carried against what it could still
    // take, and the state of what it was made of. Empty while it holds, and for
    // a joint taken out on purpose.
    std::string parted_because;
    // The two numbers that decided it: the load the solver measured in the
    // step it parted, and what it could still take at that moment. Zero while
    // it holds.
    double parted_load_n{}, parted_capacity_n{};
};

// A store of energy: a battery (docs/machine-world.md). Joules in it and what
// it can hold, a voltage for the current it gives, and the most power it can
// give. Nothing goes back into it but from a declared source, and a step that
// is taken back takes nothing out of it.
struct LiveEnergyStore {
    unsigned id{};
    std::string name;
    std::string body;             // what it is in; "" for nothing
    double capacity_j{};
    double charge_j{};
    double voltage_v{};
    // The most it gives, watts; zero for no limit but its charge.
    double max_power_w{};
    // All it has given since it was made, joules.
    double given_j{};
    // What steps asked of it that it no longer had, joules. A motor's drive is
    // held to what is left before each step, from the speed the step starts
    // at; a step that ends faster did a little more work than that, and the
    // little is this. Reported rather than folded in anywhere.
    double short_j{};
};

// A motor on a pin, wired to a store: a DC motor's torque-speed line, from the
// two numbers a maker gives -- the torque it stalls at and the speed it runs at
// unloaded, both at the store's voltage. The command runs from -1 to 1, the
// share of that voltage applied. A brake holds the pin by friction, and draws
// nothing.
//
// Its account, one kept step at a time, from the impulse the solver applied:
//   work_j   the torque times the turn: what it did to what it drives;
//   heat_j   what it turned into heat -- its windings' I^2 R, and whatever a
//            load driving it gave back, since nothing goes back into the store;
//   drawn_j  what it asked of the store: its work plus its heat, while it
//            drives, and never less than nothing.
// While the pin coasts or brakes, what the pin's friction takes out of the turn
// is friction_heat_j.
//
// What it turns runs in bearings: the pin's friction and the motor's windings
// are its losses, and the engine's slight drag on moving pieces (0.02 of their
// speed a second on everything but a ball, a numerical stand-in rather than a
// law) is taken off the pin's two bodies while the motor is on it.
struct LiveMotor {
    unsigned id{};
    unsigned joint{};             // the pin (LiveWorld::hinge)
    unsigned store{};             // what it draws on (LiveWorld::energyStore)
    double stall_torque_n_m{};
    double no_load_rad_s{};
    double brake_torque_n_m{};
    double command{};
    bool brake{};
    // "driving", "coasting", "braking", "flat" (told to drive, and its store
    // is empty) or "gone" (its pin is not in anything).
    std::string state{"coasting"};
    // The last kept step.
    double speed_rad_s{};         // b's turn relative to a's, about the pin
    double torque_n_m{};
    double current_a{};
    double power_w{};             // asked of the store
    // Since it was made.
    double turned_rad{};          // the whole turn, not wrapped at +-180 degrees
    double work_j{}, heat_j{}, drawn_j{}, friction_heat_j{};
};

// A machine's controller (docs/machine-world.md, "Operating a machine"): what a
// person or a program means -- power on or off, a direction, a drive setting --
// turned into its motor's command and brake before every step. It governs the
// motor's effort and never the motion: every command it sets is on the motor's
// line, and how far the shaft turns is the world's answer. A hoist's
// controller also reads its rope on the drum: it slows for the two ends of its
// travel and stops at them, and stops when its load comes to rest on something.
struct LiveControl {
    unsigned id{};
    std::string name;             // the machine's, as the host calls it
    unsigned motor{};             // what it works (LiveWorld::motor)
    // A hoist's rope on its drum (LiveWorld::drum), and the rope out at the
    // top and at the bottom of its travel, metres; a shaft has no rope (0) and
    // no travel.
    unsigned rope{};
    double top_out_m{}, bottom_out_m{};
    // The sign of the motor's command that is forward: for a hoist the one
    // that winds its rope on, raising the load, worked out from the pin, the
    // drum and which way the rope winds.
    int forward{1};
    // What it was last told. `power` is whether it may drive at all; the
    // direction is -1 (lower, reverse), 0 (stop) or 1 (raise, forward); the
    // setting is the share of the battery's voltage it drives at -- an effort,
    // not a speed. Lowering a hoist it comes on from the share that holds the
    // load still, at no more than 2 of the voltage a second, so a motor that
    // would drive the drum down faster than the load can fall never lets the
    // rope go slack.
    bool power{};
    int direction{};
    double setting{1.0};
    // Who told it last, and their count. A command from a sender that is no
    // newer than one already applied from that sender is dropped as stale, so
    // a "raise" held up on its way cannot start a machine that a later "stop"
    // stopped.
    std::string sender;
    std::uint64_t seq{};
    // What it has its motor doing now.
    double command{};
    bool brake{};
    // Measured, as the last kept step left it: the shaft's turns a minute the
    // forward way, and for a hoist the rope out and how fast the rope comes in
    // -- its load's speed, rising, while the rope is taut.
    double speed_rpm{};
    double out_m{};
    double rope_speed_m_s{};
    // What stands in its way, in words a person reads, or "" when nothing does
    // and it does what it was told: "off"; "stopped, holding on its brake";
    // "stopped: it coasts, with no brake to hold it"; "slowing for the top",
    // "at the top", "slowing for the bottom", "at the bottom"; "the load is
    // down: its rope is slack"; "stopping before it turns the other way";
    // "stalled: it made no progress, so it stopped"; "too weak at this
    // setting: the load turned it back, so it stopped"; "held back by its
    // battery's power"; "its battery is flat"; "the hand is on it"; "its
    // motor is gone".
    std::string condition;
};

// What heat, composition and burning have done to what one body can carry.
// See docs/thermal-mechanics.md and thermo/ThermalMechanics.hpp.
struct LiveMaterialState {
    std::string name;
    std::string material;
    // The law it follows, and where that law's numbers come from. Empty for a
    // material with no law: heat does not change what it can carry, and that is
    // said rather than implied.
    std::string law;
    std::string provenance;
    // Whether the thermal network holds it. A body nothing has heated is
    // exactly as it was: its factors are all one.
    bool tracked{};
    // Surface and core now, and the hottest each has been.
    double surface_k{thermo::kReferenceTemperatureK};
    double core_k{thermo::kReferenceTemperatureK};
    double peak_surface_k{thermo::kReferenceTemperatureK};
    double peak_core_k{thermo::kReferenceTemperatureK};
    // How much of its load-bearing matter is left, and its load-bearing share
    // when it was declared, against its material's own.
    double remaining_fraction{1.0};
    double composition_factor{1.0};
    // Its box, and the section across its longest axis: what has burned, the
    // char, what is still sound, and every factor against the same section cold
    // -- now, and if it were cooled now.
    Vec3 dimensions_m{};
    thermo::SectionState section;

    // ---- what is left of it (docs/thermal-mechanics.md, "One material state")
    //
    // The box its material is measured against -- as authored, or the cells'
    // box a piece broke off as -- and the part of that box not burned away,
    // which is what collides and what is drawn. The section above is taken
    // across the reference box with the burned depth inside it, so nothing is
    // counted twice. Equal while nothing has burned.
    Vec3 reference_m{};
    Vec3 remaining_m{};
    double remaining_volume_m3{};
    // The rigid body it is now: what it weighs and its principal inertia about
    // its own axes, from the matter left spread over the volume left.
    double mass_kg{};
    Vec3 inertia_kg_m2{};
    // Its cells: how many it has, and how many burned away entirely.
    std::size_t cells{};
    std::size_t cells_burned{};
    // What a fracture run would give its lattice: over its bonds, the weakest
    // and the mean tension factor and the mean stiffness factor, against the
    // same bonds cold. The same field the section integrates. 1 cold.
    double bond_tension_min{1.0};
    double bond_tension_mean{1.0};
    double bond_stiffness_mean{1.0};
    // Times its collision shape has been changed where it stands.
    unsigned revision{};
};

// A thing carrying more than it can hold up.
//
// This is the OTHER way something breaks here, and it exists because the first
// way cannot see it. Every other break in this engine starts from a blow: a
// closing speed, an impedance, an energy. A shelf with too much stacked on it
// is not struck by anything at all -- measured, a plank bridging two piers with
// an iron block sitting on it reports NO contacts whatsoever once everything
// has come to rest, because the contact ledger is a ledger of impacts. Load it
// until it should snap and nothing would ever ask.
//
// So this is asked separately, from statics rather than from dynamics: what is
// resting on it, how far apart the things holding it up are, and what bending
// that puts in it.
//
//     a simply supported beam, span L, section b x d
//     carrying a point load W in the middle and its own weight w per metre
//
//     stress  =  3 W L / (2 b d^2)  +  3 w L^2 / (4 b d^2)
//
// Like every other bound in this engine, `stress_pa` past `strength_pa` is
// NECESSARY AND NOT SUFFICIENT: it says the lattice is worth running, not that
// the thing is going to come apart. The beam formula assumes the load is in the
// middle and the ends are free to rotate, which is the worst case for both, so
// it errs towards asking.
struct LiveOverload {
    std::string name;
    // What is stacked on it, in newtons, not counting its own weight.
    double carrying_n{};
    // How far apart the things holding it up are. A beam held everywhere along
    // its length has no span and cannot be bent -- which is why a plate lying
    // flat on the floor will not break however hard it is loaded.
    double span_m{};
    // What that works out to, and what the material can take.
    double stress_pa{};
    double strength_pa{};
    // What its section can still take, against the same beam cold: 1 for
    // anything heat has not touched. strength_pa is already the material's
    // strength times this, so stress_pa past strength_pa stays the whole test.
    double capacity_fraction{1.0};
    // Why, in words: the bending it carries and what is left to carry it.
    std::string why;
};

// What statics said about a body answered for a sustained load rather than a
// blow (fracture/SustainedLoad.hpp): the body's own lattice, as heat has left
// it, solved for equilibrium under its weight and what rests on it, held up
// where it rests, with the shared failure criterion applied until nothing more
// fails. One per body, the latest.
struct LiveStatics {
    std::string name;
    double time_s{};
    // "held", "broke", or why it could not say: "no support found under it",
    // "did not converge", "round limit".
    std::string stop;
    double load_n{};
    // The largest ratio of any bond's strain to its removal threshold under
    // the load, before anything failed: below 1 it carries it.
    double first_failure_ratio{};
    double deflection_m{};
    std::size_t bonds_removed{}, rounds{}, solves{}, supported_cells{}, loaded_cells{}, pieces{};
    double cost_ms{};
};

// A body whose load-bearing matter burned away entirely: it left the world,
// and what it still held -- its ash, the last of its moisture -- left the
// thermal network with it, on the ledger (left_kg).
struct LiveBurnedAway {
    std::string name;
    std::string material;
    double time_s{};
    double residue_kg{};
    std::string why;
};

// An edge on a body. See docs/cutting-model.md for the whole model; this is
// what a host can see of one.
//
// A blade is declared ON a body that already exists -- the body supplies the
// matter, the material, the mass and its distribution -- and the declaration
// adds what cells cannot resolve: where the edge runs, which way it faces, how
// thick and how sharp it is, and where a hand holds it.
struct LiveBlade {
    unsigned id{};
    std::string body;
    std::string material;
    // Where it is now, in world metres: the edge heel to tip, the way it
    // faces, the normal to its flats, and the grip.
    Vec3 heel_m{}, tip_m{}, facing{}, flat{}, grip_m{};
    // The same in the body's own frame, for a host that draws the edge riding
    // on the body's pose rather than asking every frame.
    Vec3 heel_local_m{}, tip_local_m{}, facing_local{}, grip_local_m{};
    double thickness_m{}, edge_radius_m{}, bevel_deg{};
    // What it has done. `cut_work_j` is measured from the solver's own
    // friction impulses; `cut_area_m2` is the area that bought, at each
    // material's declared resistance.
    double cut_area_m2{}, cut_work_j{};
    // What the edge is in right now, "" for nothing.
    std::string cutting;
    // False once the body carrying it has gone -- broken up, or swept away --
    // and while it is set aside (LiveWorld::park), when the edge is out of the
    // world with it.
    bool attached{true};
};

// One meeting between an edge and something else, from first touch until they
// part. Every contact is reported, including the ones that cut nothing, because
// "it did not cut because the flat hit it" is an answer a host has to be able
// to give.
struct LiveCut {
    std::string blade;    // the body carrying the edge
    std::string target;   // what it met, by the name it had when it was met
    // "edge", "slice", "press": the edge bit, and how it was moving.
    // "glancing", "flat", "point": it met the surface some other way and was
    //                              an ordinary contact. See docs/cutting-model.md
    //                              section 5 for the rules, which are geometry
    //                              and motion, never names.
    // "blunt": the target is as hard as the blade, or harder, and flattens
    //          the edge rather than being cut.
    // "brittle": the target has no yield point; it cracks, it is not cut.
    std::string kind;
    double at_s{};
    // The relative motion of the edge at first contact, in the blade's axes:
    // `into` along the facing, `along` the edge, `across` the flats.
    double speed_m_s{}, into_m_s{}, along_m_s{}, across_m_s{};
    // The material's resistance to this edge, R = G + H w, J/m^2 (= N per
    // metre of engaged edge).
    double resistance_j_m2{};
    // What this contact has cut so far, and what that cost.
    double area_m2{}, work_j{};
    std::size_t bonds{};   // bonds severed
    std::size_t links{};   // rope links severed
    bool separated{};      // the target came apart
    std::size_t pieces{};  // into how many, when it did
    bool open{};           // still in contact
};

// The working end of a tool: a point on a body that can go into the ground.
// See docs/ground-work.md for the whole model; this is what a host sees of it.
//
// Declared ON a body, as an edge is: the body supplies the matter, the
// material, the mass and where it is. The declaration adds what cells cannot
// resolve -- where the tip is, which way the point goes in, how wide and thick
// it is and how sharply it comes to its tip, how much of the tool is point --
// and where a hand holds it.
struct LiveToolPoint {
    unsigned id{};
    std::string body;
    std::string material;
    // Where it is now, in world metres, and the same in the body's own frame.
    Vec3 tip_m{}, pointing{}, grip_m{};
    Vec3 tip_local_m{}, pointing_local{}, grip_local_m{};
    double width_m{}, thickness_m{}, angle_deg{}, length_m{};
    // What the point is in right now ("soil", "sand", "loose soil"), "" for
    // nothing, and how far in along its own axis.
    std::string in;
    double depth_m{};
    // False once the body carrying it has gone -- broken up, or swept away --
    // and while it is set aside (LiveWorld::park), when the point is out of the
    // world with it.
    bool attached{true};
};

// One meeting between a tool's point and the ground, from first touch until
// the point is out again. Every meeting is reported, including the ones that
// loosened nothing, and the ones the model does not cover: "not supported" is
// an answer, and it is never "your tool failed".
struct LiveGroundWork {
    unsigned point{};          // the tool point
    std::string tool;          // the body carrying it
    std::string ground;        // what the point met: "soil", "sand", "loose soil", "rock", "the floor"
    // "in the ground"  the point is in and the ground is resisting it (open)
    // "broke out"      a pry broke ground out, and it came loose
    // "pulled out"     the point came out without breaking anything out
    // "stopped"        ground at least as hard as the point stopped it
    // "glanced"        the point met the ground side-on: an ordinary contact
    // "not supported"  the ground there is a regime the model does not cover
    std::string kind;
    bool supported{true};
    // Why, for "stopped", "glanced" and "not supported"; what happened, for
    // anything else worth saying.
    std::string why;
    double at_s{};
    Vec3 at_m{};                   // where the point entered, or met the ground
    double closing_speed_m_s{};    // along its own axis, as it arrived
    double depth_m{};              // the deepest it went, along its axis
    double sideways_m{};           // how far it went sideways while in the ground
    // Measured from the solver: the ground's push back on the point along its
    // axis over the whole meeting, the most it pushed with in one step, and
    // the work it took out of the tool -- going in, and being pried.
    double impulse_n_s{};
    double peak_force_n{};
    double work_j{};
    double penetration_work_j{};
    double breakout_work_j{};
    // The model's own numbers at the deepest it went: what the ground resisted
    // the point going in with, and a pry with.
    double resistance_n{};
    double passive_n{};
    // What came loose and was taken out of the ground through the dig path --
    // and so is carried (terrain::Environment::carried).
    terrain::Volumes loosened;
    double loosened_kg{};
    // The tool as the meeting ended: whole or not, and its deepest dent.
    bool tool_whole{true};
    double tool_dent_m{};
    std::string model;             // "ground-work-v1"
    bool open{};
    // Where what came loose went out through the ground's dig, as a dig edit
    // says it ({"dig": {"from_m", "to_m", "width_m", "depth_m"}}): a host that
    // keeps the ground's edits keeps this one, and the ground opened again from
    // them has the same hole and carries the same.
    bool dug{};
    double dug_from_m[2]{};
    double dug_to_m[2]{};
    double dug_width_m{};
    double dug_depth_m{};
};

// A bounded tool action, asked for by a host: the hand makes it at the step's
// own rate with the strength it has, and the world decides what it does.
//
//   swing  the held tool is swung so its point comes down on `target_m` -- a
//          point on the ground -- turning about `shoulder_m`, the way a pick
//          is swung. With `raise_deg` above zero it is first raised back that
//          far; at zero it swings from wherever it is held.
//   lever  a tool whose point is in the ground is pried: turned by
//          `lever_deg` about where the point went in, the handle coming back
//          towards `shoulder_m`, and then drawn up out of the ground.
//
// `speed_m_s` is as fast as the hand may take the grip along the motion. How
// fast the tool actually goes is the hand's strength against the tool's mass;
// what it does to the ground is the ground's.
struct LiveStrike {
    Vec3 target_m{};
    Vec3 shoulder_m{};
    // A steady swing. With the wrist turning the tool as the grip goes round,
    // its point comes down two to three times as fast as the hand goes.
    double speed_m_s{4.0};
    double raise_deg{0.0};
    bool lever{};
    double lever_deg{40.0};
    double give_up_s{2.0};
};

// A moment where the world was made to wait, or was saved from waiting.
//
// Working out a fracture costs between a third of a second and a second, and
// that is irreducible -- every way of making the run shorter was measured and
// every one of them changes the answer. So the only thing left is to not make
// anyone wait for it, and the only way to know whether that is working is to
// write down every time it happens.
// What a sweep picked up, added up by material rather than by shard: nobody
// wants forty entries called "glass plate 20mm piece 31", they want to know they
// now have four hundred grams of glass.
struct LiveCollected {
    std::string material;
    double kilograms{};
    std::size_t pieces{};
    std::size_t cells{};
    // Which bodies went, so a host can show them going rather than have them
    // blink out of existence between one frame and the next.
    std::vector<std::string> took;
};

struct LiveDelay {
    // When, in world time.
    double at_s{};
    // What it was about.
    std::string object;
    // "blocked"     the host asked and had to wait for the whole run
    // "foreseen"    a collision was spotted coming, with this much warning
    // "precomputed" the answer was ready before it was asked for
    // "held"        the pair was pinned while the answer was worked out
    const char *kind{"blocked"};
    // How much warning there was, for "foreseen": the time until contact.
    double lead_ms{};
    // What it cost, for "blocked" and "precomputed".
    double cost_ms{};
    // For a lattice run: the step it was taken at -- its own lattice's -- and
    // how many of them it took.
    double step_s{};
    std::uint64_t steps{};
};

// What the lattice actually did when it was run. The bounds above say what is
// POSSIBLE; only running it says what happened.
enum class LiveOutcome : std::uint8_t {
    Nothing = 0,   // asked about something that is not there, or cannot be run
    Held = 1,      // it took the hit and is the shape it was
    Dented = 2,    // still one piece, and no longer the shape it was
    Broke = 3,     // it came apart
};

// What opening a world from a saved one gave back (LiveWorld::open with a
// snapshot). See LiveWorld::snapshot for what a saved world holds.
struct LiveRestore {
    // "whole"  the world as it was saved: every body where it was and moving
    //          or at rest as it was, every piece with its cells and name,
    //          dents, severed bonds and cuts, joints at the angle they had,
    //          edges and points, what was set aside, and the hand.
    // "poses"  the saved world did not fit this scene -- it was saved from
    //          another one, or from a build that lays the cells out another
    //          way -- so the world opened from its scene and each thing still
    //          whole and its authored self, on no joint and carrying no edge or
    //          point, was put back where it was left.
    // "carried" the scene had changed since the world was saved (the room's
    //          chat added, moved or took something away; a thing was stood
    //          up), so the saved world was carried into it thing by thing
    //          (LiveWorld::open with a LiveCarry). Each authored thing the
    //          change did not touch came back exactly as it was saved -- its
    //          cells, its pieces, its dent and cuts, where it was and how it
    //          moved, asleep or awake -- with the pins, stores, motors, edges
    //          and points the host still declares the same way, its heat, and
    //          the hand's hold. What the change added, moved or took away is as
    //          the scene has it.
    // "none"   opened from its scene; nothing saved could be used.
    // "" for a world not opened from a saved one.
    std::string tier;
    std::string why;              // why not whole, in words; "" when whole
    double saved_t_s{};           // the saved world's clock
    std::size_t bodies{};         // how many bodies came back (were put back, for "poses")
    // What a saved world does not carry yet, in words. For "carried", what did
    // not come back as it was saved first, thing by thing (not_carried).
    std::vector<std::string> not_kept;
    // For "carried": thing by thing, what did not come back as it was saved,
    // and why -- the room changed it or took it away, or it could not be
    // carried exactly.
    std::vector<std::string> not_carried;
    // For "carried": the things woken because a saved thing near them did not
    // come back as it was -- the room took it away, or has it as the room makes
    // it now -- so what rested on it or against it falls or moves. Everything
    // else came back asleep or awake as it was saved.
    std::vector<std::string> woken;
    // For "carried": how much of each came back as it was saved, and how many
    // bodies are as the scene has them instead.
    struct Carried {
        std::size_t placed{};     // whole things whose cells could not be found again, put back where left
        std::size_t fresh{};      // bodies as the scene has them: new, changed, or not carried
        std::size_t gone{};       // saved bodies of things the scene no longer has
        std::size_t joints{}, energy_stores{}, motors{}, controls{}, blades{}, tool_points{};
        std::size_t heat{};       // bodies whose heat came back
        bool hand{};              // the hand holds what it held
    };
    Carried carried;
    // What is set aside in the world opened again, where each was put away and
    // facing the way poses() says things face: a host whose own record says
    // one of them is out in the world can bring it back there.
    struct Parked {
        std::string name;
        Vec3 at_m{};
        Quat facing{};
    };
    std::vector<Parked> parked;
};

// What a host still declares of a saved world, for opening that world into a
// scene that has changed since it was saved (LiveWorld::open with a carry).
//
// Pins, edges, points, stores and motors go in from the host once the scene is
// open; the scene names none of them. So only the host can say which it still
// declares as it did when the world was saved -- each by the id the saved world
// has for it (LiveWorld::snapshot). One it does not name comes back no more: the
// host declares what it has now in its place.
struct LiveCarry {
    // Explicit host assertion that terrain declarations/edits are unchanged.
    bool ground{};
    std::set<unsigned> joints, energy_stores, motors, controls, blades, tool_points;
    // Things the host is about to declare something new on -- a pin, an edge, a
    // point -- written against where the scene authors them. Each comes back as
    // the scene has it, because a declaration made against where a thing was
    // authored misses it wherever it has got to since. Scenery never moves, so
    // what is anchored comes back as it was all the same.
    std::set<std::string> declared_anew;
};

// A scene that keeps running instead of being run.
//
// runTileImpact is a batch: build, fracture, hand off, settle, write a
// recording, return. Everything it knows dies with the call, which is why the
// playground plays a film rather than a world -- to move something you have to
// edit the scene and run the whole thing again.
//
// This holds the rigid world open instead. A host steps it a frame at a time,
// reads where everything is, and can take hold of an object and move it. The
// rigid phase is already far faster than realtime (0.146 s of wall for 4.000 s
// of scene on a four-object ramp, 27x faster than it needs to be), so the
// limit here is not the physics.
//
// It starts intact and stays intact: no lattice phase runs, because nothing has
// been struck yet. A live world currently moves, collides and settles, and
// breaks nothing. Fracture on demand -- re-entering the lattice when a contact
// is hard enough to matter -- is the piece that is still missing, and the
// contact ledger is the trigger it will use.
class LiveWorld {
public:
    // Throws if the scene cannot be built, exactly as the batch lane would.
    [[nodiscard]] static std::unique_ptr<LiveWorld> open(const TileImpactRequest &request);
    ~LiveWorld();
    LiveWorld(const LiveWorld &) = delete;
    LiveWorld &operator=(const LiveWorld &) = delete;

    // Advance by one fixed step. A host calls this at whatever rate it draws.
    void step(double dt_s);
    [[nodiscard]] double time_s() const;
    // How many things are in the world: what poses() lists, so a thing set
    // aside (park) is not counted until it is back.
    [[nodiscard]] std::size_t bodies() const;

    // Every object, in the order they were authored.
    // `with_geometry` fills in cells_local_m for the bodies that need it. It is
    // static between steps, so a host asks for it when the set of bodies
    // changes and not on every frame.
    [[nodiscard]] std::vector<LiveBodyPose> poses(bool with_geometry = false) const;
    [[nodiscard]] double cellSize() const;

    // What happened in the step just taken. Cleared by the next step, so a host
    // reads it once per frame and narrates it. Contacts too gentle to be worth
    // mentioning are left out: `quiet_speed_m_s` is what counts as an arrival
    // rather than two things leaning on each other.
    // Every contact since the last forgetImpacts(), hardest first.
    //
    // Accumulated rather than per-step, because a host almost never steps once.
    // The playground asks for however many steps have gone by since the last
    // frame -- four, usually -- and a step only ever kept the contacts of the
    // step it just took, so three steps out of four were thrown away before
    // anyone could read them. Measured: a ball dropped on a pane reported four
    // contacts when stepped one at a time and NONE when stepped four at a time.
    // Everything that did not clear a threshold happened in silence.
    [[nodiscard]] std::vector<LiveImpact> impacts(double quiet_speed_m_s = 0.5) const;
    // Start a fresh batch. A host calls this when it has read what it needs,
    // which in practice is at the top of each batch of steps.
    void forgetImpacts();

    // What the last step hit hard enough to break, by name and once each.
    //
    // Includes anything carrying more than it can hold up -- see overloaded().
    // A host answers both the same way, because from the outside they are the
    // same question: this thing may come apart, do you want to know?
    [[nodiscard]] std::vector<std::string> breakable() const;

    // Everything carrying more than its material can take, as statics rather
    // than as impacts. See LiveOverload: this is the only way a shelf with too
    // much on it ever gets noticed, because nothing strikes it.
    //
    // Surveyed at a stride rather than every step -- load does not change in a
    // quarter of a second, and the survey is O(bodies^2) on axis-aligned boxes,
    // which is nothing for a room and not nothing at sixty times a second.
    [[nodiscard]] std::vector<LiveOverload> overloaded() const;

    // True when the last step was taken back because it would have broken
    // something. The world is one step short of that impact and the clock has
    // not moved, so a host that is drawing frames knows not to draw one, and
    // knows the next thing to do is decide whether to pay for the fracture.
    [[nodiscard]] bool steppedBack() const;

    // Put one object back into the lattice for `window_s` of simulated time and
    // replace it with whatever it became. Returns how many pieces it is now:
    // 1 means it took the hit and held.
    //
    // This is deliberately NOT automatic inside step(). A step costs about two
    // microseconds; this costs roughly the object's cell count times a third of
    // a millisecond, so a 500-cell object is about 165 ms and a 5,000-cell one
    // about 1.6 s. A host has to decide when to pay that -- on a worker, over a
    // held frame, or not at all -- and hiding it inside step() would take the
    // choice away and make a frame budget meaningless.
    //
    // The window is short because it can be: removed energy settles five to ten
    // times sooner than the piece count, and 3 ms covers it.
    std::size_t fracture(const std::string &name, double window_s = 0.003);

    // The same thing, without waiting for it.
    //
    // Working out a fracture costs a third of a second to a second, and that is
    // irreducible -- every way of making the run shorter changes the answer.
    // So the world does not stop for it: the run goes onto a worker, the pair
    // involved is pinned where it is, and everything else carries on. The room
    // keeps moving, the camera keeps moving, and half a second later the pieces
    // appear.
    //
    //     if (world.beginFracture(name)) {        // false: nothing to do
    //         while (!world.fractureReady()) world.step(dt);   // world runs on
    //         const std::size_t pieces = world.finishFracture();
    //     }
    //
    // Only one at a time. A second contact that needs the lattice while one is
    // pending has to wait, unless it shares no matter with the first -- which is
    // what `fracturePending` is for asking about.
    [[nodiscard]] bool beginFracture(const std::string &name, double window_s = 0.003);
    [[nodiscard]] bool fracturePending() const;
    [[nodiscard]] bool fractureReady() const;
    // What is being worked out, so a caller can tell whether a new contact
    // touches it.
    [[nodiscard]] std::string fractureSubject() const;
    std::size_t finishFracture();
    // What the last fracture() call turned out to be. The return value counts
    // pieces, which cannot tell "held exactly as it was" from "held, but bent
    // out of shape" -- both are one piece.
    [[nodiscard]] LiveOutcome lastOutcome() const;

    // Every moment the world waited, or was spared waiting, since the last
    // forgetDelays(). A host that never looks at this cannot tell a world that
    // is keeping up from one that is stalling twice a second.
    [[nodiscard]] std::vector<LiveDelay> delays() const;

    // The step the scene's lattice was built to take, which the stiffest,
    // lightest thing anywhere in it sets at open. A run is taken at its own
    // lattice's step instead (LiveDelay::step_s): no shorter than this, unless
    // heat has left its bodies lighter than they were cold.
    [[nodiscard]] double sceneLatticeStep_s() const;

    // Sweep up the loose pieces within `radius_m` of a point and say what they
    // were made of, added up by material.
    //
    // Only pieces: a "hull" is what something becomes when it breaks or bends,
    // so authored objects, anchored scenery and whatever is in a hand all stay
    // where they are. `largest_cells` is what counts as little -- a shard of
    // nine cells is debris, half a pane is not.
    //
    // This is also how a room that shatters stays inside the body budget, which
    // is what breaking depends on: sweeping the floor is the natural way to
    // keep the world small enough to keep working.
    [[nodiscard]] std::vector<LiveCollected> collect(const Vec3 &at, double radius_m,
                                                     std::size_t largest_cells = 64);
    void forgetDelays();
    // How far ahead to look for a collision that will need the lattice. Zero
    // turns the looking off. A ray per moving body is cheap -- 0.02 ms -- but
    // it is not free, so it is asked at a stride rather than every step.
    void foreseeCollisions(double horizon_s);
    // Let this contact pass. The world can move again without anything being
    // put back into the lattice.
    //
    // A step that would break something is taken back and time stops until the
    // host answers. Answering is what matters, not which way: a host that only
    // ever calls fracture has no way to say "not this one" and, if it says
    // nothing at all, the same contact is judged again on the next step and
    // taken back again, for ever.
    void declineBreak(const std::string &name);

    // Taking hold of something. A held body is pinned out of the simulation --
    // gravity and contacts stop moving it -- and goes exactly where it is put,
    // which is what makes dragging feel like holding rather than pushing.
    // Anchored scenery refuses to be picked up; it is the world, not a prop.
    [[nodiscard]] bool grab(const std::string &name);
    // How hard the hand can pull on something that is attached to other things,
    // in newtons. Everything an archer can do to a bow is bounded by this.
    //
    // A loose body is CARRIED and this does not apply to it: it goes exactly
    // where the hand goes, which is what makes dragging feel like holding. A
    // body on a joint is HAULED instead, and hauling is a force -- see
    // carryOrHaul for why it cannot be anything else.
    void setHandStrength(double newtons);
    [[nodiscard]] double handStrength() const;
    void moveHeld(const Vec3 &to_world_m);
    // Let go. The object rejoins the simulation from rest, so it falls from
    // where it was left rather than carrying the hand's speed.
    void release();
    [[nodiscard]] std::string held() const;
    // What is under a ray: the same question the solver answers, so a pointer
    // agrees with the physics instead of with a second copy of the shapes.
    // Costs no step; safe to ask every frame.
    // Where `name` would go set down on a surface at `on_world_m` -- a point a
    // host found with pick() -- turned `yaw_rad` about the vertical, and
    // whether it fits: what it would go into, what it would rest on, and how
    // much of its footprint has something under it. The engine's own shapes;
    // nothing moves. The first half of placing a thing (docs/inventory-and-
    // hands.md, section 5): the host carries it there if the person says so.
    // `onto` names what the point is on, as pick() found it -- empty for the
    // ground. It is lifted off that, and the ground, until it clears them (a
    // slope, a rounded top); anything else it would go into is in the way.
    [[nodiscard]] LivePlacement placement(const std::string &name, const Vec3 &on_world_m,
                                          double yaw_rad, const std::string &onto = {}) const;

    [[nodiscard]] LivePick pick(const Vec3 &from_world_m,const Vec3 &direction,
                                double max_distance_m = 1000.0) const;

    // Hang one named thing off another on a pin.
    //
    // The pin is given where it is in the world, right now, and is kept in both
    // bodies' own frames from then on. Limits are in degrees because that is
    // how anybody describes a door -- "it opens ninety degrees" -- measured
    // from where it is standing when the pin goes in, so a door built shut
    // swings 0..90 and one built open swings -90..0.
    //
    // Returns 0 if either name is not there, or if they are the same thing.
    unsigned hinge(const std::string &a, const std::string &b,
                   const Vec3 &point_world_m, const Vec3 &axis_world,
                   double lower_deg = -180.0, double upper_deg = 180.0,
                   double friction_torque_n_m = 0.0);

    // Let one named thing slide along a line fixed in another.
    //
    // The same idea as a pin, one degree of freedom the other way round: the
    // two are locked in rotation and free to move along one axis. A portcullis
    // in its grooves, a sliding door, a bolt going across a door.
    //
    // And, like a pin, nothing is played. A portcullis that has been hauled up
    // and let go FALLS, because gravity is still acting on a body that is free
    // to move down its own axis -- which is the thing that makes a winch worth
    // having and a prop useless.
    //
    // Travel is metres either side of where it is built, so a grate built down
    // in its gateway has 0..2 of lift and one built up has -2..0 of drop.
    // `friction_n` is what it takes to start it moving: a heavy grate in dry
    // stone grooves does not run freely, and this is the difference between a
    // gate that stays where you leave it and one that drops the moment you stop
    // hauling.
    //
    // Returns 0 if either name is not there, or if they are the same thing.
    unsigned slide(const std::string &a, const std::string &b,
                   const Vec3 &point_world_m, const Vec3 &axis_world,
                   double lower_m = -1.0, double upper_m = 1.0,
                   double friction_n = 0.0);

    // Tie one named thing to another, so that they may be up to `length_m`
    // apart and no further.
    //
    // That one asymmetry is the whole of what makes a rope a rope: it pulls
    // and it does not push. Below the length the link does nothing at all, so
    // slack really is slack.
    //
    // A rope or a chain is made of these -- a run of small bodies, each tied
    // to the next -- rather than being a special kind of object. Which means it
    // hangs in a catenary because its own segments are heavy, drapes over what
    // it touches because its segments collide, and can be cut anywhere along
    // its length, because every link is separately real.
    //
    // `breaking_tension_n` is what it takes to part it, and zero means it never
    // parts. A link that parts is reported once with `attached` false, exactly
    // like a gate coming off its hinges, because a host that drew a rope has to
    // stop drawing it.
    //
    // `length_m` of zero means "as they stand": the distance between the two
    // points given, which is what you want when tying a rope that is already
    // laid out.
    unsigned tie(const std::string &a, const std::string &b,
                 const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                 double length_m = 0.0, double breaking_tension_n = 0.0);

    // Reeve a rope from one named thing, over two fixed points, to another.
    //
    // A hoist. Pull one end down and the other comes up.
    //
    // `ratio` applies to B'S RUN, and which end is not a detail: because b's
    // length is what gets multiplied, b moves 1/ratio as far as a does and feels
    // ratio times the cable tension. The advantage is on b's side --
    //
    //     hang the LOAD at b, and a counterweight of load/ratio balances it.
    //
    // At ratio 2 that is a block and tackle: half the weight holds the load and
    // the load rises half as far as the counterweight falls. With the load at
    // `a` you have the same machine backwards and need TWICE the weight, which
    // is a real thing to build and a surprising thing to build by accident.
    //
    // This is the IDEAL pulley, and the difference matters enough to say out
    // loud. What the engine holds is a relationship between lengths:
    //
    //     |a - over_a|  +  ratio * |b - over_b|  <=  length
    //
    // There is no wheel, so no wheel inertia and no bearing friction. There is
    // no wrap, so the rope cannot slip, cannot come off its sheave, and does
    // not rub. What you get is the mechanism working exactly.
    //
    // The physical alternative is already here and costs a body per segment: a
    // run of things tied with tie(), draped over something solid. That one has
    // real wrap, real friction and real slip. Reach for this when you want a
    // hoist that works; reach for that when the rope itself is what is being
    // watched.
    //
    // Like a rope it pulls and does not push -- slack on one side is just slack.
    // `length_m` of zero means "as it is rove": what the two runs add up to now.
    // Fix one named thing to another: a peg, a bracket, a nail, a door catch,
    // a locking bar, a rope anchor.
    //
    // All six degrees of freedom are held, so the two move as one piece, and
    // whatever their relative pose is right now is the pose they keep. That is
    // what "defined alignment" means here -- it is defined by where they are
    // when the peg goes in, which is how a peg works.
    //
    // Two strengths, because a peg pulled straight out and a peg sheared
    // sideways fail at different loads and it is rarely the same number.
    // `axis_world` is the direction the peg points: tension is along it, shear
    // is across it. Either exceeded and the fixing parts, reported once with
    // `attached` false, exactly like a rope.
    //
    // Zero means it never lets go on its own. That is a weld, and welds are a
    // real thing to want. Releasing it on purpose is unhinge(), which is what a
    // latch does -- and doing so changes what the assembly IS, which is the
    // whole point of a latch.
    // Put an elastic element between two named things: a bow limb, a spring, a
    // bent plank -- anything that stores energy by being deformed.
    //
    // A DECLARED SIMPLIFIED MODEL, and worth naming: an ideal linear spring.
    //
    //     force  = stiffness * (length - rest)
    //     stored = stiffness * (length - rest)^2 / 2
    //
    // Hooke's law with viscous damping. It has no mass of its own, no internal
    // stress, no yield, no hysteresis, and it does not care which way it bends;
    // a real bow limb has all of those. What it does have is the property
    // everything built on it depends on -- work in is energy stored, energy
    // stored is energy back, minus what the damping takes -- and that is
    // measured rather than asserted.
    //
    // It pushes as well as pulls. A thing that only pulls is a rope: use tie().
    //
    // `rest_m` of zero means "as it stands", which is what you want for
    // something built already relaxed. `damping_n_s_m` is the declared loss.
    unsigned spring(const std::string &a, const std::string &b,
                    const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                    double rest_m = 0.0, double stiffness_n_m = 1000.0,
                    double damping_n_s_m = 0.0);

    // A fixing: a peg, a bracket, a catch (LiveJoint). With comes_off_n above
    // zero it is ONE-WAY along `axis_world`, which then points the way b comes
    // off a -- an arrow on a string, a sling's ring on its release pin. Pushed
    // back into a, b is in contact and takes whatever the push is; pulled along
    // the axis it is held with up to comes_off_n, and pulled harder it slides
    // off, reported once with `attached` false and a delay that says it "came
    // off". It has no tension strength, so holds_tension_n must be zero with it.
    unsigned fix(const std::string &a, const std::string &b,
                 const Vec3 &point_world_m, const Vec3 &axis_world,
                 double holds_tension_n = 0.0, double holds_shear_n = 0.0,
                 double comes_off_n = 0.0);

    unsigned reeve(const std::string &a, const std::string &b,
                   const Vec3 &point_a_world_m, const Vec3 &point_b_world_m,
                   const Vec3 &over_a_world_m, const Vec3 &over_b_world_m,
                   double ratio = 1.0, double length_m = 0.0);
    // Every pin in the scene, with where each has turned to.
    [[nodiscard]] std::vector<LiveJoint> joints() const;
    // How hard it is to move. A stiff hinge holds a door where it is left.
    void setJointFriction(unsigned joint, double friction_torque_n_m);
    // Take the pin out. What hung on it falls.
    void unhinge(unsigned joint);

    // ---- machines: stores of energy and motors (docs/machine-world.md) ----
    //
    // A store of energy in a named body, or in nothing: what it can hold and
    // what it holds, joules; its voltage; and the most power it gives, zero
    // for no limit but its charge. Returns its id, above zero, or 0 if the body
    // is not there or the numbers are not a store's.
    unsigned energyStore(const std::string &name, const std::string &body, double capacity_j,
                         double charge_j, double voltage_v = 24.0, double max_power_w = 0.0);
    // A motor on a pin, drawing on a store. Returns its id, above zero, or 0 if
    // the pin or the store is not there, the pin is not a hinge, the pin has a
    // motor already, or the numbers are not a motor's.
    unsigned motor(unsigned joint, unsigned store, double stall_torque_n_m, double no_load_rad_s,
                   double brake_torque_n_m = 0.0);
    // What a motor is told: a command from -1 to 1, and whether its brake is
    // on. The brake is friction on the pin, so it holds only while the motor
    // is not driving -- a command of zero. False if there is no such motor.
    // A motor with a controller is worked by it: this tells the controller
    // instead -- power on, the command's way as its direction (0 to stop) and
    // its size as the setting -- so the controller's limits still hold.
    bool driveMotor(unsigned motor, double command, bool brake = false);
    [[nodiscard]] std::vector<LiveEnergyStore> energyStores() const;
    [[nodiscard]] std::vector<LiveMotor> motors() const;
    // Attach a bounded DC/thermal circuit to one existing store and ALL its
    // motors. Additive only: inspection/reopening cannot reset state.
    // Returns an id (1-based); throws on invalid/unsupported declarations.
    unsigned circuit(const std::string &declaration);
    void circuitSwitch(unsigned circuit, const std::string &branch, bool closed);
    [[nodiscard]] std::string circuits() const;
    // A controller for a motor (LiveControl): a hoist's when `rope` is a rope
    // on a drum that the motor's pin turns -- `top_out_m` and `bottom_out_m`
    // the rope out at the two ends of its travel, the top the less -- and a
    // shaft's when `rope` is 0. Returns its id, above zero, or 0 when the motor
    // or the rope is not there, the rope's drum is not on the motor's pin, the
    // motor has a controller already, or the travel is not a hoist's. It starts
    // off, its motor stopped on its brake.
    unsigned control(const std::string &name, unsigned motor, unsigned rope = 0, double top_out_m = 0.0,
                     double bottom_out_m = 0.0);
    // What a controller is told, by a sender and that sender's count. What is
    // left out stays as it was: states are said outright, never toggled.
    struct ControlCommand {
        std::string sender;
        std::uint64_t seq{};
        std::optional<bool> power;
        std::optional<int> direction;     // -1, 0 or 1
        std::optional<double> setting;    // 0 to 1
    };
    // "applied", or "stale" when that sender has had a command as new or newer
    // applied already, and nothing changes. Anything else is why it is not a
    // command: no such controller, a direction other than -1, 0 or 1, a
    // setting outside 0 to 1.
    std::string operate(unsigned control, const ControlCommand &command);
    [[nodiscard]] std::vector<LiveControl> controls() const;
    // How hard a named thing is to turn about an axis through its centre of
    // mass, kg m^2, from the inertia the solver uses. Zero if it is not there.
    [[nodiscard]] double inertiaAbout(const std::string &name, const Vec3 &axis_world) const;
    // A rope that winds onto a turning drum (rigid/DrumRope.hpp): from the
    // drum -- a thing that turns on a pin of its own -- to a load, made off on
    // the load at load_point_world_m. The drum's centre and axle and the
    // radius the rope lies at are given as things stand now. `winds` is +1 if
    // the drum turning the positive way about its axle takes rope on, -1 if
    // the other way does. length_m is the whole rope; out_m is how much of it
    // is off the drum, and zero means "as it hangs" -- exactly the span from
    // the drum to the load. As many turns as there is rope, and it pulls and
    // never pushes. Returns 0 if either name is not there, they are the same
    // thing, or the numbers are not a drum's.
    unsigned drum(const std::string &drum, const std::string &load, const Vec3 &centre_world_m,
                  const Vec3 &axis_world, double radius_m, const Vec3 &load_point_world_m, int winds,
                  double length_m, double out_m = 0.0);

    // ---- heat, chemistry and gas ----------------------------------------
    //
    // The thermochemical network this world runs (thermo/ThermoWorld.hpp), or
    // null when nothing in it has declared any. It steps with the world and
    // its state is part of the reversible step: a step that is taken back
    // takes back the fuel it burned, the gas it made and the heat it moved, or
    // the retry would burn them twice. Pressure boundaries push on bodies
    // inside the same trial and are charged exactly the work those pushes did.
    [[nodiscard]] const thermo::ThermoWorld *thermo() const;
    // Declare into the running world: {"contents": [{"body": ...}],
    // "gas_regions": [...], "heaters": [...]} -- a heater's start is from now.
    void declareThermo(const std::string &json);
    // Heat a body or a gas region from now, for `seconds`. Returns its id.
    unsigned heat(const std::string &target, double power_w, double seconds);
    void setVent(const std::string &region, bool open);
    // Bodies, regions and the ledger as JSON; with `with_model`, also every
    // substance and reaction with its provenance, and what is not modelled.
    [[nodiscard]] std::string thermoReport(bool with_model = false) const;
    // The kinetic and gravitational energy of every body, from the solver's own
    // masses: the mechanical view beside the thermochemical ledger. Boundary
    // work is what passes between the two.
    [[nodiscard]] double mechanicalEnergyJ() const;

    // ---- heat and strength (docs/thermal-mechanics.md) -------------------
    //
    // Temperature, composition and what has burned change what a body can
    // carry, by a declared law per material (thermo/ThermalMechanics.hpp). The
    // failures are the ones this world already had: a joint parts when the
    // load the solver measures passes what it can still take, and a beam is
    // offered as overloaded when the bending in it passes what its section can
    // still take. Heat changing either is itself a reason to ask again, while
    // nothing moves.
    //
    // What heat, composition and burning have done to each body the thermal
    // network holds, and to every body a joint is made of.
    [[nodiscard]] std::vector<LiveMaterialState> materialStates() const;
    // What statics said, latest per body (LiveStatics), and the bodies that
    // burned away entirely, in order (LiveBurnedAway).
    [[nodiscard]] std::vector<LiveStatics> statics() const;
    [[nodiscard]] std::vector<LiveBurnedAway> burnedAway() const;
    // Say which of a joint's two bodies it is made of (LiveJoint::member): its
    // strength (a fixing, a link) or its stiffness (an elastic) follows that
    // body's law from now on. A declared strength of zero becomes the member's
    // own section times its material's strength. "" goes back to the declared
    // numbers. False for a pin, a slide or a pulley, which have no strength to
    // lose here, and for a name that is not one of the joint's two ends.
    bool setJointMember(unsigned joint, const std::string &member);
    // All of it as JSON: the bodies, every joint made of a member, what
    // elastics have handed over as heat; with `with_laws`, the laws, where
    // their numbers come from, and what is not modelled.
    [[nodiscard]] std::string mechanicsReport(bool with_laws = false) const;

    // ---- rolling resistance (docs/rolling-resistance.md) ------------------
    //
    // What rolling resistance is doing, as JSON: every contact of a round body
    // in the last step -- the ball, what it rolls on, the solver's normal
    // force there, the pair's coefficient, the most the couple can be and what
    // it was, whether the ball is held still -- and the energy it has taken
    // out of the motion, in all and by ball: a declared loss, like a cut's
    // work, so the kinetic energy a rolling ball loses is accounted for.
    [[nodiscard]] std::string rollingReport() const;
    [[nodiscard]] double rollingLossJ() const;
    // The materials, the floor and the ground's surfaces, each with its
    // friction and its own share of rolling resistance, marked sourced or a
    // demonstration value and saying where it came from. Needs no world.
    [[nodiscard]] static std::string materialsJson();

    // ---- terrain and water ------------------------------------------------
    //
    // The ground and the rivers on it (terrain/Environment.hpp), or null when
    // the scene declares neither. The water's pressure and drag are pushed
    // onto bodies inside the reversible step, so a step taken back takes them
    // back; the water, the ground's settling and its colliders are brought up
    // to the world's clock after the step is accepted.
    [[nodiscard]] const terrain::Environment *environment() const;
    // The rectangle of ground points an edit or a slump has changed since this
    // was last asked, for a host that sends a picture of the ground: nothing
    // when nothing changed, and nothing in a world without ground.
    terrain::TerrainField::Rect takeChangedGround();
    // Dig a trench from a to b (x, z), `width_m` wide and `depth_m` below the
    // ground as it stands. Rebuilds exactly the colliders it changed and wakes
    // exactly what they held up, here, between steps.
    terrain::EditEffect dig(double ax, double az, double bx, double bz, double width_m, double depth_m);
    // How much dug ground the person can carry (terrain::Environment). A world
    // with no ground has nothing to dig and takes any limit.
    void setCarryLimitKg(double kg);
    // Heap material up around a point; it settles to the slope it can hold.
    terrain::EditEffect deposit(double x, double z, double radius_m, double sand_m3, double soil_m3);
    [[nodiscard]] std::string withdrawGround(double sand_m3, double soil_m3);
    void returnGround(double sand_m3, double soil_m3);
    // Cut a block out of bare rock, `height_m` tall (rounded to whole cells).
    // The ground loses it now; the host adds it as a body in the scene it
    // opens next -- a body cannot join a running world -- and until then the
    // ledger has it as cut. Its sides must be whole cells, so the footprint
    // is refused, with the sizes that would do, when they are not.
    std::optional<terrain::CutBlock> cutBlock(double x, double z, int cells_x, int cells_z, double height_m,
                                              std::string *why = nullptr);
    // A river's discharge, from now: a flood, a drought.
    bool setDischarge(const std::string &river, double discharge_m3_s);
    // Everything about the ground and the water as JSON, with `full` adding
    // the model's provenance and what is not modelled.
    [[nodiscard]] std::string environmentReport(bool full = false) const;
    // The water as it stands, for carrying into a world opened again.
    [[nodiscard]] std::string environmentState() const;
    // Ground and water at a point.
    [[nodiscard]] std::string survey(double x, double z) const;
    // How many bodies the rigid solver is stepping right now.
    [[nodiscard]] unsigned awakeBodies() const;

    // ---- Blades (docs/cutting-model.md) --------------------------------
    //
    // Give a body an edge. Everything is given where it is in the world RIGHT
    // NOW and kept in the body's own frame from then on, like a pin:
    //
    //   heel, tip      the edge, a straight line, heel to point. Both ends must
    //                  lie on the body's matter -- an edge floating in the air
    //                  next to a body is refused.
    //   facing         the way the edge faces: squared up against the edge
    //                  line, so it only has to be roughly perpendicular.
    //   thickness_m    across the flats
    //   edge_radius_m  how sharp: the edge's contact width is twice this
    //   bevel_deg      the included angle of the edge wedge
    //   grip           where a hand holds it
    //
    // Returns the blade's id, or 0 if it cannot be made.
    unsigned blade(const std::string &body, const Vec3 &heel_world_m,
                   const Vec3 &tip_world_m, const Vec3 &facing_world,
                   double thickness_m, double edge_radius_m, double bevel_deg,
                   const Vec3 &grip_world_m);
    // Why the last blade() returned 0, in words a caller can act on: not on
    // its matter, facing into it, facing along the edge, out of range.
    const std::string &bladeRefusal() const;
    [[nodiscard]] std::vector<LiveBlade> blades() const;
    // Every edge contact since forgetCuts(), in the order they began. Open
    // ones are still going and keep changing.
    [[nodiscard]] std::vector<LiveCut> cuts() const;
    void forgetCuts();

    // ---- Tools that work the ground (docs/ground-work.md) ----------------
    //
    // Give a body a point that can go into the ground. Like an edge, it is
    // given where it is in the world right now and kept in the body's own
    // frame:
    //
    //   tip            the working end, on the body's matter
    //   pointing       the way the point goes in, out of the body at the tip
    //   width_m        across the edge the point comes to
    //   thickness_m    its thickness where it stops getting thicker
    //   angle_deg      the included angle it comes to its tip at
    //   length_m       how much of the tool is point: the rest of it meets the
    //                  ground as a rigid surface, and stops there
    //   grip           where a hand holds it
    //
    // From then on the body collides as its cells rather than its hull, so a
    // pick's crook is open. Returns the point's id, or 0 with the reason in
    // toolPointRefusal().
    unsigned toolPoint(const std::string &body, const Vec3 &tip_world_m, const Vec3 &pointing_world,
                       double width_m, double thickness_m, double angle_deg, double length_m,
                       const Vec3 &grip_world_m);
    [[nodiscard]] const std::string &toolPointRefusal() const;
    [[nodiscard]] std::vector<LiveToolPoint> toolPoints() const;
    // A bounded tool action (LiveStrike) with the tool in the hand, which has
    // to be WIELDED -- held by its grip. Returns false with the reason when it
    // cannot be made: nothing wielded, no point on it, nothing to lever.
    [[nodiscard]] bool strike(const LiveStrike &strike, std::string &why);
    // Every meeting of a point with the ground since forgetGroundWork(), in
    // the order they began. Open ones are still going.
    [[nodiscard]] std::vector<LiveGroundWork> groundWork() const;
    void forgetGroundWork();

    // Take hold of something the way a person holds a sword: at a point on
    // it, with a hand whose force and torque are BOUNDED. See
    // docs/cutting-model.md section 7. moveHeld() says where the grip should
    // be and aimHeld() which way the body should face; the hand pulls and
    // turns towards both with what it has, and what the body meets can slow
    // it, turn it aside or stop it.
    //
    // This is not grab(). grab() carries a loose body exactly where it is put,
    // which is placement -- an editor's move -- and stays exactly that.
    [[nodiscard]] bool wield(const std::string &name, const Vec3 &grip_world_m);
    // In the frame poses() reports: asking a thing to face the way it is said
    // to face leaves it as it is, however it was built turned.
    void aimHeld(const Quat &orientation_world);
    [[nodiscard]] bool wielding() const;
    // The most torque the hand can put on what it wields, newton metres.
    void setHandTorque(double newton_metres);
    [[nodiscard]] double handTorque() const;
    // The moving mass of the hand and arm, kilograms: what the strength has to
    // get going along with whatever a stroke throws. 2 kg unless told
    // otherwise, a demonstration value. It is why a light ball leaves a hand
    // faster than a heavy one even when neither is too heavy to hold.
    void setHandMass(double kilograms);
    [[nodiscard]] double handMass() const;

    // The hand's own motions (LiveStroke). A stroke needs a hand that PULLS:
    // something wielded, or something hauled because it is attached. A carried
    // body goes where it is put and is never pushed, so it is refused, with the
    // reason in `why`. A new stroke replaces one already running, and moveHeld
    // takes the hand back from one: whoever moves the hand is driving it.
    [[nodiscard]] bool stroke(const LiveStroke &stroke, std::string &why);
    void cancelStroke();
    [[nodiscard]] LiveHand hand() const;
    // Previews, for aiming. Neither changes the world, and both are bounded:
    // at most ten seconds of flight, and a stroke at most its own give_up_s.
    [[nodiscard]] LiveStrokePreview previewStroke(const LiveStroke &stroke, double dt_s,
                                                  double horizon_s) const;
    [[nodiscard]] LiveFlight previewFlight(const Vec3 &from_world_m, const Vec3 &velocity_m_s,
                                           double horizon_s, const std::string &ignoring) const;

    // Set a thing aside -- put in a bag, say -- and bring it back as it was.
    // Parked, it is out of the world: nothing meets it, no step moves it, and
    // poses() leaves it out, so a host stops drawing it. But it is not gone: its
    // matter, its cells, its dents and cuts and what it is made of stay with it,
    // and unpark() puts that same thing back, at rest, where it is asked to be,
    // facing as poses() would say it faces. Between steps only. Refused, with
    // why, for what cannot be set aside as it is: anchored scenery, a thing on a
    // joint, a thing breaking, a thing being cut or cutting, a tool whose point
    // is in the ground, a gas's piston. A thing in the hand is let go first.
    [[nodiscard]] bool park(const std::string &name, std::string &why);
    [[nodiscard]] bool unpark(const std::string &name, const Vec3 &at_world_m, const Quat &facing_world,
                              std::string &why);
    [[nodiscard]] bool parked(const std::string &name) const;

    // ---- a world that is kept: a restart gives back the room as it stood ----
    //
    // The whole of the world as it stands, as JSON ("banjo.world.v1"), for
    // opening the same scene again later -- after the process holding it has
    // gone. It carries every body by its cells (the scene's own node numbers)
    // and their offsets in its frame, where it is and how it moves, whether it
    // is asleep or set aside; the severed bonds and permanent sets; dents,
    // cuts, joints, edges, tool points, the hand and the counters; the water;
    // and what it does not carry (notKept()). `spec_digest` is the host's own
    // word for the scene it opened, carried as it is.
    //
    // Empty, with `why`, while anything is in flight that a saved world cannot
    // carry: a break being worked out, something cut through and about to come
    // apart, an edge in a cut, a tool's point in the ground, a stroke of the
    // hand. A host keeps the last one it was given, and asks again later.
    [[nodiscard]] std::string snapshot(std::string &why, const std::string &spec_digest = {}) const;
    // The scene opened again from a saved world. The scene builds the same
    // cells under the same numbers, so each saved body is made again from its
    // own cells, at its saved centre of mass facing the world's way -- which
    // puts its cells exactly where its frame had them, so everything kept in its
    // frame (dents, cuts, joint points, edges, tool points, the grip) is where it
    // was -- and then turned and set moving as it was. A saved world that does
    // not fit (another scene, or a build that lays the cells out another way:
    // the lattice's fingerprint says) or cannot be read opens the scene as
    // open(request) does, and restored() says so and why. Throws only when the
    // scene itself cannot be opened.
    [[nodiscard]] static std::unique_ptr<LiveWorld> open(const TileImpactRequest &request,
                                                         const std::string &snapshot);
    // The scene opened carrying a saved world whose scene has changed since --
    // the room's chat added, moved or took something away, or a thing was
    // stood up. Each authored thing whose definition is unchanged comes back
    // exactly as it was saved: the scene builds each authored thing's cells on
    // their own, and lays them end to end, so an unchanged thing's cells are
    // its own numbers moved by where its part now begins, and its pieces, dents
    // and cuts are found again under those. What the change touched is as the
    // scene has it; `carry` says which of its pins, stores, motors, edges and
    // points the host still declares the same way. restored() says what came
    // back and what did not, thing by thing ("carried"). A saved world that
    // cannot be carried at all opens the scene as it is, and says why.
    [[nodiscard]] static std::unique_ptr<LiveWorld> open(const TileImpactRequest &request,
                                                         const std::string &snapshot, const LiveCarry &carry);
    // Every pin, store, motor, edge and point a saved world holds, for a host
    // whose declarations have not changed since it was saved.
    [[nodiscard]] static LiveCarry carryAll(const std::string &snapshot);
    // What opening from a saved world gave back; an empty tier for a world
    // opened from its scene.
    [[nodiscard]] const LiveRestore &restored() const;
    // What a saved world does not carry yet, in words.
    [[nodiscard]] static std::vector<std::string> notKept();
    // What a world carried into a changed scene does not carry, in words.
    [[nodiscard]] static std::vector<std::string> notCarried();

private:
    // A saved world as read back, and the one open both ways go through.
    struct Saved;
    // With `carry`, the saved world is carried into a scene that has changed.
    [[nodiscard]] static std::unique_ptr<LiveWorld> openFrom(const TileImpactRequest &request,
                                                             const Saved *saved, const LiveCarry *carry = nullptr);
    // After a saved world that did not fit: each thing still whole and its
    // authored self put back where it was left (LiveRestore "poses").
    void placeWhereLeft(const Saved &saved, const std::string &why);
    // Each saved thing still whole and its authored self, on no joint and
    // carrying no edge or point, put back where it was left -- only those named
    // in `only`, when it is given. The names of those that were.
    std::vector<std::string> putBackWhereLeft(const Saved &saved, const std::set<std::string> *only = nullptr);
    // Every body as the water sees it: shape, where it is, how it moves.
    [[nodiscard]] std::vector<water::BodyInWater> waterBodies();
    // Every body as the network sees it: where it is, how it is turned, what
    // it weighs and how much surface it has.
    [[nodiscard]] std::vector<thermo::BodyShape> thermoShapes() const;
    [[nodiscard]] double hullArea(std::size_t body) const;
    thermo::ThermoWorld &ensureThermo();
    // After an accepted step: the heat paths again at a stride, and the rigid
    // bodies told what they weigh now.
    void settleThermo();
    // What one body can carry across a load running along `load_world` -- its
    // longest axis when null. See materialStates.
    [[nodiscard]] LiveMaterialState materialStateOf(std::size_t body, const Vec3 *load_world) const;

    // ---- one material state (docs/thermal-mechanics.md) --------------------
    //
    // A body's material field: the thermal network's state for it, laid over
    // its reference box. Empty when the network does not hold it or its
    // material has no law -- it is then exactly as it was built.
    [[nodiscard]] std::optional<thermo::MaterialField> fieldOf(std::size_t body) const;
    // What a body's matter is measured against, and what has been done to its
    // shape because of it (defined in LiveWorld.cpp). Made the first time
    // anything asks, from the body as it is then, and kept.
    struct MatterRecord;
    MatterRecord &recordOf(std::size_t body) const;
    // The box the field is measured against, for the survey and the section:
    // as authored, never what is left of it.
    [[nodiscard]] Vec3 referenceBoxOf(std::size_t body) const;
    // A point in the body's own frame, in its reference box's frame.
    [[nodiscard]] Vec3 inReference(std::size_t body, const Vec3 &local_m) const;
    // Give an island's cells and bonds the field of the body each belongs to.
    // Called in prepared() before its cells are moved into the island's frame.
    struct HeatedCells;
    [[nodiscard]] std::unique_ptr<HeatedCells> heatedCellsOf(const std::vector<std::size_t> &bodies) const;
    // `bonds` false weighs the cells and leaves the bonds as they were: a body
    // rebuilt because cells burned away keeps its char in place until
    // something actually tests it.
    void heatIsland(FragmentLattice &island, const HeatedCells &heated, const std::string &name,
                    bool bonds);
    // Make every heated body's shape, mass, cells and attachments follow what
    // is left of its matter. At the thermal network's stride.
    void reviseMatter();
    // A body whose load-bearing matter is gone: it leaves the world, and what
    // it held (its residue) leaves the thermal network with it, on the ledger.
    void burnAway(std::size_t body, const std::string &why);
    // A piece whose cells have burned away is rebuilt from the cells it has
    // left -- as more than one if they no longer join. Returns how many.
    std::size_t reformFromCells(std::size_t body);
    // The bond summary and admission limits of a heated body, from its field.
    void refreshHeatedBonds(std::size_t body, const thermo::MaterialField &field);
    // Every joint made of a member brought up to what its member is now, with
    // a re-check (both ends woken) wherever that moved, and a survey asked for
    // wherever a heated beam's section moved. Outside the reversible trial:
    // it runs after a step has been accepted.
    void refreshMechanics();
    LiveWorld();
    // The cutting model, in the two halves a step has. Before it: find every
    // edge about to meet or already in matter, decide what each meeting is,
    // and put a kerf constraint where an edge has bitten. After it: read what
    // each constraint took, advance the kerfs by exactly that much area, sever
    // what they crossed, and replace whatever came apart with its pieces.
    // Both run outside the reversible trial, because both change the world's
    // configuration and a trial forbids that.
    void prepareCuts(double dt_s);
    void settleCuts(double dt_s);
    // Replace a body whose severed bonds leave it in more than one piece.
    std::size_t splitCut(std::size_t which);
    // Reads the contacts of the step just taken and answers whether any of them
    // could break what it hit. Called inside a reversible trial, so it must not
    // change the world.
    [[nodiscard]] bool judgeStep();
    // Look ahead for a collision that will need the lattice, and write down how
    // much warning there is.
    void foresee();
    // The three phases of a fracture. Only `work` takes any time, and it is the
    // only one that touches nothing shared -- everything else reads and writes
    // the rigid world.
    struct Pending;
    // A collision that has not happened yet, described as it is expected to be.
    //
    // The lattice run costs about as long as a two-metre fall takes, and until
    // now it started when the two things touched -- so you dropped something,
    // it landed, and then it sat there for most of a second before it came
    // apart. The engine can see the collision coming hundreds of milliseconds
    // out. This is what it sees, in the form prepare() needs to start early.
    struct Foresight {
        std::size_t struck{};
        std::size_t striker{static_cast<std::size_t>(-1)};
        RigidSnapshot striker_state{};
        double arrival_speed_m_s{};
        // Whether that arrival clears the struck body's BREAKING bar and not just
        // its denting one. The struck body may come apart in the run only if it
        // does, as a body may at a contact only if the contact does.
        bool would_break{};
    };
    void prepare(const std::string &name, double window_s);
    [[nodiscard]] std::unique_ptr<Pending> prepared(const std::string &name, double window_s,
                                                    const Foresight *guess = nullptr);
    // Start the run for a collision that is still coming, from where the two
    // things are going to be rather than where they are.
    void guessAhead(const Foresight &guess, const std::string &name);
    // What would happen if the thing in the hand were let go right now. The
    // warning a fall gives can never be longer than the fall, and below about
    // three and a half metres that is shorter than the run -- but somebody
    // lining up a drop has already given us seconds of it.
    void guessWhatIsHeld(std::set<std::string> &still_coming);
    // Is the run already going for exactly this impact? Adopting it is what
    // turns most of a second of waiting into none.
    [[nodiscard]] bool adoptGuess(const std::string &name);
    void dropGuess(const char *why);
    // A break detected while another is being worked out. Captured here and
    // now -- this is the only moment that still has the closing speed in it --
    // so the world can take the step instead of stopping until the first run
    // finishes. See LiveWorld.cpp; it cost 756 ms of a stopped clock, twice, in
    // one cascade before this existed.
    void queueBreaks();
    void startNextQueued();
    // Follow every queued job's indices through a rearrangement of the body
    // table, given the names that were there before it. By NAME, because a body
    // that came through whole keeps its name and is re-appended at the end --
    // so counting erasures below an index gets it wrong by one and the next
    // apply destroys the body next door.
    void restackQueue(const std::vector<std::string> &before);
    void repin();
    // Work out what everything is carrying and whether it can hold it.
    void surveyLoads();
    // Where the hand puts what it is holding: carried if it is loose, hauled
    // along its joint if it is attached to something. See the definition; the
    // hand writes the world from two places and both have to agree.
    void carryOrHaul(double dt_s);
    // The hand's side of a step. Before it: where a stroke wants the grip this
    // step, and where the grip is, for the work. After a KEPT step: the work
    // done, how far a stroke has got and whether it is over. A step that is
    // taken back undoes the first half and never gets the second.
    void beginHandStep(double dt_s);
    void endHandStep(const Vec3 &grip_force_n, const Vec3 &grip_torque_n_m, double dt_s);
    void abandonHandStep();
    // Whether what the hand holds is attached to something, which makes holding
    // it a haul rather than a carry.
    [[nodiscard]] bool hauling() const;
    // Where the grip is and how fast it is moving: the wielded point, or the
    // centre of mass of anything carried or hauled.
    [[nodiscard]] std::pair<Vec3, Vec3> gripNow() const;
    // Part every link carrying more than it can take.
    //
    // Checked after the step rather than inside it, because a link's tension is
    // the impulse the solver just applied and that does not exist until the
    // step has run. One step of overload before it parts is 4 ms at a live
    // rate, which is not visible; a rope that never parts is.
    void partOverloadedLinks();
    // Put the pins back after the body table has been rearranged.
    //
    // Every body in an island is destroyed and rebuilt when anything in it
    // breaks, so the engine-level constraints are gone even for the bodies that
    // came through whole -- and the ones that did break have new names. This
    // finds each pin's wood again by NAME first and, failing that, by looking
    // for the piece that now carries the pin, which is the physically honest
    // answer: the pin stays with whichever lump of door is still at it --
    // around it, or beside it when the pin was put on the face of the post.
    void rehangJoints();
    // Which piece of a broken body, if any, now carries a pin: the nearest,
    // provided it stands no further off than the body did. Used to follow a
    // pin into the piece it ended up with. See the definition.
    [[nodiscard]] std::size_t bodyHolding(const Vec3 &point_world_m,
                                          const std::string &was_called,
                                          double &stand_off_m) const;
    // Take bodies out of the world and out of every table parallel to it,
    // fixing up the hand and any fracture holding an index.
    void dropBodies(const std::vector<std::size_t> &which);
    static void work(Pending &job);
    std::size_t applyPending();
    // What the tool-terrain process is handed at each call: this world, seen
    // through a few questions it may ask (ToolTerrain.hpp).
    [[nodiscard]] ToolTerrainHost toolHost() const;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo::fastlattice
