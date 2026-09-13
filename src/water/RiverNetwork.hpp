#pragma once

// The water beyond the detailed valley, held coarsely: a river network.
//
// NODES hold water and have a level: a reservoir, a lake, a spring's pool,
// the junction where two rivers meet. REACHES join them and carry discharge
// along a channel. It is the one-dimensional counterpart of ShallowWater, for
// the regions nobody is standing in (docs/watershed.md): a handful of numbers
// a reach instead of thousands of columns, on its own clock, with its own
// ledger -- where a reservoir nobody is looking at goes on filling.
//
// THE MODEL
//
// A reach is a channel of declared width whose bed falls in a straight line
// from one end to the other, cut into cells. Each cell holds a water level;
// each face -- between two cells, or between an end cell and the node there --
// carries a discharge. The discharge obeys the local inertial form of the
// Saint-Venant momentum equation (Bates, Horritt & Fewtrell 2010): the water
// is accelerated by the fall of its surface and held back by the bed's Manning
// friction, the same law and by default the same n as the detailed water's,
// the friction taken semi-implicitly so a shallow face cannot reverse its own
// flow:
//
//     q' = (q - g h dt dEta/dx) / (1 + g dt n^2 |q| / h^(7/3)),    Q = q width
//
// h being the depth over the higher of the two beds at the face. (A face can
// be made to start from its own discharge blended with its neighbours' --
// NetworkSettings::theta, after de Almeida, Bates, Freer & Souvignet 2012 --
// and by default is not: see there for why.) It leaves out
// the advection of momentum, so it covers slow, deep, subcritical flow -- a
// river, not a torrent. That is its DECLARED regime: a face whose Froude
// number would pass the limit is held to it, and counted, so a reach run
// outside what it covers says so.
//
// WHAT IT KEEPS EXACTLY
//
// - Mass, to rounding. Every face's discharge leaves one cell and enters the
//   next. A cell or node asked for more than it holds gives what it holds,
//   shared over the faces it is losing water through, both sides of each face
//   seeing the same flux. The ledger counts what is fed from beyond the world,
//   what goes out to it, what crosses to and from the detailed region, and
//   anything rounding takes below empty that has to be put back.
// - A lake at rest. The state is the LEVEL, as in ShallowWater, and a node's
//   level is worked out again only when its volume changes, so still water at
//   one level has exactly no fall across any face and exactly no flux.
// - Its own clock. advance(dt) takes exactly dt, in as many substeps as the
//   stability limit of its fastest wave needs.
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
#include <vector>

namespace banjo::water {

// How much water a node holds at a level.
class StageStorage {
public:
    StageStorage() = default;
    // Vertical sides: volume = (level - bed) * area.
    [[nodiscard]] static StageStorage prism(double bed_m, double area_m2);
    // Levels, rising, and the volume held at each, the first holding none;
    // above the last it goes on at the last segment's area.
    [[nodiscard]] static StageStorage table(const std::vector<std::pair<double, double>> &level_volume);
    // The ground of a basin region: bed heights on an nx x nz grid (i fastest)
    // of cells each `cell_area_m2`, and the cell its lake starts from. The
    // volume at a level is what a lake at rest at that level holds over the
    // cells it reaches from there -- across saddles lower than the level,
    // never through ground higher -- which is exactly what ShallowWater holds
    // with each of those columns set to that surface.
    [[nodiscard]] static StageStorage fromGround(int nx, int nz, const std::vector<double> &bed_m,
                                                 double cell_area_m2, std::size_t seed);

    [[nodiscard]] double volume(double level_m) const;
    // The level a volume stands at. Where the lake has reached a saddle, the
    // water that fills the ground beyond it does so with the level held at the
    // saddle, as it does in detail.
    [[nodiscard]] double level(double volume_m3) const;
    [[nodiscard]] double bottom() const { return level_.empty() ? 0.0 : level_.front(); }
    // The area of the surface at a level: how fast the level moves for a flow.
    [[nodiscard]] double area(double level_m) const;
    [[nodiscard]] bool empty() const { return level_.empty(); }
    [[nodiscard]] std::size_t breakPoints() const { return level_.size(); }

private:
    // Break points, rising: at level_[k] the volume steps from below_[k] to
    // above_[k] (a saddle reached, the ground beyond it filling at that level),
    // and rises at slope_[k] cubic metres a metre until the next.
    std::vector<double> level_, below_, above_, slope_;
};

struct NetworkSettings {
    double gravity_m_s2{9.81};
    // The bed, where a reach declares none: the detailed water's own, 0.03, a
    // clean natural stream. DECLARED, not calibrated to any river.
    double manning_n{0.03};
    // Fraction of the local inertial scheme's stability limit; Bates et al.
    // (2010) use 0.7.
    double cfl{0.7};
    // How much of a face's own discharge it starts a substep from, the rest
    // being its neighbours' (de Almeida et al. 2012) -- a dry face's nothing
    // included, as at a wall. 1, the default, is Bates et al.'s scheme. Below
    // 1 damps the oscillation of deep, lightly rubbed water from cell to cell,
    // at the price of a viscosity of the order of the cell and the wave speed:
    // it holds back a flood front, and where a reach runs from deep water into
    // shallow it moves discharge into the shallow end, where a cubic metre a
    // second carries more energy. Still water and steady uniform flow are the
    // same whatever it is.
    double theta{1.0};
    // A face thinner than this carries nothing.
    double dry_m{1.0e-5};
    // The Froude number a face is held to: the regime this model covers.
    double froude_limit{1.0};
    // The longest substep, whatever the stability limit allows.
    double max_step_s{2.0};
};

struct NetworkStats {
    double time_s{};
    std::uint64_t substeps{};
    double last_substep_s{};
    std::uint64_t faces_computed{};   // since the start
    std::uint64_t shared_out{};       // holders asked for more than they held
};

class RiverNetwork {
public:
    static constexpr int kOpen = -1;   // a reach end the detailed region's water takes

    struct Node {
        std::string name;
        StageStorage storage;
        bool junction{};                 // said as a junction rather than a basin
        double fed_m3_s{};               // from beyond the world
        bool has_outlet{};               // a broad-crested weir, to beyond the world
        double crest_m{}, outlet_width_m{};
        // Where it is, for a picture of it (not used by the physics).
        double x_m{}, z_m{};
        // State.
        double volume_m3{}, level_m{};
        // Its own ledger: volume = initial + fed - out + across + from_reaches + numerical.
        double initial_m3{}, fed_m3{}, out_m3{}, across_m3{}, from_reaches_m3{}, numerical_m3{};
        // Over the last substep (out, reaches) and the last exchange (across), m^3/s.
        double out_rate_m3_s{}, across_rate_m3_s{}, from_reaches_rate_m3_s{};
    };

    struct Reach {
        std::string name;
        int from{kOpen}, to{kOpen};      // node indices, or kOpen for the detailed region's water
        double length_m{}, width_m{}, bed_from_m{}, bed_to_m{};
        double manning_n{};              // 0: the network's
        int cells{};
        // Its course, for a picture of it: points from the `from` end to the
        // `to` end (not used by the physics; the length is declared).
        std::vector<std::pair<double, double>> path_m;
        // State: the level of each cell, and the discharge through each face
        // -- face 0 at `from`, face `cells` at `to` -- positive from `from`
        // towards `to`. An open end's face is the detailed water's: what it
        // last passed is kept there for the report.
        std::vector<double> level_m, q_m3_s;
        // Derived from the declaration.
        double dx_m{};
        std::vector<double> bed_m;       // under each cell's centre
        // Its own ledger's share: water it started with, what crossed its open
        // ends from the detailed region (net in), and what rounding put back.
        double initial_m3{}, across_m3{}, numerical_m3{};
        // The largest Froude number at any face inside it in the last substep,
        // and how many times one has been held to the limit. Its end faces are
        // held too where the water falls freely into a node below -- a brink,
        // passing the critical discharge, as the detailed water's mouths do --
        // and that is the boundary, not the reach outside its regime: not counted.
        double froude_now{};
        std::uint64_t froude_held{};
    };

    // Where the detailed region's water meets the network: a node, or a
    // reach's open end.
    struct Endpoint {
        int node{kOpen};
        int reach{kOpen};
        bool at_to{};                    // the reach's `to` end, else its `from` end
    };

    explicit RiverNetwork(NetworkSettings settings = {});

    // A node, standing at `level_m` (at least its bottom); its index.
    int addNode(Node node, double level_m);
    // A reach, `depth_m` deep over its bed in every cell and passing
    // `discharge_m3_s` through every face; its index. Both ends may not be
    // open, nor both at one node.
    int addReach(Reach reach, double depth_m, double discharge_m3_s);
    // Still water standing at one level along a reach (cells whose bed stands
    // higher are dry), passing nothing.
    void standReach(std::size_t reach, double level_m);
    // Start the ledgers from the water as it stands.
    void resetLedger();

    [[nodiscard]] const std::vector<Node> &nodes() const { return nodes_; }
    [[nodiscard]] const std::vector<Reach> &reaches() const { return reaches_; }
    [[nodiscard]] const NetworkSettings &settings() const { return settings_; }
    [[nodiscard]] const NetworkStats &stats() const { return stats_; }
    [[nodiscard]] int nodeNamed(const std::string &name) const;
    [[nodiscard]] int reachNamed(const std::string &name) const;

    // What is fed into a node from beyond the world, from now.
    bool setFeed(const std::string &node, double discharge_m3_s);

    // The detailed region's side. Its water sees an endpoint's level and the
    // speed the network's water is moving out across it (positive out of the
    // network, metres a second); after its own stride it hands over what
    // crossed -- into the network positive -- and the network takes exactly
    // that. Rates are over the stride; startExchange() begins a stride's.
    [[nodiscard]] double levelAt(const Endpoint &end) const;
    [[nodiscard]] double speedOut(const Endpoint &end) const;
    void startExchange();
    void exchange(const Endpoint &end, double into_m3, double dt_s);

    // Exactly dt_s of time, in as many substeps as the stability limit needs.
    // Returns how many.
    int advance(double dt_s);
    [[nodiscard]] double stableStep() const;

    [[nodiscard]] double volume() const;
    [[nodiscard]] double reachVolume(std::size_t reach) const;
    // The totals of every node's and reach's ledger, and what rounding left:
    // volume - (initial + fed - out + across + numerical).
    struct Totals {
        double initial_m3{}, fed_m3{}, out_m3{}, across_m3{}, numerical_m3{};
    };
    [[nodiscard]] Totals totals() const;
    [[nodiscard]] double residual() const;
    [[nodiscard]] double timeS() const { return stats_.time_s; }

    // Everything that makes a node or a reach what it is, for carrying it
    // into a world opened again: its state and its ledger, bit for bit.
    struct NodeState {
        double volume_m3{}, level_m{};
        double initial_m3{}, fed_m3{}, out_m3{}, across_m3{}, from_reaches_m3{}, numerical_m3{};
    };
    struct ReachState {
        std::vector<double> level_m, q_m3_s;
        double initial_m3{}, across_m3{}, numerical_m3{};
        std::uint64_t froude_held{};
    };
    [[nodiscard]] NodeState nodeState(std::size_t node) const;
    [[nodiscard]] ReachState reachState(std::size_t reach) const;
    void restoreNode(std::size_t node, const NodeState &state);
    // False, and nothing changed, when it was saved with another number of cells.
    bool restoreReach(std::size_t reach, const ReachState &state);
    void restoreClock(double time_s) { stats_.time_s = time_s; }

private:
    // One substep of `dt`, the stability limit being `limit`.
    void substep(double dt, double limit);
    // The bed the water crosses at a reach's end face: its own end's bed, or
    // the node's bottom where that is higher.
    [[nodiscard]] double endBed(const Reach &reach, bool at_to) const;

    NetworkSettings settings_;
    std::vector<Node> nodes_;
    std::vector<Reach> reaches_;
    NetworkStats stats_;
    // The widths of the reaches meeting each node: how short a small node is.
    std::vector<double> node_width_;
    // Scratch, per substep.
    std::vector<double> node_dv_, node_out_, node_share_;
    std::vector<std::vector<double>> cell_dv_, cell_out_, cell_share_, q_old_;
};

} // namespace banjo::water
