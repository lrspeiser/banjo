#include "physics/ContactNormalBlock.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace banjo {
namespace {
constexpr double eps=std::numeric_limits<double>::epsilon();

// Symmetric Jacobi diagonalization, bounded dimension and sweep count. Only
// roundoff-sized null eigenvalues are omitted; no diagonal stiffness is added.
std::array<double,16> principalInverse(const std::array<double,16> &k, unsigned mask) {
    std::array<unsigned,4> ids{}; unsigned n=0;
    for(unsigned i=0;i<4;++i)if(mask&(1u<<i))ids[n++]=i;
    std::array<double,16> a{},v{},out{}; double scale=0;
    for(unsigned i=0;i<n;++i){v[4*i+i]=1;for(unsigned j=0;j<n;++j){
        a[4*i+j]=k[4*ids[i]+ids[j]];scale=std::max(scale,std::abs(a[4*i+j]));}}
    // Most proper principal faces are SPD even when the whole patch is rank
    // deficient. Factor those directly; reserve the eigensolve for singular faces.
    std::array<double,16> lower{};bool positive=true;
    for(unsigned i=0;i<n&&positive;++i)for(unsigned j=0;j<=i;++j){
        double value=a[4*i+j];for(unsigned r=0;r<j;++r)value-=lower[4*i+r]*lower[4*j+r];
        if(i==j){if(value<=128*eps*scale){positive=false;break;}lower[4*i+j]=std::sqrt(value);}
        else lower[4*i+j]=value/lower[4*j+j];
    }
    if(positive){
        for(unsigned column=0;column<n;++column){std::array<double,4> y{},x{};
            for(unsigned i=0;i<n;++i){double value=i==column?1:0;for(unsigned j=0;j<i;++j)value-=lower[4*i+j]*y[j];y[i]=value/lower[4*i+i];}
            for(unsigned ii=n;ii>0;--ii){const unsigned i=ii-1;double value=y[i];for(unsigned j=i+1;j<n;++j)value-=lower[4*j+i]*x[j];x[i]=value/lower[4*i+i];}
            for(unsigned i=0;i<n;++i)out[4*ids[i]+ids[column]]=x[i];
        }
        return out;
    }
    for(unsigned sweep=0;sweep<32;++sweep){
        double largest=0;
        for(unsigned p=0;p<n;++p)for(unsigned r=p+1;r<n;++r){
            const double off=a[4*p+r];largest=std::max(largest,std::abs(off));
            if(std::abs(off)<=8*eps*scale)continue;
            const double tau=(a[4*r+r]-a[4*p+p])/(2*off);
            const double t=std::copysign(1.,tau)/(std::abs(tau)+std::hypot(1.,tau));
            const double c=1/std::hypot(1.,t),s=t*c;
            a[4*p+p]-=t*off;a[4*r+r]+=t*off;a[4*p+r]=a[4*r+p]=0;
            for(unsigned j=0;j<n;++j)if(j!=p&&j!=r){
                const double x=a[4*j+p],y=a[4*j+r];
                a[4*j+p]=a[4*p+j]=c*x-s*y;a[4*j+r]=a[4*r+j]=s*x+c*y;
            }
            for(unsigned j=0;j<n;++j){const double x=v[4*j+p],y=v[4*j+r];
                v[4*j+p]=c*x-s*y;v[4*j+r]=s*x+c*y;}
        }
        if(largest<=8*eps*scale)break;
        if(sweep==31)throw std::invalid_argument("normal patch eigensolve did not converge");
    }
    for(unsigned r=0;r<n;++r){
        const double eigen=a[4*r+r];
        if(eigen < -128*eps*scale)throw std::invalid_argument("normal patch matrix is not positive semidefinite");
        if(eigen<=128*eps*scale)continue;
        for(unsigned i=0;i<n;++i)for(unsigned j=0;j<n;++j)
            out[4*ids[i]+ids[j]]+=v[4*i+r]*v[4*j+r]/eigen;
    }
    return out;
}
}

ContactNormalBlock::ContactNormalBlock(const std::array<double,16> &k,unsigned points):points_(points),k_(k){
    if(points<1||points>4)throw std::invalid_argument("normal patch needs 1..4 points");
    double scale=0;
    for(unsigned i=0;i<points;++i)for(unsigned j=0;j<points;++j){
        if(!std::isfinite(k[4*i+j]))throw std::invalid_argument("nonfinite normal patch matrix");
        scale=std::max(scale,std::abs(k[4*i+j]));
    }
    for(unsigned i=0;i<points;++i){
        if(k[4*i+i]<=0)throw std::invalid_argument("normal patch needs positive effective inverse mass");
        for(unsigned j=0;j<points;++j)if(std::abs(k[4*i+j]-k[4*j+i])>32*eps*scale)
            throw std::invalid_argument("normal patch matrix is not symmetric");
    }
    for(unsigned mask=1;mask<(1u<<points);++mask)inverse_[mask]=principalInverse(k,mask);
}

std::array<double,4> ContactNormalBlock::solve(const std::array<double,4> &q) const {
    if(!points_)throw std::logic_error("normal patch was not prepared");
    double qscale=0;
    for(unsigned i=0;i<points_;++i){if(!std::isfinite(q[i]))throw std::invalid_argument("nonfinite normal patch velocity");qscale=std::max(qscale,std::abs(q[i]));}
    std::array<double,4> best{};double bestNorm=std::numeric_limits<double>::infinity();bool found=false;
    // Full support first. Its feasible minimum-norm solution is also the global
    // minimum-norm solution, so ordinary four-point resting patches take one solve.
    const unsigned full=(1u<<points_)-1;
    for(unsigned attempt=0;attempt<=full;++attempt){
        const unsigned mask=attempt==0?full:attempt-1;
        std::array<double,4> x{};double xscale=0;
        for(unsigned i=0;i<points_;++i){for(unsigned j=0;j<points_;++j)x[i]-=inverse_[mask][4*i+j]*q[j];xscale=std::max(xscale,std::abs(x[i]));}
        bool valid=true;double norm=0;
        for(unsigned i=0;i<points_;++i){
            if(!std::isfinite(x[i])||x[i]<-512*eps*xscale){valid=false;break;}
            if(x[i]<0)x[i]=0; // only a roundoff-sized negative admitted above
            norm+=x[i]*x[i];double g=q[i],scale=qscale;
            for(unsigned j=0;j<points_;++j){const double term=k_[4*i+j]*x[j];g+=term;scale+=std::abs(term);}
            const double tolerance=1024*eps*scale;
            if(!std::isfinite(g)||(mask&(1u<<i)?std::abs(g)>tolerance:g < -tolerance)){valid=false;break;}
        }
        if(valid&&norm<bestNorm){best=x;bestNorm=norm;found=true;if(mask==full)return best;}
    }
    if(!found)throw std::runtime_error("normal patch has no numerically qualified unilateral solution");
    return best;
}
}
