#include "fastlattice/MaterialContactRegion.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>

namespace banjo::fastlattice {
namespace {
bool finite(Vec3 p){return std::isfinite(p.x)&&std::isfinite(p.y)&&std::isfinite(p.z);}
}
MaterialContactTopology::MaterialContactTopology(std::uint32_t nodes,
    std::span<const std::uint32_t> a,std::span<const std::uint32_t> b):node_count_(nodes) {
    if(!nodes||nodes>1024||a.size()!=b.size()||a.size()>65536)
        throw std::invalid_argument("invalid bounded material contact topology");
    a_.assign(a.begin(),a.end());b_.assign(b.begin(),b.end());offsets_.assign(nodes+1,0);
    for(std::size_t i=0;i<a.size();++i) {
        if(a[i]>=nodes||b[i]>=nodes||a[i]==b[i])throw std::invalid_argument("invalid material contact edge");
        ++offsets_[a[i]+1];++offsets_[b[i]+1];
    }
    std::partial_sum(offsets_.begin(),offsets_.end(),offsets_.begin());
    edges_.resize(2*a.size());auto cursor=offsets_;
    for(std::uint32_t i=0;i<a.size();++i){edges_[cursor[a[i]]++]=i;edges_[cursor[b[i]]++]=i;}
}
MaterialContactRegion MaterialContactTopology::select(std::uint32_t seed,
    std::span<const std::uint8_t> alive,const MaterialContactRegionSettings &settings,
    const std::function<Vec3(std::uint32_t)> &position,const std::function<bool(std::uint32_t)> &movable) const {
    if(seed>=node_count_||alive.size()!=a_.size()||!position||!movable||
       !std::isfinite(settings.radius_m)||settings.radius_m<1e-9||settings.radius_m>100||
       !settings.maximum_hops||settings.maximum_hops>64||!settings.maximum_nodes||settings.maximum_nodes>64||
       !settings.maximum_edge_visits||settings.maximum_edge_visits>65536)
        throw std::invalid_argument("invalid bounded material contact selection");
    if(!movable(seed))throw std::invalid_argument("material contact seed is clamped");
    const Vec3 origin=position(seed);if(!finite(origin))throw std::invalid_argument("nonfinite material contact seed");
    MaterialContactRegion out;out.seed=seed;out.nodes.push_back(seed);
    std::vector<std::uint8_t> visited(node_count_);visited[seed]=1;
    std::vector<std::uint32_t> depth{0};depth.reserve(settings.maximum_nodes);
    for(std::size_t cursor=0;cursor<out.nodes.size();++cursor) {
        if(depth[cursor]==settings.maximum_hops)continue;
        const auto here=out.nodes[cursor];std::vector<std::uint32_t> next;
        for(auto i=offsets_[here];i<offsets_[here+1];++i) {
            if(++out.edge_visits>settings.maximum_edge_visits)
                throw std::invalid_argument("material contact edge budget exceeded");
            const auto edge=edges_[i];
            if(alive[edge]>1)throw std::invalid_argument("invalid material contact bond aliveness");
            if(!alive[edge])continue;
            const auto other=a_[edge]==here?b_[edge]:a_[edge];
            if(visited[other])continue;
            if(!movable(other)){++out.clamped_edge_visits;continue;}
            const Vec3 relative=position(other)-origin;
            if(!finite(relative))throw std::invalid_argument("nonfinite material contact neighbour");
            if(std::hypot(relative.x,relative.y,relative.z)>settings.radius_m)continue;
            next.push_back(other);
        }
        std::sort(next.begin(),next.end());next.erase(std::unique(next.begin(),next.end()),next.end());
        for(const auto other:next) {
            if(visited[other])continue;
            if(out.nodes.size()==settings.maximum_nodes)
                throw std::invalid_argument("material contact node budget exceeded");
            visited[other]=1;out.nodes.push_back(other);depth.push_back(depth[cursor]+1);
            out.maximum_hop=std::max(out.maximum_hop,depth.back());
        }
    }
    return out;
}
}
