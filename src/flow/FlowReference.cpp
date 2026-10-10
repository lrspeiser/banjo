#include "flow/FlowReference.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <limits>

namespace banjo::flow {
namespace {
bool finite(Cell c) { return std::isfinite(c.h)&&std::isfinite(c.qx)&&std::isfinite(c.qz); }
Cell flux(Cell l, Cell r, bool x, double g) {
    const double ul=l.h>0?(x?l.qx:l.qz)/l.h:0, ur=r.h>0?(x?r.qx:r.qz)/r.h:0;
    const double a=std::max(std::abs(ul)+std::sqrt(g*l.h),std::abs(ur)+std::sqrt(g*r.h));
    const Cell fl{x?l.qx:l.qz, l.qx*ul+(x?0.5*g*l.h*l.h:0), l.qz*ul+(x?0:0.5*g*l.h*l.h)};
    const Cell fr{x?r.qx:r.qz, r.qx*ur+(x?0.5*g*r.h*r.h:0), r.qz*ur+(x?0:0.5*g*r.h*r.h)};
    return {0.5*(fl.h+fr.h-a*(r.h-l.h)),0.5*(fl.qx+fr.qx-a*(r.qx-l.qx)),0.5*(fl.qz+fr.qz-a*(r.qz-l.qz))};
}
}
Reference::Reference(Settings s, std::vector<Cell> c):settings_(s),cells_(std::move(c)) {
    if(s.nx<2||s.nz<2||s.nx>128||s.nz>128||s.nx*s.nz>4096||cells_.size()!=static_cast<std::size_t>(s.nx*s.nz)
       ||!std::isfinite(s.dx)||s.dx<0.01||s.dx>1||!std::isfinite(s.density)||s.density<1||s.density>20000
       ||!std::isfinite(s.gravity)||s.gravity<0||s.gravity>20||!std::isfinite(s.cfl)||s.cfl<=0||s.cfl>0.2)
        throw std::invalid_argument("bounded flow settings refused");
    for(Cell a:cells_) if(!finite(a)||a.h<0||a.h>2||(a.h==0&&(a.qx!=0||a.qz!=0))
        ||(a.h>0&&std::hypot(a.qx,a.qz)/a.h>20)) throw std::invalid_argument("flow initial state refused");
    initial_=totals();
}
Account Reference::totals() const {
    Account a; const double area=settings_.dx*settings_.dx, rho=settings_.density;
    for(int j=0;j<settings_.nz;++j)for(int i=0;i<settings_.nx;++i){
        Cell c=cells_[static_cast<std::size_t>(j*settings_.nx+i)]; const double x=(i+0.5)*settings_.dx,z=(j+0.5)*settings_.dx;
        a.mass+=rho*area*c.h; a.px+=rho*area*c.qx; a.pz+=rho*area*c.qz;
        a.ly+=rho*area*(z*c.qx-x*c.qz);
        a.energy+=rho*area*(0.5*settings_.gravity*c.h*c.h+(c.h>0?0.5*(c.qx*c.qx+c.qz*c.qz)/c.h:0));
    }return a;
}
Account Reference::account() const {
    Account a=totals(); a.time=crossings_.time;a.steps=crossings_.steps;
    a.wall_px=crossings_.wall_px;a.wall_pz=crossings_.wall_pz;a.wall_ly=crossings_.wall_ly;
    a.numerical_ly=crossings_.numerical_ly;a.numerical_energy=crossings_.numerical_energy;
    a.mass_residual=a.mass-initial_.mass;a.px_residual=a.px-initial_.px-a.wall_px;a.pz_residual=a.pz-initial_.pz-a.wall_pz;
    a.ly_residual=a.ly-initial_.ly-a.wall_ly-a.numerical_ly;
    a.energy_residual=a.energy-initial_.energy-a.numerical_energy;return a;
}
void Reference::step(double dt) {
    const auto before=totals(); std::vector<Cell> next=cells_; const int nx=settings_.nx,nz=settings_.nz;
    const double scale=dt/settings_.dx,jscale=settings_.density*dt*settings_.dx;
    auto add=[&](int k,Cell f,double sign){auto& a=next[static_cast<std::size_t>(k)];a.h+=sign*scale*f.h;a.qx+=sign*scale*f.qx;a.qz+=sign*scale*f.qz;};
    for(int j=0;j<nz;++j)for(int i=0;i<=nx;++i){
        Cell l=i>0?cells_[static_cast<std::size_t>(j*nx+i-1)]:cells_[static_cast<std::size_t>(j*nx)];
        Cell r=i<nx?cells_[static_cast<std::size_t>(j*nx+i)]:cells_[static_cast<std::size_t>(j*nx+nx-1)];
        if(i==0)l.qx=-l.qx;
        if(i==nx)r.qx=-r.qx;
        Cell f=flux(l,r,true,settings_.gravity);
        if(i>0)add(j*nx+i-1,f,-1);
        if(i<nx)add(j*nx+i,f,1);
        if(i==0||i==nx){const double sign=i==0?1:-1,jx=sign*jscale*f.qx,jz=sign*jscale*f.qz;
            crossings_.wall_px+=jx;crossings_.wall_pz+=jz;crossings_.wall_ly+=(j+0.5)*settings_.dx*jx-i*settings_.dx*jz;
        }else crossings_.numerical_ly-=settings_.dx*jscale*f.qz;
    }
    for(int j=0;j<=nz;++j)for(int i=0;i<nx;++i){
        Cell l=j>0?cells_[static_cast<std::size_t>((j-1)*nx+i)]:cells_[static_cast<std::size_t>(i)];
        Cell r=j<nz?cells_[static_cast<std::size_t>(j*nx+i)]:cells_[static_cast<std::size_t>((nz-1)*nx+i)];
        if(j==0)l.qz=-l.qz;
        if(j==nz)r.qz=-r.qz;
        Cell f=flux(l,r,false,settings_.gravity);
        if(j>0)add((j-1)*nx+i,f,-1);
        if(j<nz)add(j*nx+i,f,1);
        if(j==0||j==nz){const double sign=j==0?1:-1,jx=sign*jscale*f.qx,jz=sign*jscale*f.qz;
            crossings_.wall_px+=jx;crossings_.wall_pz+=jz;crossings_.wall_ly+=j*settings_.dx*jx-(i+0.5)*settings_.dx*jz;
        }else crossings_.numerical_ly+=settings_.dx*jscale*f.qx;
    }
    for(Cell c:next)if(!finite(c)||c.h<0||(c.h==0&&(c.qx!=0||c.qz!=0))||(c.h>0&&std::hypot(c.qx,c.qz)/c.h>20))throw std::runtime_error("flow positivity/finite/speed gate refused");
    cells_=std::move(next); const auto after=totals();
    const double change=after.energy-before.energy;
    if(change>1e-10*std::max(1.0,before.energy))throw std::runtime_error("flow entropy energy creation gate refused");
    crossings_.numerical_energy+=change;crossings_.time+=dt;++crossings_.steps;
    const auto a=account(); const double tol=1e-9*std::max(1.0,initial_.mass);
    if(std::abs(a.mass_residual)>tol||std::abs(a.px_residual)>tol||std::abs(a.pz_residual)>tol||std::abs(a.ly_residual)>tol*settings_.dx*(nx+nz))
        throw std::runtime_error("flow mass/momentum account refused");
}
void Reference::advance(double seconds) {
    if(!std::isfinite(seconds)||seconds<=0||seconds>5)throw std::invalid_argument("flow interval refused");
    Reference trial=*this; double remaining=seconds; std::uint64_t count=0;
    while(remaining>0){double speed=0;for(Cell c:trial.cells_){const double u=c.h>0?std::hypot(c.qx,c.qz)/c.h:0;speed=std::max(speed,u+std::sqrt(settings_.gravity*c.h));}
        const double dt=std::min({remaining,0.02,speed>0?settings_.cfl*settings_.dx/speed:0.02});
        if(++count>20000||trial.crossings_.steps>=20000||trial.crossings_.steps>=8000000/static_cast<std::uint64_t>(settings_.nx*settings_.nz)||dt<1e-12)
            throw std::runtime_error("bounded flow work/CFL interval refused");
        trial.step(dt);remaining-=dt;
    }*this=std::move(trial);
}
}
