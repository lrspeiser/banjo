#pragma once
#include "platform/CompiledObject.hpp"
#include "platform/PlatformWorld.hpp"
#include "rigid/JoltWorld.hpp"
#include <map>

namespace banjo {
struct CompiledRuntimeObject {
    unsigned id{};
    MaterialPreset material{};
    RigidPrimitive shape;
    RigidSnapshot state;
    std::uint64_t seed{};
};
class CompiledRuntime {
public:
    CompiledRuntime(Vec3 gravity,const std::vector<CompiledRuntimeObject> &objects,
        const RigidSurfaceDescription *ground,const std::vector<std::array<Vec3,3>> &bowl,MaterialPreset surface);
    void step(double dt);
    std::vector<PlatformInstance> renderInstances() const;
    std::vector<PlatformBondLine> renderBonds() const;
    RigidSnapshot state(unsigned object) const;
    unsigned componentCount(unsigned object) const;
    std::string reportJson() const;
    unsigned fractureCount() const { return broken_; }
    double energy() const { return rigid_.mechanicalTotals(gravity_).mechanicalEnergy(); }
private:
    struct Object {unsigned id;MaterialPreset material;RigidPrimitive shape;CompiledDamage damage;};
    struct Component {unsigned object;std::vector<unsigned> nodes;Vec3 origin;};
    struct Event {double time;unsigned object,component;MatterBodyId other;unsigned link,round;double work,stress;};
    RigidCompoundDescription description(unsigned object,const std::vector<unsigned> &nodes,unsigned id,const RigidSnapshot &state,Vec3 &origin) const;
    void split(unsigned component);
    JoltWorld rigid_;
    Vec3 gravity_;
    std::vector<Object> objects_;
    std::map<unsigned,Component> components_;
    std::vector<Event> events_;
    std::vector<ImpactEvent> observations_;
    unsigned next_id_{1000001},broken_{},solves_{},rebuilds_{},activations_{},limited_{},contacts_{},splits_{};
    double time_{},work_{},allocated_loss_{},rigid_energy_change_{},transfer_energy_change_{},max_transfer_energy_error_{},max_transfer_mass_error_{},max_transfer_momentum_error_{},max_transfer_angular_error_{};
};
}
