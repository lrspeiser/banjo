#pragma once
#include "creator/CreatorWorld.hpp"
#include "creator/BondedBowl.hpp"
namespace banjo {
struct BowlSettings {
    double radius_m{1.2},depth_m{.55},tilt_degrees{};
    MaterialPreset surface{MaterialPreset::Concrete};
    unsigned rings{24},sectors{96};
    bool experimental_fracture{true};
};
// Parabolic finite open bowl, upward-facing triangles, shared by renderer/solver.
std::vector<std::array<Vec3,3>> compileBowl(const BowlSettings &settings);
Vec3 bowlPoint(const BowlSettings &settings,double x,double z);
class BowlLab {
public:
    explicit BowlLab(CreatorWorld stock=CreatorWorld{});
    const CreatorWorld &stock() const {return stock_;}
    const BowlSettings &settings() const {return settings_;}
    const auto &triangles() const {return triangles_;}
    bool running() const {return running_;}
    double timeSeconds() const {return bonded_?bonded_->time():ticks_/240.0;}
    const BondedBowl *bonded() const {return bonded_.get();}
    unsigned contacts() const {return contacts_;}
    bool collect(MaterialPreset material);
    ObjectRecipe craftRecipe(MaterialPreset material) const;
    MatterBodyId craft(MaterialPreset material);
    // Authoring reset: same allocated objects, new placements, zero velocities.
    // Never a physical energy refund or an inventory credit.
    void configure(BowlSettings settings);
    void release();
    void pause() {running_=false;}
    void step(unsigned ticks=1);
    RigidSnapshot state(MatterBodyId id) const;
    std::string reportJson() const;
private:
    CreatorWorld stock_;
    BowlSettings settings_;
    std::vector<std::array<Vec3,3>> triangles_;
    std::unique_ptr<JoltWorld> world_;
    std::unique_ptr<BondedBowl> bonded_;
    bool running_{};
    std::uint64_t ticks_{};
    unsigned contacts_{};
    double initial_energy_j_{};
};
}
