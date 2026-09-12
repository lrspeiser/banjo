#pragma once

#include "core/Math.hpp"
#include "core/RigidPrimitive.hpp"
#include "core/Plane.hpp"
#include "core/Types.hpp"
#include "fracture/ActiveMatter.hpp"
#include "fracture/FragmentGeometry.hpp"
#include "fracture/ImpactEvent.hpp"
#include "material/Material.hpp"
#include "physics/SphereMaterialContact.hpp"
#include "physics/MechanicalAccounting.hpp"
#include "physics/CohesiveInterface.hpp"
#include "physics/CohesiveRigidPair.hpp"
#include "physics/RigidAttachment.hpp"

#include <memory>
#include <functional>
#include <vector>

namespace banjo {

struct RigidSurfaceDescription {
    SupportPlaneFrame frame{};
    MaterialDefinition material{};
    double half_length_tangent_m{10.0};
    double half_length_bitangent_m{5.0};
    double thickness_m{0.5};
};

struct RigidBallDescription {
    MatterBodyId body_id{kInvalidMatterBodyId};
    double radius_m{};
    MaterialDefinition material{};
    Vec3 position_world_m{};
    Vec3 linear_velocity_m_s{};
    Vec3 angular_velocity_rad_s{};
    double mass_override_kg{};
    double sphere_inertia_factor{0.4};
    bool defer_brittle_contacts_to_material{};
};

struct RigidBoxDescription {
    MatterBodyId body_id{kInvalidMatterBodyId};
    Vec3 dimensions_m{};
    MaterialDefinition material{};
    RigidSnapshot state{};
    bool fixed{};
};

struct RigidCompoundPart { RigidPrimitive geometry; Vec3 center_local_m; };
struct RigidCompoundDescription {
    MatterBodyId body_id{};
    std::vector<RigidCompoundPart> parts;
    MaterialDefinition material;
    RigidSnapshot state;
    double mass_kg{};
    Mat3 inertia_local_kg_m2;
};
struct RigidConvexDescription {
    MatterBodyId body_id{};
    std::vector<Vec3> vertices_local_m;
    MaterialDefinition material;
    RigidSnapshot state;
    double mass_kg{};
    Mat3 inertia_local_kg_m2;
};

enum class PairContactOwner { Jolt, External };

struct RigidContactCapacity {
    unsigned body_pairs{16384};
    unsigned constraints{8192};
};
struct RigidContactDiagnostics {
    RigidContactCapacity capacity;
    double speculative_distance_m{};
    std::size_t temporary_arena_bytes{};
    // Listener callbacks/geometry points, not constraint allocator occupancy.
    unsigned last_manifolds{},peak_manifolds{},last_points{},peak_points{};
    unsigned last_speculative_manifolds{},peak_speculative_manifolds{};
};

struct PairImpulseAudit {
    MechanicalTotals before{}, after{};
    double impulse_work_j{}, numerical_energy_change_j{};
    Vec3 momentum_error_kg_m_s{}, applied_couple_kg_m2_s{}, angular_momentum_error_kg_m2_s{};
};
struct CohesiveTensionKick {
    CohesiveInterfaceIncrement interface_increment;
    PairImpulseAudit transfer;
};

// What a ray met first.
//
// `named` is separate from `hit` because a ray can stop on something this world
// is holding that has no id of ours -- the ground is added through its own path
// and is not in the body table. Saying "it hit the ground" is a different answer
// from "it hit nothing", and a host that is deciding whether the pointer is over
// an object needs to tell them apart.
struct RayHit {
    bool hit{};
    bool named{};
    MatterBodyId body_id{};
    double distance_m{};
    Vec3 point_world_m{};
};

struct CohesiveTensionPatchKick {
    std::vector<CohesiveInterfaceIncrement> interface_increments;
    PairImpulseAudit transfer;
};

class JoltWorld {
public:
    JoltWorld();
    explicit JoltWorld(unsigned worker_threads);
    JoltWorld(unsigned worker_threads,RigidContactCapacity capacity);
    ~JoltWorld();

    JoltWorld(const JoltWorld &) = delete;
    JoltWorld &operator=(const JoltWorld &) = delete;
    JoltWorld(JoltWorld &&) noexcept;
    JoltWorld &operator=(JoltWorld &&) noexcept;
    [[nodiscard]] static unsigned positionPrecisionBits() noexcept;

    // Numerical experiment setting, before any bodies/supports are created.
    // Disables only cached narrow-phase body-pair results, not contacts/forces.
    void setBodyPairContactCacheEnabled(bool enabled);
    void setContactSolverIterations(unsigned velocity,unsigned position);
    // Resource capacity and observations do not alter contact laws/settings.
    // Deferred material contacts still require their activation observations.
    void setImpactObservationsEnabled(bool enabled);
    // Whether landing on the support surface is reported as an impact. Off by
    // default: a body at rest touches the floor on every step, and only a lane
    // that judges those contacts wants them. Only the arrival is reported, not
    // the resting that follows.
    void setSurfaceImpactObservations(bool enabled);
    [[nodiscard]] RigidContactDiagnostics contactDiagnostics() const;
    // Initial/current AABB + speculative-margin pair envelope, no time sweep.
    // Host-thread observation for bounded convex v2 admission, <=1024 bodies.
    [[nodiscard]] unsigned contactPairUpperBound() const;
    void setGravity(const Vec3 &gravity_m_s2);
    void addFloor();
    void addSupportSurface(const RigidSurfaceDescription &description);
    // Static, single-sided triangle support; winding points into free space.
    // Curved supports do not use the plane-only rolling-resistance approximation.
    void addTriangleSupport(const std::vector<std::array<Vec3,3>> &triangles,const MaterialDefinition &material);
    // Push on a body for one step, in newtons. Cleared by the step, so a
    // caller that wants a sustained push applies it every step -- which is what
    // a hand holding something does.
    void pushBody(MatterBodyId body_id, const Vec3 &force_n);
    // The same push delivered AT a point on the body rather than at its centre
    // of mass, so it turns the body as well as moving it -- a hand on the grip
    // of a sword swings the blade, it does not slide it. Cleared by the step.
    void pushBodyAt(MatterBodyId body_id, const Vec3 &force_n, const Vec3 &point_world_m);
    // A torque for one step, in newton metres. Cleared by the step.
    void twistBody(MatterBodyId body_id, const Vec3 &torque_n_m);
    void addBall(const RigidBallDescription &description);
    void addBox(const RigidBoxDescription &description);
    // Bounded compound collision proxy with independent matter-derived inertia.
    void addCompound(const RigidCompoundDescription &description);
    void addConvex(const RigidConvexDescription &description);
    // Physical central springs solved in Jolt's contact/constraint iterations.
    // Topology/history and constitutive work remain owned by the caller.
    unsigned addDistanceSpring(MatterBodyId a, MatterBodyId b, double rest_m,
        double stiffness_n_m, double damping_n_s_m);
    void updateDistanceSpring(unsigned spring, double rest_m, double stiffness_n_m,
        double damping_n_s_m);
    void removeDistanceSpring(unsigned spring);
    double distanceSpringImpulse(unsigned spring) const;
    // Opt-in observation only. Includes support/persisted contacts for reduced
    // fracture experiments; impulses remain estimates, not measured reactions.
    void setDetailedImpactObservations(bool enabled);
    // Host-thread only, between steps. External suppresses this pair's Jolt
    // contact response/events over both entire bodies, not just a joint face;
    // the caller must provide the physical response for all their contacts.
    // Ownership is transient and must be restored when rebuilding a world.
    void setPairContactOwner(MatterBodyId a,MatterBodyId b,PairContactOwner owner);
    [[nodiscard]] PairContactOwner pairContactOwner(MatterBodyId a,MatterBodyId b) const;
    // Instantaneous equal/opposite transfer supplied by an external law, not a
    // force law or a time advance. Requires External pair ownership and two
    // unpinned, unrestricted dynamic bodies. Points/impulse are world-space SI.
    // Preflights float rounding and speed limits before changing either body.
    // Budget bounds transfer roundoff only; the caller accounts for the source
    // of impulse work and any noncentral couple. Host thread, between steps.
    [[nodiscard]] PairImpulseAudit applyPairImpulse(MatterBodyId a,MatterBodyId b,
        Vec3 point_a_m,Vec3 point_b_m,Vec3 impulse_on_a_n_s,double maximum_roundoff_energy_j);
    // Central tensile connector between body-local points; Jolt retains every
    // surface contact. Compression stiffness must be zero. Requires double
    // positions and Jolt pair ownership; material-activation deferral rejects.
    // Caller owns geometric validity, site
    // history, time integration and its full work/error budget. No world step
    // or multi-kick rollback is implied. History is returned only on success.
    // Keeps both bodies awake while called, including a failed/slack site;
    // the external scheduler must stop calls when normal sleeping may resume.
    [[nodiscard]] CohesiveTensionKick applyCohesiveTensionKick(MatterBodyId a,MatterBodyId b,
        Vec3 attachment_a_local_m,Vec3 attachment_b_local_m,double rest_distance_m,
        const CohesiveInterfaceLaw &law,const CohesiveInterfaceState &history,
        double impulse_duration_s,double maximum_roundoff_energy_j);
    // 1..256 caller-compiled local sites, each with its own area/history.
    // Common law.area_m2 is ignored. Every site is evaluated from the same
    // pose; the complete velocity update is preflighted before either write.
    // Returns histories only on success; does not step or own persistence.
    [[nodiscard]] CohesiveTensionPatchKick applyCohesiveTensionPatchKick(MatterBodyId a,MatterBodyId b,
        const std::vector<CohesivePatchSite> &sites,const CohesiveInterfaceLaw &law,
        double impulse_duration_s,double maximum_roundoff_energy_j);
    // A pin two bodies turn about.
    //
    // This is the first real joint in the engine, and it is a joint rather than
    // an animation on purpose: a door swings because a push off its centre line
    // makes a torque about the pin, and stops because it meets the frame or
    // runs out of the travel its hinge allows. Nothing plays a door opening.
    //
    // The frame is given in WORLD space, where the two bodies are standing at
    // the moment it is made, and Jolt keeps it in each body's own frame from
    // then on. That is what makes a mechanism keep working when the whole
    // assembly is moved or turned over: the pin is a fact about the two bodies,
    // not about where they happened to be.
    //
    // Either body may be anchored scenery -- a door on a wall is the ordinary
    // case -- but not both, or there is nothing for the joint to move.
    struct HingeDescription {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        // Where the pin is and which way it runs, in world metres, as things
        // stand right now.
        Vec3 point_world_m{};
        Vec3 axis_world{0.0, 1.0, 0.0};
        // How far it may turn from where it starts, in radians. Jolt takes a
        // lower in [-pi, 0] and an upper in [0, pi]; a full circle is the
        // default and is what a wheel wants.
        double lower_rad{-3.14159265358979323846};
        double upper_rad{3.14159265358979323846};
        // What it takes to start it turning, in newton metres. A stiff old
        // hinge holds a door where it is left; zero swings freely.
        double friction_torque_n_m{0.0};
    };
    [[nodiscard]] unsigned addHinge(const HingeDescription &description);

    // A way two bodies slide along each other.
    //
    // The same idea as a pin, one degree of freedom the other way round: the
    // two are locked in rotation and free to move along one line. A portcullis
    // in its grooves, a sliding door, a bolt going across a door -- and, like a
    // pin, none of it is played. A raised portcullis with nothing under it
    // falls, because gravity is still acting on a body that is free to move
    // down its own axis.
    //
    // Travel is metres either side of where it is built, so a portcullis built
    // down has 0..2 of lift and one built up has -2..0 of drop.
    struct SliderDescription {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        Vec3 point_world_m{};
        // Which way it may move. Vertical for a portcullis.
        Vec3 axis_world{0.0, 1.0, 0.0};
        double lower_m{-1.0}, upper_m{1.0};
        // What it takes to start it moving, in newtons. A heavy grate in dry
        // stone grooves does not slide freely, and friction here is the whole
        // difference between a gate that stays up when you stop hauling and one
        // that drops the moment you let go.
        double friction_n{0.0};
    };
    [[nodiscard]] unsigned addSlider(const SliderDescription &description);

    // One link of a rope or a chain.
    //
    // Two points that may be any distance apart UP TO a limit, and no further.
    // That one asymmetry is the whole of what makes a rope a rope: it pulls and
    // it does not push. Slack costs nothing and is not a force; going taut is.
    //
    // A rope is made of these -- a run of small bodies, each linked to the
    // next -- rather than being a special kind of object, so it hangs in a
    // catenary because its own segments are heavy, it drapes over what it
    // touches because its segments collide, and it can be cut anywhere along
    // its length because every link is separately real.
    //
    // `breaking_tension_n` is what it takes to part it. Zero means it never
    // parts; anything else is a rope that can be overloaded, which is the
    // difference between a hoist you have to think about and one you do not.
    // Read what a link is actually carrying with jointTension().
    struct LinkDescription {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        // Where the link is tied on each body, in world metres, as things stand
        // right now. Kept in each body's own frame from then on, like a pin.
        Vec3 point_a_world_m{};
        Vec3 point_b_world_m{};
        // How far apart they may get. Below this the link does nothing at all.
        double length_m{0.1};
        double breaking_tension_n{0.0};
    };
    [[nodiscard]] unsigned addLink(const LinkDescription &description);

    // A rope run over two fixed points, with what hangs on each end.
    //
    // This is the IDEAL pulley: a relationship between cable lengths, not a
    // wheel with a rope wrapped round it. The engine holds
    //
    //     |a - over_a|  +  ratio * |b - over_b|  <=  length
    //
    // and nothing else. There is no wheel, so there is no wheel inertia and no
    // bearing friction; there is no wrap, so the rope cannot slip, cannot come
    // off, and does not rub. What it does give you is exactly what a hoist is
    // for: pull one end down and the other end comes up.
    //
    // `ratio` applies to B'S RUN, and WHICH END is not a detail. Because b's
    // length is what gets multiplied, b moves 1/ratio as far as a does, and
    // feels ratio times the cable tension. So the advantage is on b's side:
    //
    //     hang the LOAD at b, and a counterweight of load/ratio balances it.
    //
    // At ratio 2 that is a block and tackle: half the weight holds the load, and
    // the load rises half as far as the counterweight falls. Put the load at `a`
    // instead and you have the same machine backwards -- it would then need
    // TWICE the weight -- which is a real thing to build and a surprising thing
    // to build by accident.
    //
    // The physical alternative is already here: a run of bodies tied with
    // addLink, draped over something. That one has real wrap, real friction and
    // real slip, and costs a body per segment. Use this when you want a hoist
    // to work; use that when the rope itself is the thing being watched.
    //
    // Like a link it pulls and does not push: the sum is bounded above and free
    // below, so slack on one side is just slack.
    struct PulleyDescription {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        // Where the rope is made off on each body, in world metres.
        Vec3 point_a_world_m{};
        Vec3 point_b_world_m{};
        // The fixed points it runs over -- the sheaves. These do not move, ever:
        // that is what makes them the fixed half of the relationship.
        Vec3 over_a_world_m{};
        Vec3 over_b_world_m{};
        // Mechanical advantage on the second end.
        double ratio{1.0};
        // How long the rope is. Zero means "as it is rove": the length the two
        // runs add up to right now, which is what you want for a rope already
        // threaded.
        double length_m{0.0};
    };
    [[nodiscard]] unsigned addPulley(const PulleyDescription &description);

    // A fixing: two bodies held together as one, until they are not.
    //
    // A peg, a bracket, a nail, a bolt, a door catch, a locking bar, a rope
    // anchor. All six degrees of freedom are held, so the two move as one piece
    // and whatever their relative pose is when the fixing is made is the pose it
    // keeps. That is the "defined alignment": it is defined by where they are.
    //
    // What makes it a fixing rather than a weld is that it has a STRENGTH, and
    // two of them, because a peg pulled straight out and a peg sheared sideways
    // fail at different loads and it is rarely the same number. Tension is
    // along the axis; shear is across it. Either one exceeded parts it.
    //
    // Zero means it never lets go on its own -- that is a weld, and welds are a
    // real thing to want. Releasing it deliberately is removeJoint(), which is
    // what a latch does.
    struct FixingDescription {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        // Where the fixing is, in world metres, as things stand.
        Vec3 point_world_m{};
        // Which way it points -- the direction a peg would be driven. Tension is
        // along this and shear is across it.
        Vec3 axis_world{0.0, 1.0, 0.0};
        double holds_tension_n{0.0};
        double holds_shear_n{0.0};
    };
    [[nodiscard]] unsigned addFixing(const FixingDescription &description);

    // An elastic element between two points: a bow limb, a spring, a bent
    // plank, anything that stores energy by being deformed and gives it back.
    //
    // This is a DECLARED SIMPLIFIED MODEL and it is worth being plain about
    // which one. It is an ideal linear spring:
    //
    //     force  =  stiffness * (length - rest)        newtons
    //     stored =  stiffness * (length - rest)^2 / 2  joules
    //
    // Hooke's law, in other words, with viscous damping proportional to the
    // rate of change of length. What that is NOT: it has no mass of its own, no
    // internal stress, no yield, no hysteresis, and it does not care which way
    // it is bent. A real bow limb has all of those. What it does have is the
    // property the rest of this depends on -- work put in is energy stored, and
    // energy stored is energy given back, minus what the damping takes -- and
    // that is checked rather than asserted: see tests/elastic_tests.cpp, where
    // the work integral of the draw is compared against the kinetic energy that
    // comes out the other end.
    //
    // Unlike a link it pushes AS WELL as pulling: compressed below its rest
    // length it shoves back. A thing that only pulls is a rope, and there is
    // already one of those.
    struct ElasticDescription {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        // Where it is attached on each body, in world metres. Points rather
        // than centres, because a bow limb pulls on the END of the limb and a
        // spring between two centres is a different machine.
        Vec3 point_a_world_m{};
        Vec3 point_b_world_m{};
        // The length at which it stores nothing. Zero means "as it stands",
        // which is what you want for something built already relaxed.
        double rest_m{0.0};
        double stiffness_n_m{1000.0};
        // Newton seconds per metre. This is the DECLARED LOSS: everything the
        // damping takes out is energy the spring will not give back, and it is
        // the difference between the work put in and the work got out.
        double damping_n_s_m{0.0};
    };
    [[nodiscard]] unsigned addElastic(const ElasticDescription &description);

    // What a fixing is carrying, split along its axis and across it. Both zero
    // for every other kind of joint, which has no axis to split along.
    struct JointLoad {
        double tension_n{};
        double shear_n{};
    };
    [[nodiscard]] JointLoad jointLoad(unsigned joint, const Vec3 &axis_world) const;
    // What this link is carrying, in newtons. Zero when it is slack.
    [[nodiscard]] double jointTension(unsigned joint) const;

    enum class JointKind : std::uint8_t {
        Hinge = 0, Slider = 1, Link = 2, Pulley = 3, Fixing = 4, Elastic = 5,
        // An edge in a cut. Not a joint anybody builds: the cutting model
        // makes one while an edge is engaged and takes it away when it is
        // not. See docs/cutting-model.md and KerfDescription below.
        Kerf = 6
    };

    // An edge engaged in matter, as the solver sees it.
    //
    // Everything the cutting model needs the solver to do is friction and
    // locking, so it is one six-degree-of-freedom constraint between the blade
    // and the thing it is cutting, in the BLADE's own axes:
    //
    //   along the facing    free, with a friction limit: the edge does not
    //                       advance until it is pushed harder than the
    //                       material resists, and then the material takes
    //                       exactly the limit. That is the cut's resistance.
    //   along the edge      free, with its own limit: what a slice costs.
    //   across the flats    locked while `embedded` -- the kerf walls.
    //   twist about the facing or the edge
    //                       locked while `embedded`, for the same reason.
    //   turning in the blade's own plane
    //                       always free, which is how an edge follows a swing.
    //
    // Made fresh every step by the cutting model and read back after it: the
    // friction impulses are the work the cut took, which is the whole of the
    // energy account.
    struct KerfDescription {
        MatterBodyId blade{kInvalidMatterBodyId};
        MatterBodyId target{kInvalidMatterBodyId};
        Vec3 point_world_m{};
        Vec3 facing_world{};   // the way the edge faces
        Vec3 flat_world{};     // normal to the blade's flats
        bool embedded{};
        double resist_facing_n{};
        double resist_along_n{};
    };
    [[nodiscard]] unsigned addKerf(const KerfDescription &description);
    // Change what an engaged edge's constraint resists with, and keep it -- and
    // with it the impulse it has built up, which the solver carries into the
    // next step. That carried impulse is what lets a heavy blade pressed into a
    // light plank lying on the floor actually be held.
    void updateKerf(unsigned joint, double resist_facing_n, double resist_along_n);
    // The friction impulses the last step applied, in newton seconds, along
    // the facing and along the edge. Signed as Jolt applies them to the blade's
    // constraint axes; the cutting model uses their size.
    struct KerfImpulse {
        double facing_n_s{};
        double along_n_s{};
    };
    [[nodiscard]] KerfImpulse kerfImpulse(unsigned joint) const;

    // Everything about a joint that a caller can see from outside.
    struct JointReport {
        MatterBodyId a{kInvalidMatterBodyId};
        MatterBodyId b{kInvalidMatterBodyId};
        JointKind kind{JointKind::Hinge};
        // Where it has got to, from where it was made: radians for a pin,
        // metres for a slide. One number, because a joint with one degree of
        // freedom has one number, and which unit it is in is what `kind` says.
        double at{};
        double lower{};
        double upper{};
        // Newton metres for a pin, newtons for a slide.
        double friction{};
    };
    [[nodiscard]] bool hasJoint(unsigned joint) const;
    [[nodiscard]] JointReport jointState(unsigned joint) const;
    void setJointFriction(unsigned joint, double friction);
    // Take the pin out. What was hanging on it falls.
    void removeJoint(unsigned joint);
    [[nodiscard]] std::vector<unsigned> jointsOn(MatterBodyId body_id) const;

    void pinToWorld(MatterBodyId body_id);
    void releaseFromWorld(MatterBodyId body_id);
    void applyRigidState(MatterBodyId body_id,const RigidSnapshot &state);
    // What a ray hits first, asked of the shapes the solver is actually using.
    //
    // "What is the pointer on", "can this see that", "is anything in the way"
    // are all this one question, and without it a host has to keep its own copy
    // of the world and answer from that -- a second set of shapes that drifts
    // from the real ones. The playground did exactly that, picking against
    // bounding boxes in the browser, so a piece that broke off something could
    // not be pointed at: its cells are its surface and no box describes it.
    //
    // Costs no step and changes nothing, so it is safe to ask every frame.
    [[nodiscard]] RayHit castRay(const Vec3 &from_world_m,const Vec3 &direction,
                                 double max_distance_m) const;
    // Put a body back into simulation and clear how long it has been still.
    // A body that has come to rest is dropped from the step -- that is what
    // keeps a scene of a hundred settled pieces cheap -- and nothing that only
    // writes a pose brings it back, because writing a pose is how a sleeping
    // body is placed. A host that moves a body by hand and then expects gravity
    // to act on it has to say so.
    void wake(MatterBodyId body_id);
    void addFragments(const std::vector<RigidFragmentDescription> &fragments);
    // Trusted host callback, between steps. True accepts; false or an exception
    // restores Jolt bodies/contacts/constraints/global state, ticks and queued
    // impacts. Geometry/configuration mutations reject while a trial is open.
    // Caller owns external histories and must keep this world alive/unmoved.
    // At most 2,048 bodies and 16 nested trials; no persistence/portable
    // snapshot. The budget is the state recorder's, not Jolt's: every trial
    // saves the world and restores it if the trial is refused. Measured on a
    // room of shattered glass, a step with the trial on costs 0.6 ms at 58
    // bodies, 3.3 ms at 250 and 3.1 ms at 600 -- flat, because a body that has
    // settled is cheap to record. It was 256, and 256 is reached by breaking
    // two panes: past it the step is taken straight, and a fracture handed an
    // already-resolved contact finds nothing to break. Measured, the same iron
    // ball onto the same 20 mm pane broke it into 71 pieces in a room of 58
    // bodies and left it whole in a room of 430.
    [[nodiscard]] bool runReversibleTrial(const std::function<bool()> &trial);
    // Trusted host callback for adaptive spring integration. Existing distance
    // springs may be updated or removed; additions and every other topology or
    // configuration mutation remain forbidden. True accepts. False or an
    // exception restores the complete Jolt state, constraint order, spring map
    // and settings, ticks, impacts and contact diagnostics. Caller-owned
    // material history is outside this transaction. The caller must keep the
    // world alive/unmoved. Host thread, between steps; at most 1024 bodies,
    // 20000 springs, 16 MiB recorded Jolt state and 16 nested spring trials.
    [[nodiscard]] bool runSpringTrial(const std::function<bool()> &trial);
    void step(double fixed_dt_s);
    [[nodiscard]] CoupledSphereState sphereContactState(MatterBodyId body_id) const;
    void applySphereContactState(MatterBodyId body_id, const CoupledSphereState &state);

    [[nodiscard]] std::vector<ImpactEvent> drainImpacts();
    [[nodiscard]] RigidSnapshot snapshot(MatterBodyId body_id) const;
    [[nodiscard]] RigidMechanicalState mechanicalState(MatterBodyId body_id) const;
    [[nodiscard]] MechanicalTotals mechanicalTotals(const Vec3 &gravity_m_s2 = {}) const;
    [[nodiscard]] bool contains(MatterBodyId body_id) const;
    void removeAndDestroy(MatterBodyId body_id);

private:
    [[nodiscard]] PairImpulseAudit applyAuditedPairImpulses(MatterBodyId a,MatterBodyId b,
        const std::vector<AttachmentImpulse> &impulses,double maximum_roundoff_energy_j);
    class Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace banjo
