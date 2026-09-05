#pragma once
#include "creator/CreatorWorld.hpp"
#include "creator/BondedBowl.hpp"
#include "platform/BowlGeometry.hpp"
namespace banjo {
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
    void presentRecordingFrame(const BondedBowl &frame);
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
