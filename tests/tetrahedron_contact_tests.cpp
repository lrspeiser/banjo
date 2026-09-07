#include "physics/TetrahedronContact.hpp"
#include <cmath>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <vector>
namespace { using namespace banjo; using Tet=std::array<Vec3,4>;
const Tet unit{{{0,0,0},{1,0,0},{0,1,0},{0,0,1}}};
void req(bool x,std::string_view m){if(!x)throw std::runtime_error(std::string(m));}
void near(double a,double b,double e,std::string_view m){req(std::isfinite(a)&&std::abs(a-b)<=e,m);}
Tet shift(Tet t,Vec3 d){for(auto&p:t)p+=d;return t;}
Vec3 reconstruct(const Tet&t,const std::array<double,4>&w){Vec3 p;for(unsigned i=0;i<4;++i)p+=w[i]*t[i];return p;}
void validate(const TetrahedronContactResult&r,const Tet&a,const Tet&b){
 req(r.resolved&&r.narrow_phase_calls==1,"query resolved in one bounded narrow phase call");
 near(length(reconstruct(a,r.barycentric_a)-r.point_a_world_m),0,3e-5,"A barycentric reconstruction");
 near(length(reconstruct(b,r.barycentric_b)-r.point_b_world_m),0,3e-5,"B barycentric reconstruction");
 for(double w:r.barycentric_a)req(w>=-2e-5,"A weights nonnegative within tolerance");
 for(double w:r.barycentric_b)req(w>=-2e-5,"B weights nonnegative within tolerance");
}
void separated_and_touching(){
 auto b=shift(unit,{2,0,0});auto r=tetrahedronContact(unit,b);validate(r,unit,b);req(!r.hit&&r.separation_distance_m>0,"separated tetrahedra miss");
 b=shift(unit,{1,0,0});r=tetrahedronContact(unit,b);req(r.resolved,"touching tetrahedra resolve");req(r.hit||r.separation_distance_m<2e-4,"touching lies within Jolt tolerance");
}
void face_and_edge_overlap(){
 for(Vec3 d: {Vec3{.8,.05,.05},Vec3{.5,.5,0.}}){auto b=shift(unit,d);auto r=tetrahedronContact(unit,b);validate(r,unit,b);req(r.hit&&r.penetration_depth_m>=0,"overlap hits");const Vec3 gap=r.point_b_world_m-r.point_a_world_m;near(length(cross(gap,r.normal_a_to_b)),0,2e-5,"witness gap parallel normal");}
}
void rigid_transform(){
 auto b=shift(unit,{.7,.05,.02});auto r=tetrahedronContact(unit,b);req(r.resolved&&r.hit,"base overlaps");
 const double h=.4;Quat q{std::cos(h),.2*std::sin(h),-.4*std::sin(h),std::sqrt(.8)*std::sin(h)};Tet a2=unit,b2=b;Vec3 s{3,-2,.4};for(auto&p:a2)p=q.rotate(p)+s;for(auto&p:b2)p=q.rotate(p)+s;auto m=tetrahedronContact(a2,b2);req(m.resolved&&m.hit,"moved overlaps");near(m.penetration_depth_m,r.penetration_depth_m,3e-5,"rigid penetration invariant");validate(m,a2,b2);
}
void invalid(){Tet d=unit;d[3]={1,1,0};req(!tetrahedronContact(d,unit).resolved,"degenerate rejected");d=unit;d[0].x=std::numeric_limits<double>::quiet_NaN();req(!tetrahedronContact(d,unit).resolved,"nonfinite rejected");}
}
int main(){const std::vector<std::pair<std::string_view,std::function<void()>>>ts{{"separated touching",separated_and_touching},{"face edge overlap",face_and_edge_overlap},{"rigid transform",rigid_transform},{"invalid",invalid}};unsigned f=0;for(auto&[n,t]:ts)try{t();std::cout<<"[PASS] "<<n<<'\n';}catch(const std::exception&e){++f;std::cerr<<"[FAIL] "<<n<<": "<<e.what()<<'\n';}return f?1:0;}
