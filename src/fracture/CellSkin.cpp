#include "fracture/CellSkin.hpp"
#include <algorithm>
#include <cmath>
#include <map>
#include <numeric>
#include <stdexcept>

namespace banjo {
namespace {
void require(bool value,const char *message){if(!value)throw std::invalid_argument(message);}
bool finite(Vec3 v){return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
void validate(std::span<const SkinCell> cells){
    require(!cells.empty()&&cells.size()<=4096,"skin cell budget exceeded or empty");
    for(const auto &c:cells){
        require(finite(c.reference_center_m)&&finite(c.center_world_m),"nonfinite skin cell");
        for(auto axis:c.half_axes_world_m)require(finite(axis),"nonfinite skin axis");
        for(int g:c.grid)require(g>=-1000000&&g<=1000000,"skin grid outside bounds");
    }
}
// Two triangles per quad; x/y/z positive face winding is outward.
constexpr std::array<std::array<unsigned,4>,3> positiveCorners{{{{1,3,7,5}},{{2,6,7,3}},{{4,5,7,6}}}};
}
CellSkinTopology buildCellSkinTopology(std::span<const SkinCell> cells,
    std::span<const SkinFaceLink> face_links,std::uint64_t revision){
    validate(cells);require(face_links.size()<=3*cells.size(),"skin face link budget exceeded");
    std::map<std::uint32_t,unsigned> ids;
    std::map<std::array<int,3>,unsigned> occupied;
    for(unsigned i=0;i<cells.size();++i){
        require(ids.emplace(cells[i].id,i).second,"duplicate skin cell ID");
        require(occupied.emplace(cells[i].grid,i).second,"duplicate skin grid cell");
    }
    std::map<std::pair<unsigned,unsigned>,bool> links;
    std::vector<unsigned> roots(cells.size()*8);std::iota(roots.begin(),roots.end(),0);
    auto root=[&](unsigned a){while(roots[a]!=a){roots[a]=roots[roots[a]];a=roots[a];}return a;};
    for(auto link:face_links){
        require(ids.contains(link.a)&&ids.contains(link.b)&&link.a!=link.b,"invalid skin face link ID");
        unsigned a=ids.at(link.a),b=ids.at(link.b);unsigned axis=0;int distance=0;
        for(unsigned k=0;k<3;++k){const int d=cells[b].grid[k]-cells[a].grid[k];distance+=std::abs(d);if(d)axis=k;}
        require(distance==1,"skin face link must join face neighbors");
        require(links.emplace(std::minmax(a,b),link.live).second,"duplicate skin face link");
        if(!link.live)continue;
        require(cells[a].component==cells[b].component,"live skin link crosses components");
        if(cells[b].grid[axis]<cells[a].grid[axis])std::swap(a,b);
        for(unsigned corner=0;corner<8;++corner)if(corner&(1u<<axis)){
            const auto other=corner^(1u<<axis);roots[root(a*8+corner)]=root(b*8+other);
        }
    }
    CellSkinTopology topology;topology.revision=revision;
    std::map<unsigned,unsigned> vertices;
    for(unsigned i=0;i<cells.size();++i){
        topology.cell_ids.push_back(cells[i].id);topology.components.push_back(cells[i].component);topology.grids.push_back(cells[i].grid);
        std::array<unsigned,8> corners{};
        for(unsigned k=0;k<8;++k){const auto r=root(i*8+k);auto [it,inserted]=vertices.emplace(r,unsigned(vertices.size()));(void)inserted;corners[k]=it->second;}
        topology.corner_vertices.push_back(corners);
    }
    topology.vertex_count=unsigned(vertices.size());
    for(unsigned i=0;i<cells.size();++i)for(unsigned axis=0;axis<3;++axis)for(bool positive:{false,true}){
        auto adjacent=cells[i].grid;adjacent[axis]+=positive?1:-1;const auto neighbor=occupied.find(adjacent);
        const bool interior=neighbor!=occupied.end();
        if(interior){const auto found=links.find(std::minmax(i,neighbor->second));
            require(found!=links.end(),"occupied skin neighbors require explicit face link");if(found->second)continue;}
        SkinFace face;face.cell_index=i;face.component=cells[i].component;face.axis=axis;face.positive=positive;face.fracture=interior;
        auto corners=positiveCorners[axis];if(!positive){for(auto &c:corners)c^=1u<<axis;std::reverse(corners.begin(),corners.end());}
        for(unsigned k=0;k<4;++k)face.corners[k]=topology.corner_vertices[i][corners[k]];
        topology.faces.push_back(face);
    }
    return topology;
}
CellSkinMesh evaluateCellSkin(const CellSkinTopology &topology,std::span<const SkinCell> cells){
    validate(cells);
    require(topology.cell_ids.size()==cells.size()&&topology.components.size()==cells.size()&&topology.grids.size()==cells.size()&&topology.corner_vertices.size()==cells.size(),"stale skin cell membership");
    require(topology.vertex_count<=cells.size()*8&&topology.faces.size()<=cells.size()*6,"invalid skin topology budget");
    std::vector<Vec3> vertices(topology.vertex_count);std::vector<unsigned> counts(topology.vertex_count);
    for(unsigned i=0;i<cells.size();++i){const auto &cell=cells[i];
        require(topology.cell_ids[i]==cell.id&&topology.components[i]==cell.component&&topology.grids[i]==cell.grid,"stale skin topology identity");
        for(unsigned k=0;k<8;++k){Vec3 p=cell.center_world_m;for(unsigned axis=0;axis<3;++axis)p+=cell.half_axes_world_m[axis]*((k&(1u<<axis))?1.:-1.);
            const auto vertex=topology.corner_vertices[i][k];require(vertex<vertices.size(),"invalid skin vertex index");vertices[vertex]+=p;++counts[vertex];}
    }
    for(unsigned i=0;i<vertices.size();++i){require(counts[i]>0,"unused skin vertex");vertices[i]=vertices[i]/counts[i];require(finite(vertices[i]),"skin coordinate overflow");}
    CellSkinMesh mesh;mesh.revision=topology.revision;mesh.exposed_faces=unsigned(topology.faces.size());mesh.triangles.reserve(topology.faces.size()*2);
    for(const auto &face:topology.faces){
        require(face.cell_index<cells.size()&&face.component==cells[face.cell_index].component,"invalid skin face owner");
        for(auto vertex:face.corners)require(vertex<vertices.size(),"invalid skin face vertex");
        require(face.axis<3,"invalid skin face axis");
        if(face.fracture){
            ++mesh.fracture_faces;
            // Crack lips have separate material points even when the intact
            // perimeter is welded around a partial cut. A corner-only quad can
            // incorrectly seal that cut through alternate live corner paths.
            const auto &cell=cells[face.cell_index];const auto center=cell.center_world_m+cell.half_axes_world_m[face.axis]*(face.positive?1.:-1.);
            require(finite(center),"skin fracture center overflow");
            for(unsigned k=0;k<4;++k)mesh.triangles.push_back({{vertices[face.corners[k]],vertices[face.corners[(k+1)%4]],center},face.component,cell.id,true});
            continue;
        }
        for(auto tri:std::array<std::array<unsigned,3>,2>{{{{0,1,2}},{{0,2,3}}}}){
            mesh.triangles.push_back({{vertices[face.corners[tri[0]]],vertices[face.corners[tri[1]]],vertices[face.corners[tri[2]]]},face.component,cells[face.cell_index].id,face.fracture});
        }
    }
    return mesh;
}
}
