#pragma once
#include "core/Math.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo {
inline Mat3 inverseContactTensor(const Mat3 &tensor) {
    const auto require=[](bool value,const char *why){if(!value)throw std::invalid_argument(why);};
    double scale=0;
    for(const auto &row:tensor.m)for(double entry:row) {
        require(std::isfinite(entry),"contact tensor is nonfinite");scale=std::max(scale,std::abs(entry));
    }
    require(scale>0,"contact tensor is zero");
    Mat3 normalized=tensor;
    for(auto &row:normalized.m)for(double &entry:row)entry/=scale;
    for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)
        require(std::abs(normalized.m[i][j]-normalized.m[j][i])<=1e-12,"contact tensor is asymmetric");
    require(normalized.m[0][0]>0&&normalized.m[0][0]*normalized.m[1][1]-normalized.m[0][1]*normalized.m[1][0]>0&&
        normalized.determinant()>1e-14,"contact tensor is not well-conditioned positive definite");
    auto inverse=normalized.inverse(0).value();
    for(auto &row:inverse.m)for(double &entry:row) {
        entry/=scale;require(std::isfinite(entry),"contact inverse tensor overflow");
    }
    return inverse;
}
} // namespace banjo
