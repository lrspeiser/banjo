// Bounded host ABI over the SAME private CPU/CUDA physical trial equations.
#include <cmath>
#include <algorithm>
#include <initializer_list>
#include <array>
#include <cstring>
#include <vector>
#include <new>
#include "physics/FiniteFrameKernel.hpp"
#include "physics/CohesiveInterfaceKernel.hpp"
#include "material/ConnectorModeKernel.hpp"
#include "physics/MaterialHistoryKernel.hpp"
#include "physics/NormalComplianceKernel.hpp"
#include "physics/CoupledGpuKernel.hpp"
#include "physics/CoupledFlightKernel.hpp"
#if defined(_WIN32)
#define BANJO_CPU_EXPORT extern "C" __declspec(dllexport)
#else
#define BANJO_CPU_EXPORT extern "C" __attribute__((visibility("default")))
#endif
namespace {
bool finite(const double* p,unsigned count){
    if(!p&&count)return false;
    for(unsigned i=0;i<count;++i)if(!std::isfinite(p[i]))return false;
    return true;
}
bool scene(const double* b,unsigned n,const double* e,unsigned m,double h,double gy){
    if(!n||n>banjo::dgMaxBodies||m>banjo::dgMaxEdges||!finite(b,30*n)||!finite(e,70*m)||
       !std::isfinite(h)||h<=0||h>1||!std::isfinite(gy))return false;
    for(unsigned i=0;i<n;++i){const double* r=b+30*i;
        if(r[0]<0||r[0]>2||r[0]!=std::floor(r[0])||r[1]<0||r[2]<0||r[3]<=0||
           (r[0]==0&&r[1]>0)||(r[1]>0&&r[2]<=0))return false;
        for(unsigned j=4;j<7;++j)if(r[j]<=0)return false;
        for(unsigned start:{10u,26u}){double norm=0;for(unsigned j=0;j<4;++j)norm+=r[start+j]*r[start+j];if(std::fabs(norm-1)>1e-10)return false;}
        for(unsigned j=0;j<3;++j)if(std::fabs(r[7+j]-(r[20+j]+r[23+j]))>1e-12)return false;
        if(r[1]>0&&r[0]==1&&(r[4]!=r[5]||r[4]!=r[6]))return false;
    }
    for(unsigned i=0;i<m;++i){const double* r=e+70*i;
        if(r[0]<0||r[1]<0||r[0]>=n||r[1]>=n||r[0]==r[1]||r[0]!=std::floor(r[0])||r[1]!=std::floor(r[1])||r[3]<=0||r[2]<0||r[2]>2||r[2]!=std::floor(r[2]))return false;
        for(unsigned start:{10u,14u}){double norm=0;for(unsigned j=0;j<4;++j)norm+=r[start+j]*r[start+j];if(std::fabs(norm-1)>1e-10)return false;}
        if(r[2]==1){for(unsigned j=23;j<35;++j)if(r[j]<=0)return false;}
        else if(r[18]<=0||r[19]<=0||r[20]<=0||r[21]<=0||r[22]<0||(r[2]==2&&r[23]<=0))return false;
    }
    return true;
}
// Private to one request. No accepted outcome or cross-timestep cache.
struct Row {
    banjo::FiniteFrameWrenches wrench{};
    std::array<double,12> ledger{};
    std::array<double,32> history{};
    int fault{};
    bool active{};
};
struct Pair { unsigned a{},b{};std::vector<Row> rows; };
Row material(const double* bodies,const double* edge,const banjo::DGTrialBody* p){
    Row row;const auto a=static_cast<unsigned>(edge[0]),b=static_cast<unsigned>(edge[1]);
    row.fault=banjo::dgMaterialTrial(bodies+30*a,bodies+30*b,edge,p[a],p[b],
        row.history.data(),row.wrench,row.ledger.data());row.active=true;return row;
}
void contact(Pair& pair,const double* bodies,const banjo::DGTrialBody* p,double h){
    pair.rows.clear();const auto a=pair.a,b=pair.b;const double* ba=bodies+30*a,*bb=bodies+30*b;
    const auto before=banjo::dgContact(ba,bb,p[a].initial,p[b].initial);
    const auto after=banjo::dgContact(ba,bb,p[a].ending,p[b].ending);
    if(before.gap>0&&after.gap>0)return;
    pair.rows.resize(banjo::dgContactSiteCount(ba,bb));
    for(unsigned site=0;site<pair.rows.size();++site){auto& row=pair.rows[site];
        row.fault=banjo::dgContactTrial(ba,bb,p[a],p[b],site,h,row.wrench,
            row.ledger.data(),row.active,true);
    }
}
int gather(const Row& row,unsigned a,unsigned b,double* forces,double* ledger){
    // Exactly the original row order; never subtract/re-add total forces.
    for(unsigned j=0;j<12;++j){if(j==8){if(row.ledger[j]>ledger[j])ledger[j]=row.ledger[j];}
        else ledger[j]+=row.ledger[j];}
    if(row.fault)return row.fault;
    if(row.active)banjo::dgAdd(forces,a,b,row.wrench);
    return 0;
}
int finish(const double* bodies,unsigned n,unsigned m,const double* v,double h,
    const double* poses,double* residual,const double* history,const double* forces,const double* ledger){
    for(unsigned i=0;i<n;++i){const double* b=bodies+30*i;
        for(unsigned j=0;j<6;++j){const double mass=j<3?b[1]:b[2],root=std::sqrt(mass);
            residual[6*i+j]=mass>0?(v[6*i+j]-b[14+j])*root-h*forces[6*i+j]/root:0;
            if(!banjo::dgFinite(residual[6*i+j])||!banjo::dgFinite(forces[6*i+j]))return 5;
        }
    }
    for(unsigned i=0;i<32*m;++i)if(!banjo::dgFinite(history[i]))return 6;
    for(unsigned i=0;i<7*n;++i)if(!banjo::dgFinite(poses[i]))return 7;
    for(unsigned i=0;i<12;++i)if(!banjo::dgFinite(ledger[i]))return 8;
    return 0;
}
}
BANJO_CPU_EXPORT unsigned banjo_coupled_cpu_abi(){return 1;}
BANJO_CPU_EXPORT int banjo_coupled_cpu_trials(const double* b,unsigned n,const double* e,unsigned m,
    const double* v,unsigned batch,double h,double gy,double* poses,double* residual,
    double* history,double* forces,double* ledger,int* faults){
    if(!batch||batch>384||!scene(b,n,e,m,h,gy)||!finite(v,6*n*batch)||!poses||!residual||
       (!history&&m)||!forces||!ledger||!faults)return -1;
    for(unsigned i=0;i<batch;++i)faults[i]=banjo::coupledTrialUnchecked(b,n,e,m,v+6*n*i,h,{0,gy,0},
        poses+7*n*i,residual+6*n*i,history?history+32*m*i:nullptr,forces+6*n*i,ledger+12*i);
    return 0;
}
BANJO_CPU_EXPORT int banjo_coupled_cpu_local_trials(const double* b,unsigned n,const double* e,unsigned m,
    const double* base,const double* v,const int* changed,unsigned batch,double h,double gy,
    double* poses,double* residual,double* history,double* forces,double* ledger,int* faults){
    if(!batch||batch>384||!scene(b,n,e,m,h,gy)||!finite(base,6*n)||!finite(v,6*n*batch)||
       !changed||!poses||!residual||(!history&&m)||!forces||!ledger||!faults)return -1;
    // Validate the whole request before touching caller output. Bitwise checks
    // preserve signed zeros and forbid undeclared second-body perturbations.
    for(unsigned k=0;k<batch;++k){if(changed[k]<0||static_cast<unsigned>(changed[k])>=n)return -1;
        for(unsigned i=0;i<n;++i)if(i!=static_cast<unsigned>(changed[k])&&
            std::memcmp(v+6*(k*n+i),base+6*i,6*sizeof(double)))return -1;
    }
    try {
        std::array<banjo::DGTrialBody,banjo::dgMaxBodies> prepared{};
        for(unsigned i=0;i<n;++i)prepared[i]=banjo::dgPrepareTrial(b+30*i,base+6*i,h);
        std::vector<Row> edges;edges.reserve(m);
        for(unsigned i=0;i<m;++i)edges.push_back(material(b,e+70*i,prepared.data()));
        std::vector<Pair> pairs;pairs.reserve(n*(n-1)/2);
        for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c){
            if(b[30*a+1]==0&&b[30*c+1]==0)continue;
            pairs.push_back({a,c,{}});contact(pairs.back(),b,prepared.data(),h);
        }
        Pair scratch;scratch.rows.reserve(48);
        for(unsigned k=0;k<batch;++k){auto p=prepared;const unsigned body=changed[k];
            const double* velocity=v+6*n*k;double* f=forces+6*n*k,*l=ledger+12*k;
            double* s=history?history+32*m*k:nullptr,*r=residual+6*n*k,*pose=poses+7*n*k;
            p[body]=banjo::dgPrepareTrial(b+30*body,velocity+6*body,h);
            for(unsigned j=0;j<12;++j)l[j]=0;
            for(unsigned i=0;i<n;++i){banjo::dgWrite3(pose+7*i,p[i].ending.p);banjo::dgWrite4(pose+7*i+3,p[i].ending.q);
                banjo::dgWrite3(f+6*i,banjo::frameScale({0,gy,0},b[30*i+1]));banjo::dgWrite3(f+6*i+3,{});
            }
            int fault=0;
            for(unsigned i=0;i<m;++i){const double* edge=e+70*i;const unsigned a=static_cast<unsigned>(edge[0]),c=static_cast<unsigned>(edge[1]);
                const Row row=a==body||c==body?material(b,edge,p.data()):edges[i];
                // Rotation-branch refusal occurs before the shared law writes
                // history. Keep caller bytes untouched just like full trials.
                if(row.fault!=1)std::memcpy(s+32*i,row.history.data(),32*sizeof(double));
                fault=gather(row,a,c,f,l);if(fault)break;
            }
            if(!fault)for(const auto& pair:pairs){const Pair* selected=&pair;
                if(pair.a==body||pair.b==body){scratch.a=pair.a;scratch.b=pair.b;contact(scratch,b,p.data(),h);selected=&scratch;}
                for(const auto& row:selected->rows){fault=gather(row,pair.a,pair.b,f,l);if(fault)break;}
                if(fault)break;
            }
            faults[k]=fault?fault:finish(b,n,m,velocity,h,pose,r,s,f,l);
        }
    } catch(const std::bad_alloc&) {return -2;}
    return 0;
}
BANJO_CPU_EXPORT int banjo_coupled_cpu_schedule(const double* b,unsigned n,double h,double gy,
    double phase,double tolerance,double* out){
    if(!scene(b,n,nullptr,0,h,gy)||!std::isfinite(phase)||phase<=0||phase>1||!std::isfinite(tolerance)||tolerance<0||!out)return -1;
    unsigned k=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c){
        if(b[30*a+1]==0&&b[30*c+1]==0)continue;
        double va[6],vc[6];for(unsigned j=0;j<6;++j){va[j]=b[30*a+14+j];vc[j]=b[30*c+14+j];}
        if(b[30*a+1]>0)va[1]+=h*gy;
        if(b[30*c+1]>0)vc[1]+=h*gy;
        const auto pa=banjo::dgPrepareTrial(b+30*a,va,h),pc=banjo::dgPrepareTrial(b+30*c,vc,h);
        const auto r=banjo::dgContactSchedule(b+30*a,b+30*c,pa.initial,pc.initial,pa.ending,pc.ending,h,phase,tolerance);
        out[3*k]=r.step_s;out[3*k+1]=r.frequency_rad_s;out[3*k+2]=r.excitation_m_s;++k;
    }
    return static_cast<int>(k);
}
// Current primitive geometry only. A bounding sphere may overlap a box even
// when their actual surfaces are separated; that flight bound is intentionally
// conservative and must not be mistaken for present contact.
BANJO_CPU_EXPORT int banjo_coupled_cpu_separation(const double* b,unsigned n,unsigned sphere,double* gaps){
    if(!scene(b,n,nullptr,0,1e-12,0)||sphere>=n||b[30*sphere]!=2||!gaps)return -1;
    for(unsigned i=0;i<n;++i)gaps[i]=i==sphere?1e300:
        banjo::dgContact(b+30*sphere,b+30*i,banjo::dgPose(b+30*sphere),banjo::dgPose(b+30*i)).gap;
    return static_cast<int>(n);
}
// All current native contact sites, including sites behind a separated broad
// pair. Read-only geometry for continuous-branch diagnostics, not a CCD gate.
// Rows (10 doubles): a,b,site,sample owner (-1 primitive),gap,broad gap,
// current sample/center relative to target center (xyz),sample lever length.
BANJO_CPU_EXPORT int banjo_coupled_cpu_contact_geometry(const double* b,unsigned n,
    unsigned capacity,double* out){
    if(!scene(b,n,nullptr,0,1e-12,0)||!out)return -1;
    unsigned count=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c)
        if(b[30*a+1]>0||b[30*c+1]>0)count+=banjo::dgContactSiteCount(b+30*a,b+30*c);
    if(capacity<count)return -1; // refusal leaves the caller output untouched
    unsigned k=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c){
        const auto ba=b+30*a,bc=b+30*c;if(ba[1]==0&&bc[1]==0)continue;
        const auto pa=banjo::dgPose(ba),pc=banjo::dgPose(bc);
        const auto broad=banjo::dgContact(ba,bc,pa,pc);
        const unsigned sites=banjo::dgContactSiteCount(ba,bc);
        const bool sa=static_cast<int>(ba[0])==1&&static_cast<int>(bc[0])!=2;
        const bool sb=static_cast<int>(bc[0])==1&&static_cast<int>(ba[0])!=2;
        for(unsigned site=0;site<sites;++site){
            auto point=pa,target=pc;banjo::FrameVector lever{};
            double owner=-1,gap=broad.gap;
            if(sites>1){
                const bool swap=sb&&(!sa||site>=24);const auto source=swap?bc:ba;
                point=swap?pc:pa;target=swap?pa:pc;owner=swap?c:a;
                lever=banjo::dgSurfaceLever(source,point,site%24);
                gap=banjo::dgSurfaceContact(source,swap?ba:bc,point,target,site%24).gap;
                point=banjo::dgAddPosition(point,lever);
            }
            auto row=out+10*k++;row[0]=a;row[1]=c;row[2]=site;row[3]=owner;
            row[4]=gap;row[5]=broad.gap;
            banjo::dgWrite3(row+6,banjo::dgPositionValue(banjo::dgRelative(point,target)));
            row[9]=banjo::dgLength(lever);
        }
    }
    return static_cast<int>(k);
}
// Read-only native differential, canonical pair order. Rows (34 doubles):
// a,b,site,sample owner (-1 primitive),gap,broad gap; sample lever xyz;
// point relative to target xyz; target-local xyz; target shape; extents xyz;
// d(gap)/d(a translation, a world turn, b translation, b world turn) (12);
// compensated abs(local coordinate)-target half extent (3).
// Geometry/gradients come from the existing contact law; no response is applied.
BANJO_CPU_EXPORT int banjo_coupled_cpu_contact_differential(const double* b,unsigned n,
    unsigned capacity,double* out){
    if(!scene(b,n,nullptr,0,1e-12,0)||!out)return -1;
    unsigned count=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c)
        if(b[30*a+1]>0||b[30*c+1]>0)count+=banjo::dgContactSiteCount(b+30*a,b+30*c);
    if(capacity<count)return -1;
    try{
        std::vector<double> rows(34*count);unsigned k=0;
        for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c){
            const auto ba=b+30*a,bc=b+30*c;if(ba[1]==0&&bc[1]==0)continue;
            const auto pa=banjo::dgPose(ba),pc=banjo::dgPose(bc);
            const auto broad=banjo::dgContact(ba,bc,pa,pc);
            const unsigned sites=banjo::dgContactSiteCount(ba,bc);
            const bool sa=static_cast<int>(ba[0])==1&&static_cast<int>(bc[0])!=2;
            const bool sb=static_cast<int>(bc[0])==1&&static_cast<int>(ba[0])!=2;
            for(unsigned site=0;site<sites;++site){
                auto point=pa,target=pc;const double* target_body=bc;
                banjo::FrameVector lever{};auto contact=broad;double owner=-1;bool swap=false;
                if(sites>1){
                    swap=sb&&(!sa||site>=24);const auto source=swap?bc:ba;
                    point=swap?pc:pa;target=swap?pa:pc;target_body=swap?ba:bc;owner=swap?c:a;
                    lever=banjo::dgSurfaceLever(source,point,site%24);
                    contact=banjo::dgSurfaceContact(source,target_body,point,target,site%24);
                    point=banjo::dgAddPosition(point,lever);
                }
                auto row=rows.data()+34*k++;row[0]=a;row[1]=c;row[2]=site;row[3]=owner;
                row[4]=contact.gap;row[5]=broad.gap;banjo::dgWrite3(row+6,lever);
                const auto relative=banjo::dgRelative(point,target);
                banjo::dgWrite3(row+9,banjo::dgPositionValue(relative));
                for(unsigned axis=0;axis<3;++axis){
                    const auto coordinate=banjo::dgDotAcc(relative,banjo::frameRotate(target.q,banjo::dgAxis(axis)));
                    row[12+axis]=banjo::dgValue(coordinate);row[16+axis]=target_body[4+axis];
                    row[31+axis]=banjo::dgValue(banjo::dgAccSub(banjo::dgAccScale(coordinate,row[12+axis]<0?-1:1),{target_body[4+axis],0}));
                }
                row[15]=target_body[0];const auto g=contact.gradient;
                const banjo::FrameVector values[]{swap?g.force_b:g.force_a,swap?g.torque_b:g.torque_a,
                    swap?g.force_a:g.force_b,swap?g.torque_a:g.torque_b};
                for(unsigned j=0;j<4;++j)banjo::dgWrite3(row+19+3*j,values[j]);
            }
        }
        if(!finite(rows.data(),static_cast<unsigned>(rows.size())))return -1;
        std::memcpy(out,rows.data(),rows.size()*sizeof(double));return static_cast<int>(k);
    }catch(const std::bad_alloc&){return -1;}
}
BANJO_CPU_EXPORT int banjo_coupled_cpu_flight(const double* b,unsigned n,unsigned sphere,double h,double gy,
    double travel,double* bounds,double* poses,double* v,double* f,double* r){
    if(!scene(b,n,nullptr,0,h,gy)||sphere>=n||b[30*sphere]!=2||b[30*sphere+1]<=0||
       !std::isfinite(travel)||travel<0||!bounds||!poses||!v||!f||!r)return -1;
    for(unsigned i=0;i<n;++i)banjo::dgIsolatedSphereBound(b,n,sphere,i,h,gy,travel,bounds);
    banjo::dgIsolatedSphereStep(b,sphere,h,gy,poses,v,f,r);
    return 0;
}
// Read-only replay of ONE accepted native trial's actual contact contributions.
// Rows (24 doubles): a,b,site, surface A xyz, surface B xyz, wrench (12),
// contact U0,U1,maximum compression. total includes material interfaces too,
// excluding gravity, so callers can audit reconstruction against the solve.
BANJO_CPU_EXPORT int banjo_coupled_cpu_contact_receipt(const double* b,unsigned n,
    const double* e,unsigned m,const double* v,double h,unsigned capacity,double* out,double* total){
    if(!scene(b,n,e,m,h,0)||!finite(v,6*n)||!out||!total)return -1;
    unsigned possible=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c)
        if(b[30*a+1]>0||b[30*c+1]>0)possible+=banjo::dgContactSiteCount(b+30*a,b+30*c);
    if(capacity<possible)return -1;
    std::array<banjo::DGTrialBody,banjo::dgMaxBodies> p;
    for(unsigned i=0;i<n;++i)p[i]=banjo::dgPrepareTrial(b+30*i,v+6*i,h);
    std::fill(total,total+6*n,0.);
    for(unsigned i=0;i<m;++i){const auto row=material(b,e+70*i,p.data());
        if(row.fault)return -2;
        banjo::dgAdd(total,static_cast<unsigned>(e[70*i]),static_cast<unsigned>(e[70*i+1]),row.wrench);}
    unsigned k=0;
    for(unsigned a=0;a<n;++a)for(unsigned c=a+1;c<n;++c){
        const auto ba=b+30*a,bc=b+30*c;if(ba[1]==0&&bc[1]==0)continue;
        const auto before=banjo::dgContact(ba,bc,p[a].initial,p[c].initial);
        const auto after=banjo::dgContact(ba,bc,p[a].ending,p[c].ending);
        if(before.gap>0&&after.gap>0)continue;
        const unsigned sites=banjo::dgContactSiteCount(ba,bc);
        const bool sa=static_cast<int>(ba[0])==1&&static_cast<int>(bc[0])!=2;
        const bool sb=static_cast<int>(bc[0])==1&&static_cast<int>(ba[0])!=2;
        for(unsigned site=0;site<sites;++site){
            banjo::FiniteFrameWrenches w{};double ledger[12]{};bool active=false;
            if(banjo::dgContactTrial(ba,bc,p[a],p[c],site,h,w,ledger,active,true))return -2;
            if(!active)continue;
            banjo::dgAdd(total,a,c,w);
            auto xa=p[a].midpoint.p,xb=p[c].midpoint.p;
            if(sites>1){const bool swap=sb&&(!sa||site>=24);
                const auto source=swap?bc:ba,target=swap?ba:bc;
                const auto ps=swap?p[c].midpoint:p[a].midpoint,pt=swap?p[a].midpoint:p[c].midpoint;
                const auto lever=banjo::dgSurfaceLever(source,ps,site%24);
                const auto g=banjo::dgSurfaceContact(source,target,ps,pt,site%24);
                const auto sample=banjo::dgAddPosition(ps,lever).p;
                const auto surface=banjo::dgSub(sample,banjo::frameScale(g.gradient.force_a,g.gap));
                xa=swap?surface:sample;xb=swap?sample:surface;
            }else {const auto g=banjo::dgContact(ba,bc,p[a].midpoint,p[c].midpoint);
                if(static_cast<int>(ba[0])==2){xa=banjo::dgSub(xa,banjo::frameScale(g.gradient.force_a,ba[4]));
                    xb=banjo::dgSub(xa,banjo::frameScale(g.gradient.force_a,g.gap));}
                else if(static_cast<int>(bc[0])==2){xb=banjo::dgSub(xb,banjo::frameScale(g.gradient.force_b,bc[4]));
                    xa=banjo::dgSub(xb,banjo::frameScale(g.gradient.force_b,g.gap));}
            }
            auto row=out+24*k++;row[0]=a;row[1]=c;row[2]=site;
            banjo::dgWrite3(row+3,xa);banjo::dgWrite3(row+6,xb);
            const banjo::FrameVector values[]{w.force_a,w.torque_a,w.force_b,w.torque_b};
            for(unsigned j=0;j<4;++j)banjo::dgWrite3(row+9+3*j,values[j]);
            row[21]=ledger[4];row[22]=ledger[5];row[23]=ledger[8];
        }
    }
    return static_cast<int>(k);
}
