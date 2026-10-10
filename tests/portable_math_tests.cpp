// numeric/PortableMath.hpp against values computed to 240 bits (mpmath), and
// its special values. A result here is the same bits on every platform that
// passes: the table is the same table on Windows and on Linux. That is the
// point of it (docs/floating-point-model.md, profile banjo-cpu-precise-v2):
// the C libraries do not agree with each other on these functions, and the
// engine's physics no longer asks them.
#include "numeric/PortableMath.hpp"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
#include <string>

namespace {

namespace pm = banjo::pm;
int failures = 0;

void check(bool ok, const std::string &what) {
    if (!ok) {
        ++failures;
        std::printf("FAIL %s\n", what.c_str());
    }
}

std::string hex(double v) {
    char buffer[64];
    std::snprintf(buffer, sizeof buffer, "%a", v);
    return buffer;
}

bool same(double a, double b) {
    if (std::isnan(a) || std::isnan(b)) return std::isnan(a) && std::isnan(b);
    return a == b && std::signbit(a) == std::signbit(b);
}

struct Row {
    const char *name;
    double x, y, want;
};

const Row kRows[] = {
    // name, x, y (0 when unused), the correctly rounded result (mpmath, 240 bits)
    {"exp", -0x1.19de197a6d4b4p+4, 0x0.0p+0, 0x1.7fdc6d60229adp-26},
    {"exp", -0x1.175216d48484cp+5, 0x0.0p+0, 0x1.8bad991781a68p-51},
    {"exp", 0x1.e2fd853350878p+3, 0x0.0p+0, 0x1.b62354c1a9059p+21},
    {"exp", -0x1.560d0c69df60ep+5, 0x0.0p+0, 0x1.3e992f4a57153p-62},
    {"exp", 0x1.cb4a26d69baa0p+1, 0x0.0p+0, 0x1.2159f75bd78b3p+5},
    {"exp", -0x1.adcba3a6e2820p+3, 0x0.0p+0, 0x1.8a42c71681e30p-20},
    {"exp", -0x1.6199d1f907938p+5, 0x0.0p+0, 0x1.2cd02df2b3316p-64},
    {"exp", 0x1.7cb5a45e11800p-1, 0x0.0p+0, 0x1.0d3d77d58c28dp+1},
    {"exp", -0x1.7200e39f67c04p+5, 0x0.0p+0, 0x1.35b33945e4cddp-67},
    {"exp", -0x1.a8aae97176580p+2, 0x0.0p+0, 0x1.5832bc612fb1fp-10},
    {"exp", -0x1.581d9bf7ef070p+5, 0x0.0p+0, 0x1.ec40b02181d7ep-63},
    {"exp", -0x1.476df990e530cp+5, 0x0.0p+0, 0x1.ef5f4f6c1fb16p-60},
    {"exp", -0x1.a6b14a5a9f668p+6, 0x0.0p+0, 0x1.75bd7cea6074fp-153},
    {"exp", 0x1.c997cd2df4534p+8, 0x0.0p+0, 0x1.1f708ad77ca9ap+660},
    {"exp", -0x1.0756b04599207p+9, 0x0.0p+0, 0x1.1f15e71133b67p-760},
    {"exp", -0x1.837727b3a3f5ap+8, 0x0.0p+0, 0x1.00fb1d5826348p-559},
    {"exp", 0x1.64d022420c858p+7, 0x0.0p+0, 0x1.4e93667afbdc3p+257},
    {"exp", 0x1.39657146e9b5ap+9, 0x0.0p+0, 0x1.34c8fe2efe8e1p+904},
    {"exp", 0x1.afc6c981e1058p+6, 0x0.0p+0, 0x1.a8bf1aaca33dep+155},
    {"exp", -0x1.214b6f8ea4cc4p+7, 0x0.0p+0, 0x1.3f219e760d731p-209},
    {"exp", 0x1.4d60ea38583bap+9, 0x0.0p+0, 0x1.e6d0b66b4afe5p+961},
    {"exp", -0x1.3d646235cab4ep+9, 0x0.0p+0, 0x1.260ca3f8c0689p-916},
    {"exp", 0x1.f5db18814e3b4p+8, 0x0.0p+0, 0x1.047690e8c3be4p+724},
    {"exp", -0x1.268c0822a6922p+8, 0x0.0p+0, 0x1.0a984754b507fp-425},
    {"expm1", -0x1.8f37975c26e8cp+4, 0x0.0p+0, -0x1.ffffffffdfedcp-1},
    {"expm1", -0x1.9e094e04093a1p+4, 0x0.0p+0, -0x1.fffffffff34c4p-1},
    {"expm1", -0x1.33400bb2c8309p+4, 0x0.0p+0, -0x1.ffffffd8b8444p-1},
    {"expm1", -0x1.6f8200a428300p+0, 0x0.0p+0, -0x1.8627c27322d33p-1},
    {"expm1", -0x1.7acb10f0c93dep+4, 0x0.0p+0, -0x1.ffffffff8d0dfp-1},
    {"expm1", -0x1.349b99e008090p+3, 0x0.0p+0, -0x1.fff78136f4460p-1},
    {"expm1", -0x1.e8d575db6567cp+2, 0x0.0p+0, -0x1.ffc0da3c853a5p-1},
    {"expm1", -0x1.0f7516992e0b5p+4, 0x0.0p+0, -0x1.fffffe901d630p-1},
    {"expm1", -0x1.5a86b4f04df34p+3, 0x0.0p+0, -0x1.fffd6708b87b4p-1},
    {"expm1", -0x1.bcd692927e853p+4, 0x0.0p+0, -0x1.fffffffffe25bp-1},
    {"expm1", -0x1.be9f9386ab592p+4, 0x0.0p+0, -0x1.fffffffffe57cp-1},
    {"expm1", -0x1.6ca9c2494040ap+4, 0x0.0p+0, -0x1.fffffffeea024p-1},
    {"expm1", 0x1.8367ef1ffe3c4p-22, 0x0.0p+0, 0x1.8367f3b48513dp-22},
    {"expm1", -0x1.36fd1a134bea4p-23, 0x0.0p+0, -0x1.36fd189981f61p-23},
    {"expm1", -0x1.8f1dac71e5094p-22, 0x0.0p+0, -0x1.8f1da7956a0d6p-22},
    {"expm1", 0x1.6f7c4389c3148p-23, 0x0.0p+0, 0x1.6f7c4599489c7p-23},
    {"expm1", -0x1.9224a52436d58p-24, 0x0.0p+0, -0x1.9224a3e85b483p-24},
    {"expm1", -0x1.adff41f27ef78p-22, 0x0.0p+0, -0x1.adff3c4dfc011p-22},
    {"expm1", 0x1.3c166a6d292d0p-21, 0x0.0p+0, 0x1.3c16708646a3ep-21},
    {"expm1", 0x1.ab5658ccbf140p-22, 0x0.0p+0, 0x1.ab565e5f71732p-22},
    {"expm1", -0x1.12c6372bd16e3p-21, 0x0.0p+0, -0x1.12c632901ddd1p-21},
    {"expm1", 0x1.3fa5bc1c9d9d8p-23, 0x0.0p+0, 0x1.3fa5bdabbc14ep-23},
    {"expm1", 0x1.b0df654b485e0p-25, 0x0.0p+0, 0x1.b0df6602450c6p-25},
    {"expm1", 0x1.92cd02751bd92p-21, 0x0.0p+0, 0x1.92cd0c5c3e024p-21},
    {"log", 0x1.a936c6e3d061bp+45, 0x0.0p+0, 0x1.fb2f42aa8cb50p+4},
    {"log", 0x1.a965f1ff83ad5p-43, 0x0.0p+0, -0x1.d4c27ae49504ep+4},
    {"log", 0x1.a1b7531997f8cp+95, 0x0.0p+0, 0x1.095abbba78a28p+6},
    {"log", 0x1.d5597682186efp-77, 0x0.0p+0, -0x1.a62119ecda94cp+5},
    {"log", 0x1.9a5113973d4ddp-17, 0x0.0p+0, -0x1.69f9db8ea2188p+3},
    {"log", 0x1.30e7ef25584b5p+51, 0x0.0p+0, 0x1.1c33e1681e4bep+5},
    {"log", 0x1.8d917bab3b65bp-70, 0x0.0p+0, -0x1.80a41278cd84fp+5},
    {"log", 0x1.bdc678b56c209p-3, 0x0.0p+0, -0x1.86598e6292c00p+0},
    {"log", 0x1.1d633504542c6p-92, 0x0.0p+0, -0x1.fd49763d026abp+5},
    {"log", 0x1.712619f4a93afp+33, 0x0.0p+0, 0x1.73d68bcd681a8p+4},
    {"log", 0x1.a9882d3b99692p+52, 0x0.0p+0, 0x1.246a1e7bbea3ap+5},
    {"log", 0x1.7829cf36ecc72p+14, 0x0.0p+0, 0x1.42d8526bdf4a8p+3},
    {"log", 0x1.d02ef88747ed0p+0, 0x0.0p+0, 0x1.30b145078004fp-1},
    {"log", 0x1.f0f54560a6d8ep-1, 0x0.0p+0, -0x1.e88da6ea31b51p-6},
    {"log", 0x1.8afe50d0cefdfp+0, 0x0.0p+0, 0x1.bc19aae086f1dp-2},
    {"log", 0x1.643cefb7d723dp+0, 0x0.0p+0, 0x1.525a108dba28fp-2},
    {"log", 0x1.5eae04a640356p+0, 0x0.0p+0, 0x1.423faa9fb03d2p-2},
    {"log", 0x1.2f2ecf134cf58p+0, 0x0.0p+0, 0x1.5a6fd7aff534cp-3},
    {"log", 0x1.c28c31547e1b8p+0, 0x0.0p+0, 0x1.216d365aa6e33p-1},
    {"log", 0x1.eac1ee2cf5038p+0, 0x0.0p+0, 0x1.4d32161de998ap-1},
    {"log", 0x1.360dc3517540cp+0, 0x0.0p+0, 0x1.8854f0eefcc05p-3},
    {"log", 0x1.7f08d1831eb84p+0, 0x0.0p+0, 0x1.9c9e43a86cb87p-2},
    {"log", 0x1.2e98184630f8cp-1, 0x0.0p+0, -0x1.0d46fe0f14873p-1},
    {"log", 0x1.8d5f78bedc749p+0, 0x0.0p+0, 0x1.c2402297e9a40p-2},
    {"log1p", 0x1.89d64b7598cf1p+2, 0x0.0p+0, 0x1.f7b69f2991d48p+0},
    {"log1p", 0x1.3d978460e6e59p+3, 0x0.0p+0, 0x1.320d494ed433fp+1},
    {"log1p", 0x1.01e32a63d476cp+3, 0x0.0p+0, 0x1.1a14b1d39da5ap+1},
    {"log1p", 0x1.19de20b1c7a6bp+1, 0x0.0p+0, 0x1.29ef113abf142p+0},
    {"log1p", 0x1.a70e64777ff4bp+1, 0x0.0p+0, 0x1.75b5e234203b5p+0},
    {"log1p", 0x1.98da257e42448p+2, 0x0.0p+0, 0x1.fff96c5012660p+0},
    {"log1p", -0x1.4ee17cd6341d0p-1, 0x0.0p+0, -0x1.0fbe93e6ac646p+0},
    {"log1p", 0x1.087a879bcbe57p+2, 0x0.0p+0, 0x1.a2b5f0fb31fe5p+0},
    {"log1p", 0x1.dd0b5d56fa3b5p-1, 0x0.0p+0, 0x1.511bb7aa8c61ap-1},
    {"log1p", 0x1.81605d0a6684ep-2, 0x0.0p+0, 0x1.4718dfc0aabcap-2},
    {"log1p", -0x1.079308cf8e78ep-2, 0x0.0p+0, -0x1.30bc5789c0208p-2},
    {"log1p", 0x1.de51bfcaaa002p+2, 0x0.0p+0, 0x1.11884bbd2e2b1p+1},
    {"log1p", 0x1.00ac88808b789p-36, 0x0.0p+0, 0x1.00ac8880836dcp-36},
    {"log1p", 0x1.7430569fa3fbcp-33, 0x0.0p+0, 0x1.7430569f1cb4ap-33},
    {"log1p", 0x1.c5955ac64e97cp-29, 0x0.0p+0, 0x1.c5955ab9bff01p-29},
    {"log1p", 0x1.240ce11fc96c8p-14, 0x0.0p+0, 0x1.240a46ccf0122p-14},
    {"log1p", 0x1.75c6ad890be91p-38, 0x0.0p+0, 0x1.75c6ad8907a59p-38},
    {"log1p", 0x1.7b15ba5b553d0p-27, 0x0.0p+0, 0x1.7b15ba383fa79p-27},
    {"log1p", 0x1.7a5f3e6a6ff22p-24, 0x0.0p+0, 0x1.7a5f3d52d13f5p-24},
    {"log1p", 0x1.76358778e8637p-14, 0x0.0p+0, 0x1.76314188aa7d4p-14},
    {"log1p", 0x1.8c7ee37c34c84p-16, 0x0.0p+0, 0x1.8c7db0710a7a9p-16},
    {"log1p", 0x1.f4ab182ff5a68p-15, 0x0.0p+0, 0x1.f4a7450d260c7p-15},
    {"log1p", 0x1.605cbe2768cd9p-32, 0x0.0p+0, 0x1.605cbe26764e0p-32},
    {"log1p", 0x1.779eac715abb6p-28, 0x0.0p+0, 0x1.779eac6021a96p-28},
    {"pow", 0x1.c076cb1dee080p+11, 0x1.270f622485b9ap+3, 0x1.d8c5564ee6c77p+108},
    {"pow", 0x1.2b4a7f24ccbcap+13, -0x1.0c17be1808918p+3, 0x1.25d7cd985d3bfp-111},
    {"pow", 0x1.b88b6621f9594p+10, -0x1.9bb6d9419096ap+2, 0x1.8ca1a025fbe43p-70},
    {"pow", 0x1.23ab924172141p+11, -0x1.718e5206e1700p-2, 0x1.f2c62781eb8b8p-5},
    {"pow", 0x1.7033c46554ad5p+12, -0x1.6c6bd349de8aap+2, 0x1.9ba8f2d5bd608p-72},
    {"pow", 0x1.477f09750ec88p+5, -0x1.f1fe21656f240p+0, 0x1.7f4e641980c08p-11},
    {"pow", 0x1.cd9129dbcde81p+11, 0x1.9799b8f4b19a0p+0, 0x1.d342046f02626p+18},
    {"pow", 0x1.29d7d59c5e014p+13, 0x1.24992764f77e8p+2, 0x1.5980a71f787a4p+60},
    {"pow", 0x1.422ea31547c1cp+12, 0x1.693eb37b81d28p+1, 0x1.bea1541818d87p+34},
    {"pow", 0x1.a6a004b41312dp+12, -0x1.568890b429862p+3, 0x1.c04d53ae72ecbp-137},
    {"pow", 0x1.191aa440723f0p+13, 0x1.ae087bb6c31c8p+2, 0x1.31fc2770fa5ecp+88},
    {"pow", 0x1.11490e44a04e6p+13, 0x1.c9887a2b61530p+2, 0x1.86ce24f019f0ap+93},
    {"sin", -0x1.13828f409e230p+1, 0x0.0p+0, -0x1.abcfecaab672ep-1},
    {"sin", -0x1.029d3b81e1b06p+1, 0x0.0p+0, -0x1.cd1ca88404db2p-1},
    {"sin", -0x1.fb78f712f4d36p+2, 0x0.0p+0, -0x1.fe8ccff27e2f7p-1},
    {"sin", 0x1.57c8028024428p+1, 0x0.0p+0, 0x1.c2bf10f7a0240p-2},
    {"sin", -0x1.18295120c0512p+3, 0x0.0p+0, -0x1.3dd695b23d8b1p-1},
    {"sin", -0x1.14e5c4413a01fp+3, 0x0.0p+0, -0x1.650e84585624ep-1},
    {"sin", -0x1.74c87ab97fec8p+2, 0x0.0p+0, 0x1.c52ddfebbf94ep-2},
    {"sin", -0x1.b0407dce69564p+2, 0x0.0p+0, -0x1.d070e5befbb3cp-2},
    {"sin", -0x1.9976703fc46c4p+1, 0x0.0p+0, 0x1.d56ce195e1872p-5},
    {"sin", -0x1.1e5a0357cf442p+3, 0x0.0p+0, -0x1.d57d2ada7d2b8p-2},
    {"sin", -0x1.3fd9c772a8459p+3, 0x0.0p+0, 0x1.14880a2436c65p-1},
    {"sin", -0x1.be6181ca24195p+2, 0x0.0p+0, -0x1.46815c6698d0fp-1},
    {"sin", -0x1.375b205b74480p+16, 0x0.0p+0, 0x1.f4ec6e0d31876p-1},
    {"sin", -0x1.aa380ff7a2464p+14, 0x0.0p+0, -0x1.ae0dfd1753268p-2},
    {"sin", -0x1.72b3d29a4a1c6p+16, 0x0.0p+0, 0x1.f93f797daf481p-1},
    {"sin", 0x1.247279b8b6d12p+16, 0x0.0p+0, 0x1.7604043b8a0e0p-1},
    {"sin", 0x1.647730b2f6efcp+14, 0x0.0p+0, -0x1.bbd46e12dc1e2p-2},
    {"sin", -0x1.1291e726abc2bp+16, 0x0.0p+0, 0x1.749eb00e39800p-4},
    {"sin", -0x1.8318e5ba82997p+15, 0x0.0p+0, 0x1.5d3d7bb3778a3p-1},
    {"sin", -0x1.dce85cf7dc14cp+14, 0x0.0p+0, 0x1.ff4a776b2cb0fp-1},
    {"sin", -0x1.a87d3f95a8da8p+14, 0x0.0p+0, 0x1.d9a07ca8e2998p-1},
    {"sin", -0x1.26a78dc8f4298p+16, 0x0.0p+0, -0x1.e219b52f9e35cp-1},
    {"sin", 0x1.109b62a2d1b38p+16, 0x0.0p+0, 0x1.796faf1b99c78p-5},
    {"sin", 0x1.813c8b59ed932p+16, 0x0.0p+0, -0x1.4dfd60582ba58p-2},
    {"cos", -0x1.5c44979918230p-1, 0x0.0p+0, 0x1.8e0ca25b4b9aap-1},
    {"cos", -0x1.4b10f4e1a8780p-2, 0x0.0p+0, 0x1.e57928d4c1cc9p-1},
    {"cos", -0x1.0908a83478795p+3, 0x0.0p+0, -0x1.a950f09876c9cp-2},
    {"cos", -0x1.fd3329680d5b4p+2, 0x0.0p+0, -0x1.a226e3994ba10p-4},
    {"cos", -0x1.92da2d53166dcp+1, 0x0.0p+0, -0x1.fffde0b5a8af9p-1},
    {"cos", -0x1.2d1c76336ba55p+2, 0x0.0p+0, -0x1.ed45cddc8071ap-8},
    {"cos", 0x1.a4ef548ebaa50p+2, 0x0.0p+0, 0x1.ea0af7d51bc63p-1},
    {"cos", -0x1.b15bcbcd62f02p+2, 0x0.0p+0, 0x1.c439a977e322cp-1},
    {"cos", -0x1.3137ff3f95327p+3, 0x0.0p+0, -0x1.fcb7821c4d0f4p-1},
    {"cos", 0x1.20a179ec29638p+3, 0x0.0p+0, -0x1.d6912792de159p-1},
    {"cos", 0x1.215b10cf0b0b0p-1, 0x0.0p+0, 0x1.b0638953d4688p-1},
    {"cos", -0x1.c45947b196d50p+2, 0x0.0p+0, 0x1.6a44aa2c6067ap-1},
    {"cos", 0x1.0dd3e1a42d280p+13, 0x0.0p+0, 0x1.73261c51319d0p-3},
    {"cos", -0x1.717f80706e6d2p+16, 0x0.0p+0, -0x1.1d3d22ad78ad6p-2},
    {"cos", 0x1.5f5e360443e00p+12, 0x0.0p+0, 0x1.0a88b54de62e3p-7},
    {"cos", 0x1.75d43fa090ed4p+16, 0x0.0p+0, 0x1.fabadd52d3637p-2},
    {"cos", 0x1.1bd9018d03438p+16, 0x0.0p+0, 0x1.ffbcd08cf4269p-1},
    {"cos", 0x1.328eb6e080610p+15, 0x0.0p+0, 0x1.4c20b8426f350p-1},
    {"cos", -0x1.7541ebcdc0284p+15, 0x0.0p+0, 0x1.db608d7523f79p-1},
    {"cos", -0x1.a0902aa5b6254p+14, 0x0.0p+0, 0x1.c49f19e0a1327p-1},
    {"cos", -0x1.041f97d4f398ap+16, 0x0.0p+0, -0x1.77e245d9671b8p-1},
    {"cos", 0x1.a8e729d203a34p+15, 0x0.0p+0, 0x1.e46e08a411ea1p-1},
    {"cos", 0x1.9767ac06b2d90p+12, 0x0.0p+0, -0x1.e527b092b809dp-1},
    {"cos", 0x1.b405f4df7ed9cp+15, 0x0.0p+0, -0x1.aaec79e10926dp-1},
    {"tan", -0x1.05a27305cd9b6p-1, 0x0.0p+0, -0x1.1f114ed74b634p-1},
    {"tan", -0x1.a968720a429b5p-1, 0x0.0p+0, -0x1.18693de14094bp+0},
    {"tan", 0x1.de7b34d75f668p-1, 0x0.0p+0, 0x1.5a87ee725aed4p+0},
    {"tan", 0x1.746c5748cc882p+0, 0x0.0p+0, 0x1.129488eb26874p+3},
    {"tan", 0x1.0ed1a492bbe8ap+0, 0x0.0p+0, 0x1.c68ea9c0bc898p+0},
    {"tan", 0x1.d622ff2df6620p-1, 0x0.0p+0, 0x1.4ef7bf79b4ebap+0},
    {"tan", 0x1.e8f59b4cee700p-1, 0x0.0p+0, 0x1.69cb72ca1a1d5p+0},
    {"tan", 0x1.7071e8da3d150p-1, 0x0.0p+0, 0x1.c0b6bbe5a07abp-1},
    {"tan", -0x1.a3ba67999da1cp-1, 0x0.0p+0, -0x1.123d1342b6794p+0},
    {"tan", 0x1.b17d41e9d3680p-5, 0x0.0p+0, 0x1.b1e4f4018b4cfp-5},
    {"tan", -0x1.bbb63ce74b628p-2, 0x0.0p+0, -0x1.d9bd4e7169940p-2},
    {"tan", -0x1.69be4540ff80ap+0, 0x0.0p+0, -0x1.925e5bcfceba0p+2},
    {"atan", -0x1.2e1eca20ca766p+2, 0x0.0p+0, -0x1.5caf0ed671a96p+0},
    {"atan", -0x1.1a582214710c1p+1, 0x0.0p+0, -0x1.25295b6bf46b8p+0},
    {"atan", -0x1.3441bea1044dap+1, 0x0.0p+0, -0x1.2d5e7c6ee0cbap+0},
    {"atan", 0x1.ecdb2e01a4fd0p+0, 0x0.0p+0, 0x1.177bca9ab39f6p+0},
    {"atan", 0x1.242b6e1b8adf8p+2, 0x0.0p+0, 0x1.5aeb368a4af8bp+0},
    {"atan", -0x1.0e31bcfa84970p-1, 0x0.0p+0, -0x1.f13bbb6da3ae1p-2},
    {"atan", 0x1.17b18db9d9a90p+2, 0x0.0p+0, 0x1.588970e49023cp+0},
    {"atan", 0x1.385827cbf629ap+2, 0x0.0p+0, 0x1.5e6294c4d25b8p+0},
    {"atan", 0x1.23334dadf6112p+2, 0x0.0p+0, 0x1.5abda024436b6p+0},
    {"atan", -0x1.5a8839e63a512p+0, 0x0.0p+0, -0x1.de7b6a1ee57f8p-1},
    {"atan", -0x1.65cee7efa7a4bp+1, 0x0.0p+0, -0x1.3a2cf7585575fp+0},
    {"atan", -0x1.5da328d4c9864p+1, 0x0.0p+0, -0x1.3848885db5aa1p+0},
    {"atan", -0x1.282f758a89b44p+19, 0x0.0p+0, -0x1.921f999bb8fecp+0},
    {"atan", -0x1.20b2a8c01515bp+19, 0x0.0p+0, -0x1.921f98e415ff6p+0},
    {"atan", 0x1.e4a265be7c1f8p+17, 0x0.0p+0, 0x1.921f71a71ce76p+0},
    {"atan", 0x1.86ed159fe4b12p+19, 0x0.0p+0, 0x1.921fa04fafe8ap+0},
    {"atan", 0x1.4c74e1bef1a26p+19, 0x0.0p+0, 0x1.921f9ca03687ap+0},
    {"atan", -0x1.40ba4b8218670p+15, 0x0.0p+0, -0x1.921e1c9893d89p+0},
    {"atan", 0x1.2ac9057bd06e4p+18, 0x0.0p+0, 0x1.921f7e6e67d4ap+0},
    {"atan", 0x1.249eefab9de8cp+19, 0x0.0p+0, 0x1.921f994578b41p+0},
    {"atan", -0x1.957d60ddff399p+19, 0x0.0p+0, -0x1.921fa1105cb9bp+0},
    {"atan", 0x1.39a4d339e9fa0p+18, 0x0.0p+0, 0x1.921f81076fdb7p+0},
    {"atan", 0x1.902c48cda5bdep+19, 0x0.0p+0, 0x1.921fa0cba5bb6p+0},
    {"atan", 0x1.13afb8951027cp+19, 0x0.0p+0, 0x1.921f978d3dbb8p+0},
    {"atan2", 0x1.402e069fe41f4p+2, -0x1.c1e3af1c21c00p-2, 0x1.a88c54c4a0705p+0},
    {"atan2", -0x1.9b7e00da926dfp+2, 0x1.7217e5e5bc18ep+2, -0x1.ad37d19646445p-1},
    {"atan2", -0x1.acc187243d73cp+1, 0x1.810dddf762eecp+2, -0x1.0419bf9f05a85p-1},
    {"atan2", 0x1.2ddc5489bef86p+3, -0x1.0aa748abc9e3cp+1, 0x1.c9c424727ab5ap+0},
    {"atan2", -0x1.f8e6452441180p+0, 0x1.1df338b6cb256p+3, -0x1.bce26bc04204ep-3},
    {"atan2", 0x1.1fbe06d96abe6p+2, -0x1.a66533611a1e3p+2, 0x1.459433362b3f7p+1},
    {"atan2", -0x1.dd64115b97996p+2, -0x1.be86f04178541p+2, -0x1.29518fe3a98bfp+1},
    {"atan2", 0x1.031af7a53a728p+3, 0x1.885291c8eff38p+2, 0x1.d8773fd7fadddp-1},
    {"atan2", -0x1.c4e59a3e25f4ep+2, 0x1.a1eef41f56d84p+2, -0x1.a6ab5e7dc3396p-1},
    {"atan2", 0x1.33655365f2d46p+3, 0x1.929b592bfd568p+1, 0x1.411e0f2d12b0cp+0},
    {"atan2", -0x1.7ef4eece1ba7cp+1, 0x1.f24762bdce360p-1, -0x1.419d5f8724da5p+0},
    {"atan2", -0x1.d857361c9397bp+2, -0x1.36e26fe00d2b3p+3, -0x1.3ef78ff9eb514p+1},
    {"asin", 0x1.e23108dcf9b1ap-1, 0x0.0p+0, 0x1.3a56c8730898dp+0},
    {"asin", 0x1.3288a21a4f44cp-2, 0x0.0p+0, 0x1.374e915352ea3p-2},
    {"asin", 0x1.b380fdfef7e00p-5, 0x0.0p+0, 0x1.b3b5930290cfcp-5},
    {"asin", 0x1.bc082411d2f7cp-1, 0x0.0p+0, 0x1.0cb5f0927ffc8p+0},
    {"asin", -0x1.0f1dd606e2ff0p-3, 0x0.0p+0, -0x1.0fea2bf6c96bep-3},
    {"asin", 0x1.7caa2d98ef626p-1, 0x0.0p+0, 0x1.ad31717baca28p-1},
    {"asin", 0x1.4dfba46fdc2e0p-1, 0x0.0p+0, 0x1.6bd789e7803dfp-1},
    {"asin", -0x1.27e4847c6ab3ap-1, 0x0.0p+0, -0x1.3b7ae30cea876p-1},
    {"asin", -0x1.fc3e07c987438p-2, 0x0.0p+0, -0x1.09ea6bdee9f1ep-1},
    {"asin", -0x1.a801197fb3da4p-2, 0x0.0p+0, -0x1.b529ca6690105p-2},
    {"asin", -0x1.09b00a9e3fbdcp-1, 0x0.0p+0, -0x1.17575f1d77778p-1},
    {"asin", 0x1.620bf0a6e8120p-3, 0x0.0p+0, 0x1.63d5927e10ce5p-3},
    {"acos", -0x1.ecd22674a54c4p-2, 0x0.0p+0, 0x1.0954c779fcf34p+1},
    {"acos", -0x1.4bb97e54e4650p-3, 0x0.0p+0, 0x1.bbc5de2f2fd55p+0},
    {"acos", -0x1.79c7d2783447ep-1, 0x0.0p+0, 0x1.334978ce6c4f5p+1},
    {"acos", 0x1.a3db82deb5c40p-1, 0x0.0p+0, 0x1.37f989f6df51fp-1},
    {"acos", -0x1.2b73481a30124p-2, 0x0.0p+0, 0x1.de18c27072626p+0},
    {"acos", -0x1.56bec559a0330p-4, 0x0.0p+0, 0x1.a7920d1eea3afp+0},
    {"acos", 0x1.556585a14dd80p-3, 0x0.0p+0, 0x1.673fc749305b2p+0},
    {"acos", 0x1.9dfff94225380p-1, 0x0.0p+0, 0x1.42115854551b8p-1},
    {"acos", -0x1.451b4a5881260p-3, 0x0.0p+0, 0x1.baef50db3d72cp+0},
    {"acos", 0x1.abbf137067d5ap-1, 0x0.0p+0, 0x1.29e97c1ef7e1ap-1},
    {"acos", 0x1.b04290bcd9a00p-9, 0x0.0p+0, 0x1.914793e23781cp+0},
    {"acos", 0x1.04b5c89b7aff0p-4, 0x0.0p+0, 0x1.81d1865db4c0bp+0},
    {"hypot", 0x1.2ce26130e00e0p+2, -0x1.81093e38b82d4p+6, 0x1.817ebc35ed5b2p+6},
    {"hypot", -0x1.7f3357f2cb8a0p+3, -0x1.fb0702664a00cp+5, 0x1.01ffce30cc32bp+6},
    {"hypot", -0x1.8cdaa0b265671p+6, 0x1.deac376df5e30p+5, 0x1.cf70307e9122dp+6},
    {"hypot", -0x1.061f64b1d8173p+6, -0x1.534a5be170230p+2, 0x1.06fa9f91cfa7dp+6},
    {"hypot", 0x1.684f29e0113c0p+5, 0x1.6971a9f1677b8p+3, 0x1.73779805029a4p+5},
    {"hypot", -0x1.166db5ff88a28p+5, 0x1.d5ba1fa253060p+1, 0x1.17f8d87fc7f2ep+5},
    {"hypot", 0x1.62d3f7c1fd570p+3, 0x1.c6d601834c4b0p+5, 0x1.cf67d0a559338p+5},
    {"hypot", -0x1.3b1cca97ad5e4p+6, 0x1.81e52f6d75430p+3, 0x1.3ec87952039c6p+6},
    {"hypot", -0x1.9268b9e1bd205p+5, -0x1.64eec4978f6adp+5, 0x1.0cf2ea47c535dp+6},
    {"hypot", 0x1.b39e25638c8ecp+5, 0x1.8af4d54ded040p+0, 0x1.b3cae5fbb58bbp+5},
    {"hypot", 0x1.8b116d564ae80p+3, 0x1.9ffd30f2cd6b0p+5, 0x1.ab8da2dbef9e9p+5},
    {"hypot", 0x1.49fd8cc2563e0p+6, -0x1.6b35d4fb82540p+3, 0x1.4d1959a779550p+6},
    {"cbrt", 0x1.5599ca671bbb8p+0, 0x0.0p+0, 0x1.19d68881c73afp+0},
    {"cbrt", 0x1.d17833150ab2ep-4, 0x0.0p+0, 0x1.effea66e11e21p-2},
    {"cbrt", 0x1.0efc117140a28p-3, 0x0.0p+0, 0x1.04e685809b82fp-1},
    {"cbrt", 0x1.0eaeb12a98259p+3, 0x0.0p+0, 0x1.04cdae166a53ep+1},
    {"cbrt", 0x1.116e5ac8205f8p-5, 0x0.0p+0, 0x1.49b342f94db9fp-2},
    {"cbrt", 0x1.b8bdec65c2cf5p-3, 0x0.0p+0, 0x1.32d2b83229668p-1},
    {"cbrt", 0x1.ee079f4b662d4p-5, 0x0.0p+0, 0x1.919048c2b06ecp-2},
    {"cbrt", 0x1.45074429ec054p+11, 0x0.0p+0, 0x1.b808ebb92d288p+3},
    {"cbrt", 0x1.3a49e9d5706f8p+3, 0x0.0p+0, 0x1.121dff05bca78p+1},
    {"cbrt", 0x1.234a1c52e18d6p+9, 0x0.0p+0, 0x1.0b42b5d0c3e4bp+3},
    {"cbrt", 0x1.4a274b4c31f14p+11, 0x0.0p+0, 0x1.ba55eceef1cd0p+3},
    {"cbrt", 0x1.9d8b8a1ef46e8p-12, 0x0.0p+0, 0x1.2c60acc0ae12ap-4},
    {"cbrt", -0x1.b87c9bd87d57cp+8, 0x0.0p+0, -0x1.e6f514d7ea253p+2},
    {"cbrt", -0x1.c5df0bd091d70p+5, 0x0.0p+0, -0x1.ebd724fcefc72p+1},
    {"cbrt", -0x1.40008a7dd5640p+7, 0x0.0p+0, -0x1.5b723b74fcb70p+2},
    {"cbrt", -0x1.af6ecf4c53c41p+9, 0x0.0p+0, -0x1.30a5c6ef397fap+3},
    {"cbrt", -0x1.b73067c8b7541p+9, 0x0.0p+0, -0x1.32765de139384p+3},
    {"cbrt", -0x1.16f0f0f881b04p+9, 0x0.0p+0, -0x1.076deaece6303p+3},
    {"cbrt", -0x1.cfba1bc89d136p+9, 0x0.0p+0, -0x1.3811137e9a02ep+3},
    {"cbrt", -0x1.7bae450c5a614p+9, 0x0.0p+0, -0x1.23f1a7969ff7bp+3},
    {"cbrt", -0x1.cf708d1a969d6p+9, 0x0.0p+0, -0x1.380092907f6cfp+3},
    {"cbrt", -0x1.4a874d5c08020p+8, 0x0.0p+0, -0x1.ba80c93e305bfp+2},
    {"cbrt", -0x1.b021291bf0b84p+7, 0x0.0p+0, -0x1.8009d30a4d1f9p+2},
    {"cbrt", -0x1.9be5d9edf5668p+6, 0x0.0p+0, -0x1.2bfa7105415bcp+2},
    {"cbrt", 0x1.0a79658de3c3ep-12, 0x0.0p+0, 0x1.0371e0f61903dp-4},
    // Denormal results, the exact value rounded once to the 2^-1074 grid
    // (rounding to 53 bits first, then to the grid, misses some by one).
    {"exp", -0x1.627524676699dp+9, 0x0.0p+0, 0x0.98630a3db26efp-1022},
    {"pow", 0x1.486c959d021e7p-1, 0x1.9a6c869b2cbc7p+10, 0x0.000000051f3d7p-1022},
    {"hypot", -0x0.00086dd27e4bfp-1022, -0x0.0042d89f30d2fp-1022, 0x0.0043602189415p-1022},
    {"atan2", -0x0.00eead7860983p-1022, 0x1.1777ea1e9e964p+0, -0x0.00daa27648739p-1022},
    // y/x exactly halfway between two denormals; atan2 is just below it.
    {"atan2", 0x0.0000000000003p-1022, 0x1.0000000000000p+1, 0x0.0000000000001p-1022},
};

double evaluate(const Row &r) {
    const std::string n = r.name;
    if (n == "exp") return pm::exp(r.x);
    if (n == "expm1") return pm::expm1(r.x);
    if (n == "log") return pm::log(r.x);
    if (n == "log1p") return pm::log1p(r.x);
    if (n == "pow") return pm::pow(r.x, r.y);
    if (n == "sin") return pm::sin(r.x);
    if (n == "cos") return pm::cos(r.x);
    if (n == "tan") return pm::tan(r.x);
    if (n == "atan") return pm::atan(r.x);
    if (n == "atan2") return pm::atan2(r.x, r.y);
    if (n == "asin") return pm::asin(r.x);
    if (n == "acos") return pm::acos(r.x);
    if (n == "hypot") return pm::hypot(r.x, r.y);
    if (n == "cbrt") return pm::cbrt(r.x);
    return std::numeric_limits<double>::quiet_NaN();
}

void correctlyRounded() {
    unsigned rows = 0;
    for (const Row &r : kRows) {
        const double got = evaluate(r);
        check(same(got, r.want), std::string(r.name) + "(" + hex(r.x) + ", " + hex(r.y) + ") = " + hex(got) +
                                     ", correctly rounded " + hex(r.want));
        ++rows;
    }
    std::printf("  %u results, each the double nearest the true value\n", rows);
}

void specialValues() {
    const double inf = std::numeric_limits<double>::infinity(), nan = std::numeric_limits<double>::quiet_NaN();
    const double pi = 0x1.921fb54442d18p+1, half_pi = 0x1.921fb54442d18p+0;
    check(same(pm::exp(0.0), 1.0) && same(pm::exp(-inf), 0.0) && same(pm::exp(inf), inf) && std::isnan(pm::exp(nan)),
          "exp at 0, -inf, inf, nan");
    check(same(pm::exp(710.0), inf) && same(pm::exp(-746.0), 0.0), "exp overflows to inf and underflows to 0");
    check(same(pm::expm1(-0.0), -0.0) && same(pm::expm1(-inf), -1.0), "expm1 keeps -0 and tends to -1");
    check(same(pm::log(1.0), 0.0) && same(pm::log(0.0), -inf) && std::isnan(pm::log(-1.0)) && same(pm::log(inf), inf),
          "log at 1, 0, -1, inf");
    check(same(pm::log(0x1p-1074), -0x1.74385446d71c3p+9), "log of the smallest denormal");
    check(same(pm::log1p(-0.0), -0.0) && same(pm::log1p(-1.0), -inf), "log1p at -0 and -1");
    check(same(pm::pow(2.0, 10.0), 1024.0) && same(pm::pow(10.0, 2.0), 100.0) && same(pm::pow(-2.0, 3.0), -8.0),
          "pow is exact where the answer is a double");
    check(std::isnan(pm::pow(-8.0, 1.0 / 3.0)) && same(pm::pow(-0.0, 3.0), -0.0) && same(pm::pow(0.0, -1.0), inf),
          "pow of a negative base to a fraction, and of zeros");
    check(same(pm::pow(4.0, 0.5), 2.0) && same(pm::pow(nan, 0.0), 1.0) && same(pm::pow(1.0, nan), 1.0),
          "pow's square root and its 1 cases");
    check(same(pm::sin(-0.0), -0.0) && same(pm::cos(0.0), 1.0) && std::isnan(pm::sin(inf)), "sin and cos at 0 and inf");
    check(same(pm::sin(pi), 0x1.1a62633145c07p-53) && same(pm::cos(half_pi), 0x1.1a62633145c07p-54),
          "sin(pi) and cos(pi/2) are the distance from the double to pi");
    check(same(pm::atan2(0.0, -1.0), pi) && same(pm::atan2(-0.0, -1.0), -pi) && same(pm::atan2(-0.0, 0.0), -0.0),
          "atan2 keeps the sign of zero");
    check(same(pm::atan2(1.0, 0.0), half_pi) && same(pm::atan2(inf, inf), 0x1.921fb54442d18p-1),
          "atan2 on an axis and of infinities");
    check(same(pm::asin(1.0), half_pi) && same(pm::acos(-1.0), pi) && same(pm::acos(1.0), 0.0) && std::isnan(pm::asin(1.5)),
          "asin and acos at their ends");
    check(same(pm::acos(1e-310), half_pi), "acos of a denormal");
    check(same(pm::hypot(3.0, 4.0), 5.0) && same(pm::hypot(1e300, 1e300), 0x1.0e4d50f99b211p+997) &&
              same(pm::hypot(inf, nan), inf) && same(pm::hypot(1.0, 2.0, 2.0), 3.0),
          "hypot is exact where it can be, and neither overflows nor loses an infinity");
    check(same(pm::cbrt(-27.0), -3.0) && same(pm::cbrt(0x1p-1074), 0x1p-358) && same(pm::cbrt(-0.0), -0.0),
          "cbrt of a cube, of the smallest denormal and of -0");
    std::printf("  special values and the ends of each range\n");
}

} // namespace

int main() {
    correctlyRounded();
    specialValues();
    if (failures) {
        std::printf("%d portable math check(s) failed\n", failures);
        return 1;
    }
    std::printf("all portable math checks passed\n");
    return 0;
}
