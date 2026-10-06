#include "terrain/Environment.hpp"
#include "terrain/GroundWork.hpp"
#include "material/MaterialCatalog.hpp"
#include "rigid/JoltWorld.hpp"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo::terrain {
namespace {
using Json = nlohmann::json;
constexpr double kCell = .05;
constexpr std::size_t kMostDebris = 256;
constexpr MatterBodyId kFirstDebris = 800000000, kLastDebris = 899999999;
Json vec(Vec3 v) { return Json::array({v.x,v.y,v.z}); }
Vec3 vectorOf(const Json &j) {
    if (!j.is_array() || j.size()!=3) throw std::invalid_argument("invalid matter vector");
    Vec3 v{j[0].get<double>(),j[1].get<double>(),j[2].get<double>()};
    if (!std::isfinite(v.x)||!std::isfinite(v.y)||!std::isfinite(v.z))
        throw std::invalid_argument("nonfinite matter vector");
    return v;
}
bool soft(RunKind k) { return k==RunKind::Soil||k==RunKind::LooseSoil||k==RunKind::Sand; }
double density(RunKind k) { return k==RunKind::Sand?sandMaterial().density_kg_m3:
    soft(k)?soilMaterial().density_kg_m3:rockMaterial().density_kg_m3; }
const char *materialName(RunKind k) { return k==RunKind::Sand?"sand":soft(k)?"soil":"concrete"; }
MaterialDefinition contactMaterial(RunKind k) {
    auto m=makeReferenceMaterial(MaterialPreset::Concrete,0);
    m.name=materialName(k);m.density_kg_m3=density(k);
    if (soft(k)) {
        m.young_modulus_pa=.05e9;m.poisson_ratio=.3;
        m.static_friction=.7;m.dynamic_friction=.6;m.friction=.6;
        m.contact_damping_ratio=.6;m.derive_restitution_from_damping=true;
    }
    return m;
}
Json pose(const RigidSnapshot &p) {
    return {{"center_m",vec(p.center_of_mass_world_m)},
        {"orientation_wxyz",{p.orientation_world.w,p.orientation_world.x,p.orientation_world.y,p.orientation_world.z}},
        {"velocity_m_s",vec(p.linear_velocity_m_s)},{"angular_velocity_rad_s",vec(p.angular_velocity_rad_s)}};
}
RigidSnapshot readPose(const Json &j) {
    RigidSnapshot p;p.center_of_mass_world_m=vectorOf(j.at("center_m"));
    p.linear_velocity_m_s=vectorOf(j.at("velocity_m_s"));
    p.angular_velocity_rad_s=vectorOf(j.at("angular_velocity_rad_s"));
    const auto &q=j.at("orientation_wxyz");
    if (!q.is_array()||q.size()!=4) throw std::invalid_argument("invalid matter orientation");
    p.orientation_world={q[0].get<double>(),q[1].get<double>(),q[2].get<double>(),q[3].get<double>()};
    const double n=p.orientation_world.w*p.orientation_world.w+p.orientation_world.x*p.orientation_world.x+
        p.orientation_world.y*p.orientation_world.y+p.orientation_world.z*p.orientation_world.z;
    if (!std::isfinite(n)||std::abs(n-1)>1e-5) throw std::invalid_argument("invalid matter orientation norm");
    return p;
}
// Constituent cells are numerical samples. No cell becomes an independent
// shard. Contacts use merged material slabs while provenance keeps the cells.
RigidCompoundDescription description(const Json &record) {
    RigidCompoundDescription out;out.body_id=record.at("id").get<MatterBodyId>();
    const Vec3 center=vectorOf(record.at("source_center_m"));
    out.state=readPose(record.at("pose"));
    out.mass_kg=record.at("mass_kg").get<double>();
    out.material=contactMaterial(static_cast<RunKind>(record.at("slabs")[0].at("run_kind").get<int>()));
    for (const auto &s:record.at("slabs")) {
        const auto k=static_cast<RunKind>(s.at("run_kind").get<int>());
        RigidPrimitive shape;shape.kind=PrimitiveKind::Box;shape.dimensions_m=vectorOf(s.at("size_m"));
        const Vec3 local=vectorOf(s.at("source_center_m"))-center;
        const double mass=shape.volume()*density(k);const Mat3 own=shape.inertia(mass);
        out.parts.push_back({shape,local,{},contactMaterial(k),0});
        const double r[3]{local.x,local.y,local.z};const double r2=dot(local,local);
        for (unsigned a=0;a<3;++a) for (unsigned b=0;b<3;++b)
            out.inertia_local_kg_m2.m[a][b]+=own.m[a][b]+mass*((a==b?r2:0)-r[a]*r[b]);
    }
    return out;
}
Json volumes(const Volumes &v) { return {{"rock_m3",v.rock_m3},{"soil_m3",v.soil_m3},{"sand_m3",v.sand_m3}}; }
}

std::string Environment::excavateCell(JoltWorld &world,const Vec3 &at,double work,const std::string &source,bool record_request) {
    if (!std::isfinite(work)||work<0||work>1e6||source.size()>128||
        !std::isfinite(at.x)||!std::isfinite(at.y)||!std::isfinite(at.z))
        throw std::invalid_argument("work-cut needs a finite point and budget of 0 to 1 MJ");
    Json answer{{"model","work-cut-v2"},{"requested_work_j",work},{"consumed_work_j",0},
        {"work_source",source},{"broken_share",0},{"kind","not supported"},{"supported",false},
        {"loosened",volumes({})},{"mass_kg",0},{"body_id",nullptr}};
    const Json request{{"at_m",vec(at)},{"work_j",work},{"work_source",source}};
    if(record_request&&!source.empty()) if(const auto existing=cut_receipts_.find(source);existing!=cut_receipts_.end()) {
        const auto receipt=Json::parse(existing->second);
        if(receipt.at("request")!=request)throw std::invalid_argument("funded work source was already used for a different cut request");
        return receipt.at("answer").dump();
    }
    const auto finish=[&]() {
        if(record_request)cut_receipts_[source]=Json{{"request",request},{"answer",answer}}.dump();return answer.dump();
    };
    const auto refuse=[&](const char *why) {answer["why"]=why;answer["consumed_work_j"]=0;
        answer["supported"]=false;answer["kind"]="not supported";return answer.dump();};
    if (!(work>0)||source.empty()) return refuse("a positive funded work budget and named source are required");
    if(record_request&&cut_receipts_.size()>=4096)return refuse("funded cut receipt limit reached; world receipt archival is required");
    const int region=regionAt(at.x,at.z);
    if (region==-2) return refuse("there is no ground at that point");
    auto &field=fieldOf(region);const auto c=field.cellAt(at.x,at.z);
    if (!c||!field.columnSurface()) return refuse("work-cut currently requires column surface geometry");
    if (waterDepthAt(at.x,at.z)>kWetGroundM) return refuse("wet work-cut and debris/water coupling are unsupported");
    const auto &g=field.grid();const double q=g.dx;
    if(at.y<field.floor()+q||at.y>field.height(*c)+q)
        return refuse("selected height is outside the extractable terrain bounds");
    if(field.sand(*c)>1e-12&&field.looseSoil(*c)>1e-12)
        return refuse("mixed granular soil/sand work-cut is unsupported");
    const int subdivisions=static_cast<int>(std::llround(q/kCell));
    if (subdivisions<1||subdivisions>10||std::abs(subdivisions*kCell-q)>1e-9)
        return refuse("work-cut requires 5 cm compatible columns no larger than 50 cm");
    if (debris_.size()>=kMostDebris) return refuse("native cut-component limit reached; collect matter before resuming");
    const int level=static_cast<int>(std::ceil(std::min(at.y,field.height(*c)-1e-9)/q))-1;
    const double lo=std::max(level*q,field.floor()+q),hi=std::min((level+1)*q,field.height(*c));
    if (!(hi>lo)) return refuse("there is no extractable matter in the selected cell");
    const double x=g.xOf(static_cast<int>(*c%static_cast<std::size_t>(g.nx)));
    const double z=g.zOf(static_cast<int>(*c/static_cast<std::size_t>(g.nx)));
    Json slabs=Json::array(),cells=Json::array();
    double cost=0,totalmass=0;Vec3 weighted{};Volumes expected;
    const auto prefix="terrain:"+std::to_string(region)+":"+std::to_string(*c)+":"+std::to_string(level);
    // Preserve exact beds and the actual sand/loose mixture proportions, rather
    // than classifying their combined mass by its majority display material.
    const auto slab=[&](RunKind k,double bottom,double top) {
        bottom=std::max(bottom,lo);top=std::min(top,hi);
        if (isVoid(k)||!(top>bottom)) return;
        const double volume=q*q*(top-bottom),mass=volume*density(k);
        const Vec3 center{x,.5*(bottom+top),z};
        slabs.push_back({{"run_kind",int(k)},{"material",materialName(k)},
            {"size_m",vec({q,top-bottom,q})},{"source_center_m",vec(center)}});
        totalmass+=mass;weighted+=mass*center;
        if (k==RunKind::Sand) expected.sand_m3+=volume;
        else if (soft(k)) expected.soil_m3+=volume;
        else expected.rock_m3+=volume;
        if (soft(k)) {
            auto gm=k==RunKind::Sand?sandMaterial():soilMaterial();
            if (k==RunKind::LooseSoil)gm.cohesion_pa=0;
            ToolPointShape shape{q,q,30,q};
            cost+=(penetrationWorkJ(gm,shape,q)+passiveResistanceN(gm,q,q)*breakoutTravelM(q))*volume/(q*q*q);
        } else cost+=specificEnergyJPerM3(groundHardnessPa(k))*volume;
        for (int j=0;j<subdivisions;++j)for(int i=0;i<subdivisions;++i)
            for (int y=static_cast<int>(std::floor(bottom/kCell));y<static_cast<int>(std::ceil(top/kCell));++y) {
                const double b=std::max(bottom,y*kCell),t=std::min(top,(y+1)*kCell);if(t-b<1e-12)continue;
                const double v=kCell*kCell*(t-b);
                const Vec3 p{x-q/2+(i+.5)*kCell,(b+t)/2,z-q/2+(j+.5)*kCell};
                cells.push_back({{"id",prefix+":generation:"+std::to_string(next_debris_id_)+":"+std::to_string(slabs.size()-1)+":"+std::to_string(i)+":"+std::to_string(j)+":"+std::to_string(y)},
                    {"material",materialName(k)},{"run_kind",int(k)},{"density_kg_m3",density(k)},
                    {"volume_m3",v},{"mass_kg",v*density(k)},{"size_m",vec({kCell,t-b,kCell})},
                    {"source_center_m",vec(p)},{"damage",nullptr},{"temperature_k",nullptr}});
            }
    };
    double bottom=field.floor();const auto &beds=field.beds();
    for(std::uint32_t k=0;k<beds.count[*c];++k) {
        const auto ix=beds.start[*c]+k;const double top=beds.top[ix];
        slab(static_cast<RunKind>(beds.kind[ix]),bottom,top);bottom=top;
    }
    slab(RunKind::Soil,bottom,bottom+field.soil(*c));bottom+=field.soil(*c);
    slab(RunKind::LooseSoil,bottom,bottom+field.looseSoil(*c));bottom+=field.looseSoil(*c);
    slab(RunKind::Sand,bottom,bottom+field.sand(*c));
    if (slabs.empty()||!(cost>0)||cells.size()>2000) return refuse("selected regime has no supported work-cut law");
    // A void separating slabs means disconnected matter: do not weld it into
    // one cut body. Adjacent strata can remain one declared rigid component.
    for(std::size_t k=1;k<slabs.size();++k) {
        const auto previous=vectorOf(slabs[k-1]["source_center_m"]),now=vectorOf(slabs[k]["source_center_m"]);
        if (std::abs(previous.y+.5*slabs[k-1]["size_m"][1].get<double>()-
            (now.y-.5*slabs[k]["size_m"][1].get<double>()))>1e-9)
            return refuse("a selected cell spans disconnected matter; select a contiguous band");
    }
    const auto signature=Json{{"slabs",slabs},{"matter_revision",field.matterRevision(*c)}}.dump();
    double paid=0;Json work_sources=Json::array();
    if (const auto p=cut_progress_.find(prefix);p!=cut_progress_.end()) {
        const auto saved=Json::parse(p->second);
        if (saved.at("signature")==signature) {
            paid=saved.at("work_j").get<double>();work_sources=saved.value("work_sources",Json::array());
        }
    }
    const double consumed=std::min(work,std::max(0.,cost-paid));
    const double nextpaid=paid+consumed;
    if(consumed>0) {
        bool combined=false;
        for(auto &entry:work_sources)if(entry.at("source")==source) {
            entry["work_j"]=entry.at("work_j").get<double>()+consumed;combined=true;break;
        }
        if(!combined)work_sources.push_back({{"source",source},{"work_j",consumed}});
    }
    answer["supported"]=true;answer["required_work_j"]=cost;answer["consumed_work_j"]=consumed;
    answer["broken_share"]=std::min(1.,nextpaid/cost);answer["ground"]=slabs[0]["material"];
    answer["why"]="explicit work-cut reduction; no constitutive fracture or granular flow";
    if (nextpaid+1e-9<cost) {
        cut_progress_[prefix]=Json{{"signature",signature},{"work_j",nextpaid},{"work_source",source},{"work_sources",work_sources}}.dump();
        cut_source_work_j_+=consumed;answer["kind"]="working cell";return finish();
    }
    TerrainField candidate=field;
    const auto edit=candidate.breakOut(x,z,lo,hi);
    if (std::abs(edit.moved.rock_m3-expected.rock_m3)>1e-10||
        std::abs(edit.moved.soil_m3-expected.soil_m3)>1e-10||std::abs(edit.moved.sand_m3-expected.sand_m3)>1e-10)
        return refuse("cut geometry would remove unpaid neighboring or overlying matter");
    auto id=next_debris_id_;while(id<kLastDebris&&world.contains(id))++id;
    if(id>=kLastDebris)return refuse("native matter identity limit reached");
    const Vec3 center=weighted/totalmass;RigidSnapshot initial;initial.center_of_mass_world_m=center;
    Json record{{"id",id},{"model","work-cut-v2"},{"provenance","recorded-terrain-cut"},
        {"material_basis","concrete is existing terrain rock surrogate; dry soil/sand are rigid bulk cut components"},
        {"mass_kg",totalmass},{"volumes",volumes(expected)},{"source_center_m",vec(center)},
        {"slabs",slabs},{"cells",cells},{"source_work_j",cost},{"work_source",source},{"work_sources",work_sources},{"pose",pose(initial)}};
    // Allocate source record and native shape before changing terrain. No
    // simulation step can see the temporary overlap with the old collider.
    debris_.emplace(id,record.dump());
    auto display=record;display["cell_count"]=cells.size();display.erase("cells");
    try {debris_display_.emplace(id,display.dump());world.addCompound(description(record));}
    catch(...) {debris_.erase(id);debris_display_.erase(id);throw;}
    field=std::move(candidate);next_debris_id_=id+1;cut_progress_.erase(prefix);cut_source_work_j_+=consumed;
    EditEffect effect;effect.edit=edit;
    if(region>=0)regionEdited(&world,region,edit.cells,&effect);
    else {
        syncWaterBed(edit.cells);noteChanged(edit.cells);
        rebuildChunks(world,terrain_->takeDirtyChunks(),&effect);
        if(!regions_.empty())rebuildSeams(world,-1,edit.cells,&effect);
    }
    debris_world_=&world;
    answer["kind"]="cut component released";answer["loosened"]=volumes(expected);
    answer["mass_kg"]=totalmass;answer["body_id"]=id;answer["broken_share"]=1;
    return finish();
}

EditEffect Environment::detachDig(JoltWorld &world,double ax,double az,double bx,double bz,
                                 double width,double depth,double work,const std::string &source) {
    if(!std::isfinite(work)||work<0)throw std::invalid_argument("invalid measured detachment work");
    const int region=regionAt(ax,az);
    if(region==-2||regionAt(bx,bz)!=region)throw std::invalid_argument("physical tool wedge cannot span unsupported region boundaries");
    auto &field=fieldOf(region);const auto &g=field.grid();const double q=g.dx;
    const int divisions=static_cast<int>(std::llround(q/kCell));
    if(!field.columnSurface()||divisions<1||divisions>10||std::abs(divisions*kCell-q)>1e-9)
        throw std::invalid_argument("physical tool wedge requires 5 cm compatible column ground");
    const auto columns=field.columnsAlong(ax,az,bx,bz,width);
    if(columns.size()>32)throw std::invalid_argument("physical tool wedge exceeds 32 active columns");
    for(const auto c:columns) {
        const auto x=g.xOf(static_cast<int>(c%static_cast<std::size_t>(g.nx))),z=g.zOf(static_cast<int>(c/static_cast<std::size_t>(g.nx)));
        if(waterDepthAt(x,z)>kWetGroundM)throw std::invalid_argument("wet physical detachment is unsupported");
        if(field.sand(c)>1e-12&&field.looseSoil(c)>1e-12)
            throw std::invalid_argument("mixed granular soil/sand physical detachment is unsupported");
    }
    TerrainField candidate=field;const auto edit=candidate.dig(ax,az,bx,bz,width,depth);
    EditEffect effect;effect.edit=edit;if(edit.cells.empty())return effect;
    Json slabs=Json::array();
    const auto add=[&](RunKind kind,std::size_t c,double bottom,double top) {
        bottom=std::max(bottom,candidate.height(c));top=std::min(top,field.height(c));if(top-bottom<1e-12)return;
        const double x=g.xOf(static_cast<int>(c%static_cast<std::size_t>(g.nx))),z=g.zOf(static_cast<int>(c/static_cast<std::size_t>(g.nx)));
        slabs.push_back({{"run_kind",int(kind)},{"material",materialName(kind)},
            {"source_column",c},{"source_revision",field.matterRevision(c)},
            {"size_m",vec({q,top-bottom,q})},{"source_center_m",vec({x,(top+bottom)/2,z})}});
    };
    for(const auto c:edit.cells) {
        double bottom=field.rockTop(c);
        add(RunKind::Soil,c,bottom,bottom+field.soil(c));bottom+=field.soil(c);
        add(RunKind::LooseSoil,c,bottom,bottom+field.looseSoil(c));bottom+=field.looseSoil(c);
        add(RunKind::Sand,c,bottom,bottom+field.sand(c));
    }
    // Derive actual connected components from face-sharing occupied cut
    // slabs. Numerical column boundaries do not create an authored shard set.
    std::vector<int> group(slabs.size(),-1);int count=0;
    const auto adjacent=[&](std::size_t a,std::size_t b) {
        const auto pa=vectorOf(slabs[a]["source_center_m"]),pb=vectorOf(slabs[b]["source_center_m"]);
        const auto sa=vectorOf(slabs[a]["size_m"]),sb=vectorOf(slabs[b]["size_m"]);
        const double da[3]{pa.x-pb.x,pa.y-pb.y,pa.z-pb.z},ha[3]{(sa.x+sb.x)/2,(sa.y+sb.y)/2,(sa.z+sb.z)/2};
        for(int axis=0;axis<3;++axis)if(std::abs(std::abs(da[axis])-ha[axis])<1e-9) {
            bool overlap=true;for(int other=0;other<3;++other)if(other!=axis&&std::abs(da[other])>=ha[other]-1e-10)overlap=false;
            if(overlap)return true;
        }
        return false;
    };
    for(std::size_t k=0;k<slabs.size();++k)if(group[k]<0) {
        std::vector<std::size_t> queue{k};group[k]=count;
        for(std::size_t n=0;n<queue.size();++n)for(std::size_t j=0;j<slabs.size();++j)
            if(group[j]<0&&adjacent(queue[n],j)){group[j]=count;queue.push_back(j);}
        ++count;
    }
    if(debris_.size()+static_cast<std::size_t>(count)>kMostDebris)
        throw std::invalid_argument("native cut-component limit reached; collect actual matter before resuming");
    std::vector<Json> records;
    MatterBodyId next=next_debris_id_;
    Volumes accounted;
    for(int component=0;component<count;++component) {
        while(next<kLastDebris&&world.contains(next))++next;
        if(next>=kLastDebris)throw std::invalid_argument("native matter identity limit reached");
        Json occupied=Json::array(),cells=Json::array();double mass=0;Vec3 weighted{};Volumes moved;
        for(std::size_t k=0;k<slabs.size();++k)if(group[k]==component) {
            const auto &slab=slabs[k];occupied.push_back(slab);const auto kind=static_cast<RunKind>(slab["run_kind"].get<int>());
            const auto p=vectorOf(slab["source_center_m"]),size=vectorOf(slab["size_m"]);const double v=size.x*size.y*size.z,m=v*density(kind);
            mass+=m;weighted+=m*p;if(kind==RunKind::Sand)moved.sand_m3+=v;else moved.soil_m3+=v;
            const double bottom=p.y-size.y/2,top=p.y+size.y/2;
            for(int j=0;j<divisions;++j)for(int i=0;i<divisions;++i)
                for(int y=static_cast<int>(std::floor(bottom/kCell));y<static_cast<int>(std::ceil(top/kCell));++y) {
                    const double b=std::max(bottom,y*kCell),t=std::min(top,(y+1)*kCell);if(t-b<1e-12)continue;
                    const double volume=kCell*kCell*(t-b);
                    cells.push_back({{"id","terrain:"+std::to_string(region)+":"+std::to_string(slab["source_column"].get<std::size_t>())+
                        ":revision:"+std::to_string(slab["source_revision"].get<std::uint64_t>())+":generation:"+std::to_string(next)+
                        ":"+std::to_string(k)+":"+std::to_string(i)+":"+std::to_string(j)+":"+std::to_string(y)},
                        {"material",materialName(kind)},{"run_kind",int(kind)},{"density_kg_m3",density(kind)},
                        {"volume_m3",volume},{"mass_kg",volume*density(kind)},{"size_m",vec({kCell,t-b,kCell})},
                        {"source_center_m",vec({p.x-q/2+(i+.5)*kCell,(b+t)/2,p.z-q/2+(j+.5)*kCell})},
                        {"damage",nullptr},{"temperature_k",nullptr}});
                }
        }
        if(cells.size()>2000)throw std::invalid_argument("measured tool component exceeds 2000 active constituent cells");
        accounted.soil_m3+=moved.soil_m3;accounted.sand_m3+=moved.sand_m3;
        RigidSnapshot initial;initial.center_of_mass_world_m=weighted/mass;
        const double allocated_work=work*moved.total()/edit.moved.total();
        records.push_back({{"id",next},{"model","ground-work-v1-rigid-detachment"},{"provenance","recorded-terrain-cut"},
            {"material_basis","dry bulk cut components; granular flow and full contact work audit unsupported"},
            {"mass_kg",mass},{"volumes",volumes(moved)},{"source_center_m",vec(initial.center_of_mass_world_m)},
            {"slabs",occupied},{"cells",cells},{"source_work_j",allocated_work},{"work_source",source},
            {"work_sources",Json::array({{{"source",source},{"work_j",allocated_work}}})},{"pose",pose(initial)}});
        ++next;
    }
    if(std::abs(accounted.soil_m3-edit.moved.soil_m3)>1e-10||std::abs(accounted.sand_m3-edit.moved.sand_m3)>1e-10)
        throw std::invalid_argument("measured tool constituent transfer disagrees with the terrain edit");
    std::vector<MatterBodyId> added;
    try {
        for(const auto &r:records) {
            const auto id=r["id"].get<MatterBodyId>();debris_.emplace(id,r.dump());
            auto display=r;display["cell_count"]=r["cells"].size();display.erase("cells");debris_display_.emplace(id,display.dump());
            added.push_back(id);world.addCompound(description(r));
        }
    } catch(...) {
        for(const auto id:added){if(world.contains(id))world.removeAndDestroy(id);debris_.erase(id);debris_display_.erase(id);}throw;
    }
    field=std::move(candidate);next_debris_id_=next;cut_source_work_j_+=work;debris_world_=&world;
    if(region>=0)regionEdited(&world,region,edit.cells,&effect);
    else {syncWaterBed(edit.cells);noteChanged(edit.cells);rebuildChunks(world,terrain_->takeDirtyChunks(),&effect);
        if(!regions_.empty())rebuildSeams(world,-1,edit.cells,&effect);}
    return effect;
}

std::string Environment::debrisJson(bool include_cells) const {
    Json bodies=Json::array();
    for(const auto &[id,text]:include_cells?debris_:debris_display_) {
        auto body=Json::parse(text);
        if(debris_world_&&debris_world_->contains(id))body["pose"]=pose(debris_world_->snapshot(id));
        bodies.push_back(std::move(body));
    }
    return Json{{"schema","banjo.ground-debris.v1"},{"model","work-cut-v2"},{"bodies",bodies},
        {"source_work_j",cut_source_work_j_},{"maximum_components",kMostDebris},
        {"constitutive_fracture_supported",false},{"granular_flow_supported",false},
        {"full_system_energy_audited",false}}.dump();
}
std::string Environment::collectDebris(JoltWorld &world,MatterBodyId id,const Vec3 &at,double distance,
                                     const std::vector<MatterBodyId> &ignored_bodies) {
    if(!std::isfinite(distance)||distance<0||distance>3||
        !std::isfinite(at.x)||!std::isfinite(at.y)||!std::isfinite(at.z))
        throw std::invalid_argument("collection requires a finite point and reach no larger than 3 m");
    const auto found=debris_.find(id);
    if(found==debris_.end()||!world.contains(id))throw std::invalid_argument("native ground matter no longer exists");
    if(length(world.snapshot(id).center_of_mass_world_m-at)>distance)
        throw std::invalid_argument("native ground matter is outside collection reach");
    const Vec3 toward=world.snapshot(id).center_of_mass_world_m-at;
    if(length(toward)>1e-6) {
        const auto hit=world.castRayIgnoring(at,normalized(toward),length(toward),ignored_bodies);
        if(hit.hit && hit.body_id!=id && hit.distance_m+1e-4<length(toward))
            throw std::invalid_argument("native ground matter is occluded by terrain or another body");
    }
    auto packet=Json::parse(found->second);packet["pose"]=pose(world.snapshot(id));const auto &v=packet.at("volumes");
    Volumes moved{v.at("rock_m3").get<double>(),v.at("soil_m3").get<double>(),v.at("sand_m3").get<double>()};
    // Private Inventory is an explicit abstract store. Root host atomically
    // withdraws this credit with the durable private receipt/world checkpoint.
    carry(moved);world.removeAndDestroy(id);debris_.erase(found);debris_display_.erase(id);
    packet["schema"]="banjo.ground-matter-transfer.v1";packet["actor"]=selected_carrier_;
    return packet.dump();
}
std::string Environment::debrisStateJson() const {
    auto saved=Json::parse(debrisJson());saved["next_id"]=next_debris_id_;
    Json progress=Json::object();for(const auto &[key,text]:cut_progress_)progress[key]=Json::parse(text);
    saved["progress"]=std::move(progress);
    Json receipts=Json::object();for(const auto &[key,text]:cut_receipts_)receipts[key]=Json::parse(text);
    saved["receipts"]=std::move(receipts);return saved.dump();
}
void Environment::restoreDebrisState(const std::string &text) {
    const auto saved=Json::parse(text);const auto &bodies=saved.at("bodies");
    if(saved.value("schema","")!="banjo.ground-debris.v1"||!bodies.is_array()||bodies.size()>kMostDebris)
        throw std::invalid_argument("invalid saved native ground matter");
    const auto next=saved.at("next_id").get<MatterBodyId>();
    const double work=saved.at("source_work_j").get<double>();
    if(next<kFirstDebris||next>kLastDebris||!std::isfinite(work)||work<0)
        throw std::invalid_argument("invalid native ground matter ledger");
    std::map<MatterBodyId,std::string> restored,display;
    std::set<std::string> cell_ids;
    for(const auto &record:bodies) {
        const auto id=record.at("id").get<MatterBodyId>();
        if(id<kFirstDebris||id>=next||!restored.emplace(id,record.dump()).second||
            record.at("cells").empty()||record.at("cells").size()>2000||record.at("slabs").empty()||record.at("slabs").size()>128)
            throw std::invalid_argument("invalid ground component identity/cell count");
        const auto d=description(record);double mass=0,volume=0;
        if(!std::isfinite(d.mass_kg)||d.mass_kg<=0)throw std::invalid_argument("invalid ground component mass");
        for(const auto &cell:record.at("cells")) {
            const int kind=cell.at("run_kind").get<int>();
            if(kind<0||kind>=kRunKinds||kind==int(RunKind::Void)||!cell_ids.insert(cell.at("id").get<std::string>()).second)
                throw std::invalid_argument("invalid ground constituent identity/material");
            const auto size=vectorOf(cell.at("size_m"));const double v=size.x*size.y*size.z;
            const double m=v*density(static_cast<RunKind>(kind));
            if(size.x<=0||size.y<=0||size.z<=0||size.x>kCell+1e-9||size.y>kCell+1e-9||size.z>kCell+1e-9||
                std::abs(v-cell.at("volume_m3").get<double>())>1e-12||
                std::abs(m-cell.at("mass_kg").get<double>())>1e-9||
                cell.at("density_kg_m3").get<double>()!=density(static_cast<RunKind>(kind)))
                throw std::invalid_argument("invalid ground constituent volume/density/mass");
            (void)vectorOf(cell.at("source_center_m"));mass+=m;volume+=v;
        }
        double slabvolume=0,slabmass=0;
        for(const auto &s:record.at("slabs")) {
            const int kind=s.at("run_kind").get<int>();
            if(kind<0||kind>=kRunKinds||kind==int(RunKind::Void))throw std::invalid_argument("invalid ground slab material");
            const auto size=vectorOf(s.at("size_m"));const double v=size.x*size.y*size.z;
            if(size.x<=0||size.y<=0||size.z<=0||size.x>.5||size.y>2||size.z>.5)
                throw std::invalid_argument("invalid ground slab dimensions");
            slabvolume+=v;slabmass+=v*density(static_cast<RunKind>(kind));
        }
        if(std::abs(mass-d.mass_kg)>1e-8||std::abs(slabmass-mass)>1e-8||std::abs(slabvolume-volume)>1e-10)
            throw std::invalid_argument("ground constituent/component mass mismatch");
        auto drawing=record;drawing["cell_count"]=record.at("cells").size();drawing.erase("cells");
        display.emplace(id,drawing.dump());
    }
    std::map<std::string,std::string> progress;const auto &ps=saved.at("progress");
    if(!ps.is_object()||ps.size()>4096)throw std::invalid_argument("invalid saved cut progress");
    for(const auto &[key,p]:ps.items()) {
        const double paid=p.at("work_j").get<double>();
        if(key.size()>128||!std::isfinite(paid)||paid<0||p.at("signature").get<std::string>().size()>65536)
            throw std::invalid_argument("invalid saved cut work");
        progress.emplace(key,p.dump());
    }
    std::map<std::string,std::string> receipts;const auto &rs=saved.at("receipts");
    if(!rs.is_object()||rs.size()>4096)throw std::invalid_argument("invalid saved funded cut receipts");
    for(const auto &[key,r]:rs.items()) {
        const double requested=r.at("request").at("work_j").get<double>();
        const double consumed=r.at("answer").at("consumed_work_j").get<double>();
        if(key.empty()||key.size()>128||!std::isfinite(requested)||!std::isfinite(consumed)||requested<0||requested>1e6||consumed<0||consumed>requested)
            throw std::invalid_argument("invalid saved funded work receipt");
        (void)vectorOf(r.at("request").at("at_m"));receipts.emplace(key,r.dump());
    }
    debris_=std::move(restored);debris_display_=std::move(display);cut_progress_=std::move(progress);cut_receipts_=std::move(receipts);
    next_debris_id_=next;cut_source_work_j_=work;
}
void Environment::attachDebris(JoltWorld &world) {
    for(const auto &[id,text]:debris_) {
        if(world.contains(id))throw std::invalid_argument("saved native matter body id collides with world");
        world.addCompound(description(Json::parse(text)));
    }
    debris_world_=&world;
}
} // namespace banjo::terrain
