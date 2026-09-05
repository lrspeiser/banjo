#pragma once
#include "core/Types.hpp"
#include "fracture/ActiveMatter.hpp"
#include "material/MaterialCatalog.hpp"
#include <vector>
namespace banjo {
// Experimental coarse lattice with strength AND fracture-work gates.
// Released elastic energy stays in the local nodes. Contact remains approximate.
struct BowlCell { Vec3 x,v,spin; double mass{},radius{},inertia{}; unsigned object{}; };
struct BowlLink { unsigned a{},b{}; double rest{},stiffness{},work{},damping{},threshold_energy{}; bool live{true},brittle{}; };
struct BowlCellObject { MatterBodyId id{}; MaterialPreset material{}; unsigned first{},count{}; double radius{}; };
struct BowlBreak { double time_s{}; unsigned link{},object{}; double work_j{},overshoot_j{},elastic_release_j{}; };
struct BondedBowlLedger {
 double initial_energy_j{},fracture_work_j{},event_overshoot_j{},elastic_release_j{},internal_damping_j{},contact_damping_j{},friction_j{};
 Vec3 support_impulse{},support_angular_impulse{},gravity_impulse{},gravity_angular_impulse{};
};
class BondedBowl {
public:
 double bowl_radius{1.2},bowl_depth{.55},tilt_degrees{};
 MaterialPreset surface{MaterialPreset::Concrete};
 double wave_step_fraction{.35};
 Vec3 gravity{0,-9.81,0}; bool support{true},failure_enabled{true};
 std::vector<BowlCell> cells; std::vector<BowlLink> links; std::vector<BowlCellObject> objects; std::vector<BowlBreak> breaks;
 BondedBowlLedger ledger;
 void add(MatterBodyId id,MaterialPreset material,double radius,const RigidSnapshot &state);
 void initialize();
 void advance(double seconds);
 RigidSnapshot state(MatterBodyId id) const;
 std::vector<unsigned> components() const;
 double energy() const;
 Vec3 momentum() const; Vec3 angularMomentum() const;
 double time() const {return time_;} double stepLimit() const {return step_limit_;}
 double energyResidual() const;
private:
 struct Contact {unsigned a{},b{}; Vec3 n,point;double compression{},stiffness{},friction{},damping{};bool fixed{};};
 mutable std::vector<std::pair<unsigned,unsigned>> neighbors_;
 mutable std::vector<Vec3> neighbor_positions_;
 std::vector<Contact> contacts() const;
 void forces(std::vector<Vec3> &f,const std::vector<Contact> &c) const;
 void dissipate(double dt,const std::vector<Contact> &c);
 bool step(double dt,unsigned depth);
 double time_{},step_limit_{};
 unsigned evaluations_{};
 std::vector<double> damping_impulse_factors_;
};
}
