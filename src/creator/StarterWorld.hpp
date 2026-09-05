#pragma once
#include "creator/CreatorWorld.hpp"
#include <array>
#include <functional>

namespace banjo {
struct StarterObject {
    MatterBodyId id{};
    ObjectRecipe recipe;
    RigidSnapshot state;
    bool branch{},attached{},collected{},tool{};
    double cut_fraction{};
    bool custom_design{};
};
struct StarterDesign {
    std::string id,label,description;
    ObjectRecipe recipe;
    unsigned level{};
    double stamina{};
    bool tool{};
};
struct StarterQuote {
    double required_kg{},held_kg{},missing_kg{},stamina{};
    unsigned level{};
    std::vector<std::string> missing;
    [[nodiscard]] bool ready() const {return missing.empty();}
};
struct StarterRememberedDesign {
    std::string request_id,prompt,explanation;
    std::optional<ObjectRecipe> recipe;
};
// A deliberately versioned game layer. Stamina and XP are gameplay units,
// not joules or a calibrated manufacturing/fracture law.
class StarterWorld {
public:
    StarterWorld();
    StarterWorld(StarterWorld&&) noexcept=default;
    StarterWorld &operator=(StarterWorld&&) noexcept=default;
    [[nodiscard]] unsigned level() const {return 1+xp_/20;}
    [[nodiscard]] unsigned xp() const {return xp_;}
    [[nodiscard]] double stamina() const {return stamina_;}
    [[nodiscard]] double spent() const {return spent_;}
    [[nodiscard]] double inventoryKg(MaterialPreset material) const;
    [[nodiscard]] double inventoryVoxels(MaterialPreset material) const;
    [[nodiscard]] std::string equippedTool() const;
    [[nodiscard]] double gatheringCost() const;
    [[nodiscard]] const std::vector<StarterObject> &objects() const {return objects_;}
    [[nodiscard]] static std::vector<StarterDesign> designs();
    [[nodiscard]] StarterQuote quote(std::string_view design) const;
    [[nodiscard]] StarterQuote quoteRecipe(const ObjectRecipe &recipe) const;
    [[nodiscard]] static ObjectRecipe defaultDraft();
    [[nodiscard]] const std::optional<std::string> &rememberedAssembly() const {return remembered_assembly_;}
    [[nodiscard]] std::uint64_t assemblyRevision() const {return assembly_revision_;}
    std::uint64_t rememberAssemblyAndSave(const std::filesystem::path &path,std::string_view declaration,std::uint64_t expected_revision);
    std::uint64_t clearAssemblyAndSave(const std::filesystem::path &path,std::uint64_t expected_revision);
    [[nodiscard]] std::string assessAssemblyJson(std::string_view declaration) const;
    [[nodiscard]] std::string assemblyReviewDocument(std::string_view request_id,std::string_view prompt,std::string_view declaration,std::string_view test) const;
    [[nodiscard]] std::string designerRequest(std::string_view id,std::string_view prompt) const;
    [[nodiscard]] const std::optional<StarterRememberedDesign> &rememberedDesign() const {return remembered_design_;}
    void rememberDesignAndSave(const std::filesystem::path &path,const StarterRememberedDesign &design);
    std::string craftRecipe(std::string request,const ObjectRecipe &recipe,Vec3 eye);
    std::string interact(std::string request,MatterBodyId object,Vec3 eye);
    std::string craft(std::string request,std::string_view design,Vec3 eye);
    // Single-writer local host boundary: publish the candidate save before
    // changing live state or acknowledging a resource-changing action.
    std::string interactAndSave(const std::filesystem::path &path,std::string request,MatterBodyId object,Vec3 eye);
    std::string craftAndSave(const std::filesystem::path &path,std::string request,std::string_view design,Vec3 eye);
    std::string craftRecipeAndSave(const std::filesystem::path &path,std::string request,const ObjectRecipe &recipe,Vec3 eye);
    void rest(double seconds);
    void step(unsigned ticks=1);
    [[nodiscard]] std::string serialize() const;
    [[nodiscard]] static StarterWorld deserialize(std::string_view document);
    void save(const std::filesystem::path &path) const;
    [[nodiscard]] static StarterWorld load(const std::filesystem::path &path);
    [[nodiscard]] static Vec3 benchPosition() {return {0,.6,-2};}
    [[nodiscard]] static Vec3 treePosition() {return {3,1.5,-2};}
private:
    struct Receipt {std::string id,command,result;};
    std::vector<StarterObject> objects_;
    std::vector<Receipt> receipts_;
    std::optional<StarterRememberedDesign> remembered_design_;
    std::optional<std::string> remembered_assembly_;
    std::uint64_t assembly_revision_{};
    std::array<double,3> inventory_m3_{};
    std::unique_ptr<JoltWorld> physics_;
    unsigned xp_{};
    double stamina_{100},spent_{},restored_{};
    std::uint64_t ticks_{};
    MatterBodyId next_{1};
    void rebuildPhysics();
    void debit(double amount);
    [[nodiscard]] std::optional<std::string> replay(const std::string &id,const std::string &command) const;
    std::string interactUnchecked(MatterBodyId object,Vec3 eye);
    std::string craftUnchecked(std::string_view design,Vec3 eye);
    std::string craftRecipeUnchecked(const ObjectRecipe &recipe,Vec3 eye);
    std::string commitSaved(const std::filesystem::path &path,const std::function<std::string(StarterWorld&)> &action);
};
}
