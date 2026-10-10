#include "optics/RayOptics.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace banjo::optics {

Vec3 reflect(const Vec3 &along, const Vec3 &normal) { return along - 2.0 * dot(along, normal) * normal; }

double fresnelReflectance(double cos_incidence, double n_from, double n_to) {
    const double cos_i = std::clamp(cos_incidence, 0.0, 1.0);
    const double sin_t = n_from / n_to * std::sqrt(std::max(0.0, 1.0 - cos_i * cos_i));
    if (sin_t >= 1.0) return 1.0;
    const double cos_t = std::sqrt(std::max(0.0, 1.0 - sin_t * sin_t));
    // The amplitude ratios for light polarised across (s) and in (p) the plane
    // of incidence; unpolarised light reflects the mean of their squares.
    const double rs = (n_from * cos_i - n_to * cos_t) / (n_from * cos_i + n_to * cos_t);
    const double rp = (n_to * cos_i - n_from * cos_t) / (n_to * cos_i + n_from * cos_t);
    return 0.5 * (rs * rs + rp * rp);
}

Refraction refract(const Vec3 &along, const Vec3 &toward, double n_from, double n_to) {
    Refraction out;
    out.cos_incidence = std::clamp(-dot(along, toward), 0.0, 1.0);
    const double eta = n_from / n_to;
    const double sin2_t = eta * eta * (1.0 - out.cos_incidence * out.cos_incidence);
    if (sin2_t >= 1.0) {
        out.total = true;
        out.reflectance = 1.0;
        return out;
    }
    const double cos_t = std::sqrt(1.0 - sin2_t);
    // Snell's law as vectors: the part along the surface scales by n_from/n_to,
    // and the part through it is whatever keeps the ray a unit vector.
    out.along = normalized(eta * along + (eta * out.cos_incidence - cos_t) * toward);
    out.reflectance = fresnelReflectance(out.cos_incidence, n_from, n_to);
    return out;
}

namespace {

// A ray on its way: where it is, which way it goes, what it carries, what it is
// inside (-1 for the air), what it started with (for the share that is worth
// following), how many surfaces it has met, and where its drawn path goes.
struct Going {
    Vec3 from{}, along{};
    double skipped_m{};      // how far along its line it starts past the surface it left
    Power power_w{};
    int inside{-1};
    int ignore{-1};
    double started_w{};
    unsigned met{};
    int path{-1};
};

class Tracer {
public:
    Tracer(Scene &scene, std::size_t bodies, const Settings &settings) : scene_(scene), settings_(settings) {
        result_.absorbed_w.assign(bodies, 0.0);
    }

    void run(const std::vector<Ray> &rays) {
        for (const Ray &ray : rays) {
            const double sent = total(ray.power_w);
            if (!(sent > 0.0) || !std::isfinite(sent) || ray.power_w[0] < 0.0 || ray.power_w[1] < 0.0) continue;
            ++result_.rays;
            result_.ledger.sent_w += sent;
            if (ray.from_sky) {
                ++result_.casts;
                const Meeting behind = scene_.toSurface(ray.from, -1.0 * ray.along, settings_.reach_m, -1);
                if (behind.hit) {
                    absorbAt(behind.body, sent);
                    continue;
                }
            }
            Going g{ray.from, ray.along, 0.0, ray.power_w, -1, ray.ignore, sent, 0, -1};
            if (ray.drawn) {
                result_.paths.push_back({ray.light, {ray.from}, {}});
                g.path = static_cast<int>(result_.paths.size()) - 1;
            }
            follow(g);
            while (!waiting_.empty()) {
                Going next = waiting_.back();
                waiting_.pop_back();
                follow(next);
            }
        }
    }

    Result take() { return std::move(result_); }

private:
    void absorbAt(int body, double power_w) {
        if (!(power_w > 0.0)) return;
        if (body >= 0 && static_cast<std::size_t>(body) < result_.absorbed_w.size()) {
            result_.absorbed_w[static_cast<std::size_t>(body)] += power_w;
            result_.ledger.absorbed_w += power_w;
        } else {
            result_.ledger.ground_w += power_w;
        }
    }

    void leg(Going &g, const Vec3 &to) {
        ++result_.legs;
        if (g.path < 0) return;
        Path &p = result_.paths[static_cast<std::size_t>(g.path)];
        p.points.push_back(to);
        p.power_w.push_back(total(g.power_w));
    }

    // At a split the stronger part goes on as this ray (and keeps its drawn
    // path); the weaker is followed too if it is worth following, and counted
    // if it is not.
    void split(Going &a, Going &b, Going &g) {
        const bool a_stronger = total(a.power_w) >= total(b.power_w);
        Going &stronger = a_stronger ? a : b;
        Going &weaker = a_stronger ? b : a;
        weaker.path = -1;
        if (total(weaker.power_w) >= settings_.follow_share * g.started_w) waiting_.push_back(weaker);
        else result_.ledger.unfollowed_w += total(weaker.power_w);
        g = stronger;
    }

    // A ray leaving a surface starts on its own line, far enough along it to be
    // `offset_m` off the surface -- no further than twenty times that, for one
    // leaving almost along the surface -- so that it does not meet the surface
    // it stands on, and the path drawn and the path followed are one line.
    void leave(Going &g, const Vec3 &at, const Vec3 &along, const Vec3 &normal) const {
        g.along = along;
        g.skipped_m = settings_.offset_m / std::max(std::abs(dot(along, normal)), 0.05);
        g.from = at + g.skipped_m * along;
    }

    // The nearest surface through the air. A long look is looked again from
    // just short of what it found: a hit is found to a fraction of the length
    // looked along, so the second look puts it where it is to a fraction of
    // ten centimetres.
    Meeting look(const Vec3 &from, const Vec3 &along, int ignore) {
        ++result_.casts;
        Meeting m = scene_.toSurface(from, along, settings_.reach_m, ignore);
        if (m.hit && m.distance_m > 0.25) {
            const double back = 0.05;
            ++result_.casts;
            const Meeting again = scene_.toSurface(m.point_m - back * along, along, 2.0 * back, ignore);
            if (again.hit) {
                const double distance = m.distance_m - back + again.distance_m;
                m = again;
                m.distance_m = distance;
            }
        }
        return m;
    }

    void follow(Going g) {
        while (true) {
            if (g.met >= settings_.bounce_limit) {
                result_.ledger.bounce_limit_w += total(g.power_w);
                return;
            }
            if (g.inside < 0) {
                const Meeting m = look(g.from, g.along, g.ignore);
                g.ignore = -1;
                if (!m.hit) {
                    result_.ledger.escaped_w += total(g.power_w);
                    leg(g, g.from + settings_.drawn_escape_m * g.along);
                    return;
                }
                leg(g, m.point_m);
                // The normal facing back the way the light came.
                const Vec3 toward = dot(g.along, m.normal) > 0.0 ? -1.0 * m.normal : m.normal;
                if (m.body >= 0) scene_.arrives(m.body, m.point_m, g.along, toward, g.power_w);
                const Surface s = scene_.surface(m.body);
                ++g.met;
                if (s.transparent) {
                    // Smooth: Fresnel shares it between the reflection and the
                    // refraction, the same share in both bands.
                    const Refraction r = refract(g.along, toward, 1.0, s.refractive_index);
                    Going reflected = g;
                    leave(reflected, m.point_m, normalized(reflect(g.along, toward)), toward);
                    reflected.power_w = scaled(g.power_w, r.reflectance);
                    if (r.total) {
                        g = reflected;
                        continue;
                    }
                    Going through = g;
                    leave(through, m.point_m, r.along, toward);
                    through.power_w = {g.power_w[0] - reflected.power_w[0], g.power_w[1] - reflected.power_w[1]};
                    through.inside = m.body;
                    split(through, reflected, g);
                    continue;
                }
                // Opaque: so much absorbed, so much reflected as from a mirror,
                // and the rest scattered -- band by band.
                double absorbed = 0.0, scattered = 0.0;
                Power specular{};
                for (std::size_t b = 0; b < kBands; ++b) {
                    const double a = g.power_w[b] * s.absorbed[b];
                    specular[b] = g.power_w[b] * s.specular[b];
                    absorbed += a;
                    scattered += std::max(0.0, g.power_w[b] - a - specular[b]);
                }
                absorbAt(m.body, absorbed);
                result_.ledger.scattered_w += scattered;
                if (!(total(specular) > 0.0)) return;
                g.power_w = specular;
                leave(g, m.point_m, normalized(reflect(g.along, toward)), toward);
                continue;
            }
            // Inside a transparent body: absorbed on the way to where it
            // reaches the surface again, each band at its own rate.
            ++result_.casts;
            const Surface s = scene_.surface(g.inside);
            const Meeting m = scene_.outOf(g.inside, g.from, g.along, settings_.reach_m);
            if (!m.hit) {
                // It came in across a sharp edge and is already outside the
                // body's other face (a broken piece's corners are sharp to a
                // micrometre): it goes on through the air from where it is.
                ++result_.grazed;
                g.inside = -1;
                continue;
            }
            leg(g, m.point_m);   // drawn with the power it set out with
            // The path through it is from the surface it came in by, where the
            // ray truly started, to where it leaves.
            const double path_m = m.distance_m + g.skipped_m;
            double absorbed = 0.0;
            for (std::size_t b = 0; b < kBands; ++b) {
                const double kept = g.power_w[b] * std::exp(-s.absorption_per_m[b] * path_m);
                absorbed += g.power_w[b] - kept;
                g.power_w[b] = kept;
            }
            absorbAt(g.inside, absorbed);
            ++g.met;
            const Vec3 outward = dot(g.along, m.normal) < 0.0 ? -1.0 * m.normal : m.normal;
            const Vec3 toward = -1.0 * outward;
            const Refraction r = refract(g.along, toward, s.refractive_index, 1.0);
            Going reflected = g;
            leave(reflected, m.point_m, normalized(reflect(g.along, toward)), toward);
            reflected.power_w = scaled(g.power_w, r.reflectance);
            if (r.total) {
                // Past the critical angle nothing gets out: all of it turns back.
                g = reflected;
                continue;
            }
            Going out = g;
            leave(out, m.point_m, r.along, outward);
            out.power_w = {g.power_w[0] - reflected.power_w[0], g.power_w[1] - reflected.power_w[1]};
            out.inside = -1;
            split(out, reflected, g);
        }
    }

    Scene &scene_;
    const Settings &settings_;
    Result result_;
    std::vector<Going> waiting_;
};

} // namespace

Result trace(Scene &scene, std::size_t bodies, const std::vector<Ray> &rays, const Settings &settings) {
    if (!(settings.follow_share >= 0.0 && settings.follow_share <= 1.0) || !(settings.reach_m > 0.0) ||
        !(settings.offset_m > 0.0))
        throw std::invalid_argument("light: settings out of range");
    Tracer tracer(scene, bodies, settings);
    tracer.run(rays);
    return tracer.take();
}

} // namespace banjo::optics
