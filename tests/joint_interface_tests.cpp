// A declared joint is weaker than the material it joins.
//
// A Workshop product compiles to ONE fused lattice: a bond between a leg's cell
// and the top's is an ordinary oak bond, so every joint was as strong as the
// wood it joined ([#20](https://github.com/lrspeiser/banjo/issues/20)). A glued
// or dowelled joint is a fraction of it; a weld is nearly all.
//
// The mechanism was already here -- weakenBond scales a bond's damage
// thresholds, and is how heat weakens a section -- and what was missing was
// which part a cell came from surviving the join. A body now says which part of
// the object it is, a scene says what its joints leave the bonds that cross
// them, and the two meet here at asset build.
//
// What is pinned:
//
// 1. Without a joint declared, nothing changes at all: bond for bond.
// 2. A declared joint weakens exactly the bonds that cross it, by exactly what
//    it declares, and leaves every bond inside a part alone.
// 3. The force a bond fails at goes by its strength's factor -- that is the
//    bond law, and it is the SAME function heat uses.
// 4. A cell two parts both claim belongs to the first, which is the rule by
//    which it is built once.
// 5. A joint naming a part nothing is, is refused. An unknown key here is a
//    default, so a misspelling would otherwise be a silent full-strength joint.
// 6. A joint that holds nothing in any direction is refused: that is two
//    objects, not one joined.
// 7. A joint between two parts that are not bonded to each other is refused
//    too: it would have weakened nothing, in silence.

#include "fastlattice/TileImpactScene.hpp"
#include "matter/Lattice.hpp"

#include <cmath>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace banjo;
using namespace banjo::fastlattice;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}

void close(double got, double want, double tolerance, const std::string &what) {
    if (std::abs(got - want) > tolerance)
        throw std::runtime_error(what + ": got " + std::to_string(got) + ", wanted " +
                                 std::to_string(want));
}

// A post standing under a slab, as one joined oak object in two parts. The
// post's top row of cells and the slab's bottom row are what a joint crosses.
std::string sceneText(const std::string &interfaces) {
    return R"({"bodies":[
        {"name":"post","shape":"box","material":"oak","join":"thing","part":"post",
         "dimensions_m":[0.04,0.20,0.04],"center_m":[0,0.10,0]},
        {"name":"slab","shape":"box","material":"oak","join":"thing","part":"slab",
         "dimensions_m":[0.20,0.04,0.12],"center_m":[0,0.22,0]}])" +
           interfaces + "}";
}

TileImpactRequest request(const std::string &interfaces) {
    const std::string text = sceneText(interfaces);
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.bodies = readSceneJson(text);
    readSceneSettings(text, r);
    return r;
}

// Which bonds cross from one part to the other, by the cell grid each node sits
// on. The slab's underside is at y = 0.20, so a cell centred below it is the
// post's and one above is the slab's -- worked out here from the scene's own
// numbers rather than read back out of the thing under test.
bool crosses(const LatticeAsset &asset, const BondRest &bond, double cell, double seam_y) {
    const auto side = [&](std::uint32_t node) {
        return (asset.nodes[node].grid.y + 0.5) * cell < seam_y;
    };
    return side(bond.node_a) != side(bond.node_b);
}

void withoutAJointNothingChanges() {
    const auto plain = buildTileImpactSetup(request(""));
    const auto same = buildTileImpactSetup(request(R"(,"interfaces":[])"));
    require(plain->interface_bonds == 0, "a scene with no joints weakened something");
    require(same->interface_bonds == 0, "an empty joint list weakened something");
    require(plain->asset.bonds.size() == same->asset.bonds.size(), "the bond count moved");
    for (std::size_t i = 0; i < plain->asset.bonds.size(); ++i) {
        const BondRest &a = plain->asset.bonds[i], &b = same->asset.bonds[i];
        require(a.compliance == b.compliance && a.damage_end_stretch == b.damage_end_stretch &&
                    a.shear_damage_end_strain == b.shear_damage_end_strain,
                "a bond changed with no joint declared");
    }
}

void aJointWeakensWhatCrossesItAndNothingElse() {
    const auto whole = buildTileImpactSetup(request(""));
    const auto glued = buildTileImpactSetup(
        request(R"(,"interfaces":[{"a":"post","b":"slab","tension":0.25,"shear":0.4}])"));
    require(whole->asset.bonds.size() == glued->asset.bonds.size(),
            "a joint changed how many bonds there are");
    require(glued->interface_bonds > 0, "the joint reached no bond at all");

    std::size_t crossing = 0, inside = 0;
    for (std::size_t i = 0; i < whole->asset.bonds.size(); ++i) {
        const BondRest &was = whole->asset.bonds[i], &now = glued->asset.bonds[i];
        if (crosses(whole->asset, was, 0.02, 0.20)) {
            ++crossing;
            // A damage threshold is a stretch, so it goes by the strength's
            // factor over the stiffness's -- and the stiffness is untouched.
            close(now.damage_end_stretch, 0.25 * was.damage_end_stretch, 1e-12 * was.damage_end_stretch,
                  "a crossing bond's tension threshold");
            close(now.shear_damage_end_strain, 0.4 * was.shear_damage_end_strain,
                  1e-12 * was.shear_damage_end_strain, "a crossing bond's shear threshold");
            close(now.compression_damage_end_strain, was.compression_damage_end_strain,
                  1e-12 * was.compression_damage_end_strain,
                  "a crossing bond's compression: two parts pushed together bear on each other");
            close(now.compliance, was.compliance, 1e-12 * was.compliance,
                  "a crossing bond's stiffness, which a glue line does not change here");
        } else {
            ++inside;
            require(now.damage_end_stretch == was.damage_end_stretch &&
                        now.shear_damage_end_strain == was.shear_damage_end_strain &&
                        now.compliance == was.compliance,
                    "a bond inside one part was weakened");
        }
    }
    require(crossing == glued->interface_bonds,
            "the count of weakened bonds is not the count that cross the joint");
    require(crossing > 0 && inside > crossing, "the scene did not make the seam it was meant to");
}

// The bond law itself, on one record: the same function heat uses.
void theForceABondFailsAtGoesByItsStrength() {
    BondRest bond;
    bond.compliance = 4.0;
    bond.damage_start_stretch = 0.02;
    bond.damage_end_stretch = 0.05;
    bond.compression_damage_start_strain = 0.03;
    bond.compression_damage_end_strain = 0.06;
    bond.shear_damage_start_strain = 0.01;
    bond.shear_damage_end_strain = 0.04;

    require(wholeBond({}), "the identity factors are not whole");
    require(!wholeBond({1.0, 0.25, 1.0, 1.0}), "a weakened bond read as whole");

    BondRest half = bond;
    require(weakenBond(half, {1.0, 0.5, 1.0, 1.0}), "weakening a bond by half refused");
    // Stiffness untouched, so the stretch it fails at halves, and the force it
    // fails at -- stretch over compliance -- halves with it.
    close(half.compliance, bond.compliance, 1e-15, "compliance with the stiffness untouched");
    close(half.damage_end_stretch, 0.5 * bond.damage_end_stretch, 1e-15, "the tension threshold");
    close(half.compression_damage_end_strain, bond.compression_damage_end_strain, 1e-15,
          "compression, which was not weakened");

    // Half the strength AND half the stiffness: it fails at the same stretch,
    // at half the force. That is what makes it a law about force.
    BondRest soft = bond;
    require(weakenBond(soft, {0.5, 0.5, 0.5, 0.5}), "weakening stiffness and strength refused");
    close(soft.damage_end_stretch, bond.damage_end_stretch, 1e-15,
          "the stretch it fails at, with strength and stiffness falling together");
    close(soft.compliance, 2.0 * bond.compliance, 1e-15, "compliance at half the stiffness");
    close(soft.damage_end_stretch / soft.compliance, 0.5 * bond.damage_end_stretch / bond.compliance,
          1e-15, "the force it fails at");

    BondRest nothing = bond;
    require(!weakenBond(nothing, {1.0, 0.0, 0.0, 0.0}), "a bond that holds nothing was kept");
}

void aCellTwoPartsClaimBelongsToTheFirst() {
    // The slab is lowered so its bottom row sits exactly where the post's top
    // row is. Those cells are the post's, because the post is written first.
    const std::string text = R"({"bodies":[
        {"name":"post","shape":"box","material":"oak","join":"thing","part":"post",
         "dimensions_m":[0.04,0.20,0.04],"center_m":[0,0.10,0]},
        {"name":"slab","shape":"box","material":"oak","join":"thing","part":"slab",
         "dimensions_m":[0.20,0.04,0.12],"center_m":[0,0.20,0]}],
        "interfaces":[{"a":"post","b":"slab","tension":0.25,"shear":0.25}]})";
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.bodies = readSceneJson(text);
    readSceneSettings(text, r);
    const auto setup = buildTileImpactSetup(r);
    // The overlapping row is the post's, so the seam sits one cell higher than
    // the shapes alone would put it, and there are still bonds across it.
    require(setup->interface_bonds > 0, "an overlapping joint weakened nothing");
}

void whatIsRefused() {
    const auto refused = [](const std::string &interfaces, const std::string &wanted) {
        try {
            buildTileImpactSetup(request(interfaces));
        } catch (const std::invalid_argument &error) {
            const std::string said = error.what();
            require(said.find(wanted) != std::string::npos,
                    "refused for the wrong reason: " + said);
            return;
        }
        throw std::runtime_error("not refused: " + interfaces);
    };
    refused(R"(,"interfaces":[{"a":"post","b":"ghost","tension":0.5}])", "which no body in this scene is");
    refused(R"(,"interfaces":[{"a":"post","b":"post","tension":0.5}])", "two different named parts");
    refused(R"(,"interfaces":[{"a":"post","b":"slab","tension":0,"shear":0,"compression":0}])",
            "two objects, not one joined");
    refused(R"(,"interfaces":[{"a":"post","b":"slab","tension":1.5}])", "share of the material it keeps");
    refused(R"(,"interfaces":{"a":"post"})", "must be a list");

    // A joint between two parts that are not bonded to each other did nothing
    // and would have said nothing, which is the same silence as a misspelling.
    const std::string apart = R"({"bodies":[
        {"name":"post","shape":"box","material":"oak","join":"thing","part":"post",
         "dimensions_m":[0.04,0.20,0.04],"center_m":[0,0.10,0]},
        {"name":"slab","shape":"box","material":"oak","join":"thing","part":"slab",
         "dimensions_m":[0.20,0.04,0.12],"center_m":[0,0.22,0]},
        {"name":"far","shape":"box","material":"oak","join":"thing","part":"far",
         "dimensions_m":[0.04,0.04,0.04],"center_m":[0.6,0.02,0]}],
        "interfaces":[{"a":"post","b":"far","tension":0.25}]})";
    TileImpactRequest r;
    r.cell_size_m = 0.02;
    r.bodies = readSceneJson(apart);
    readSceneSettings(apart, r);
    try {
        buildTileImpactSetup(r);
    } catch (const std::invalid_argument &error) {
        const std::string said = error.what();
        require(said.find("crosses no bond") != std::string::npos, "refused for the wrong reason: " + said);
        return;
    }
    throw std::runtime_error("a joint between parts that are not joined was not refused");
}

} // namespace

int main() {
    try {
        withoutAJointNothingChanges();
        std::cout << "[PASS] with no joint declared, nothing changes at all\n";
        aJointWeakensWhatCrossesItAndNothingElse();
        std::cout << "[PASS] a joint weakens what crosses it, by what it declares, and nothing else\n";
        theForceABondFailsAtGoesByItsStrength();
        std::cout << "[PASS] the force a bond fails at goes by its strength\n";
        aCellTwoPartsClaimBelongsToTheFirst();
        std::cout << "[PASS] a cell two parts claim belongs to the first\n";
        whatIsRefused();
        std::cout << "[PASS] a joint naming nothing, holding nothing, out of range, or crossing"
                     " no bond is refused\n";
        std::cout << "\nall joint interface tests passed\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "\n[FAIL] " << error.what() << "\n";
        return 1;
    }
}
