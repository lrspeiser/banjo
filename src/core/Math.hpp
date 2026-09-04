#pragma once

#include <array>
#include <cmath>
#include <optional>

namespace banjo {

struct Vec3 {
    double x{};
    double y{};
    double z{};

    [[nodiscard]] constexpr Vec3 operator+() const { return *this; }
    [[nodiscard]] constexpr Vec3 operator-() const { return {-x, -y, -z}; }

    [[nodiscard]] constexpr Vec3 operator+(const Vec3 &other) const {
        return {x + other.x, y + other.y, z + other.z};
    }

    [[nodiscard]] constexpr Vec3 operator-(const Vec3 &other) const {
        return {x - other.x, y - other.y, z - other.z};
    }

    [[nodiscard]] constexpr Vec3 operator*(double scalar) const {
        return {x * scalar, y * scalar, z * scalar};
    }

    [[nodiscard]] constexpr Vec3 operator/(double scalar) const {
        return {x / scalar, y / scalar, z / scalar};
    }

    constexpr Vec3 &operator+=(const Vec3 &other) {
        x += other.x;
        y += other.y;
        z += other.z;
        return *this;
    }

    constexpr Vec3 &operator-=(const Vec3 &other) {
        x -= other.x;
        y -= other.y;
        z -= other.z;
        return *this;
    }

    constexpr Vec3 &operator*=(double scalar) {
        x *= scalar;
        y *= scalar;
        z *= scalar;
        return *this;
    }
};

[[nodiscard]] constexpr Vec3 operator*(double scalar, const Vec3 &value) {
    return value * scalar;
}

[[nodiscard]] constexpr double dot(const Vec3 &a, const Vec3 &b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
}

[[nodiscard]] constexpr Vec3 cross(const Vec3 &a, const Vec3 &b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
}

[[nodiscard]] constexpr double lengthSquared(const Vec3 &value) { return dot(value, value); }

[[nodiscard]] inline double length(const Vec3 &value) { return std::sqrt(lengthSquared(value)); }

[[nodiscard]] inline Vec3 normalized(const Vec3 &value, const Vec3 &fallback = {1.0, 0.0, 0.0}) {
    const double magnitude = length(value);
    return magnitude > 1.0e-12 ? value / magnitude : fallback;
}

struct Quat {
    double w{1.0};
    double x{};
    double y{};
    double z{};

    [[nodiscard]] Vec3 rotate(const Vec3 &value) const {
        const Vec3 qv{x, y, z};
        const Vec3 t = 2.0 * cross(qv, value);
        return value + w * t + cross(qv, t);
    }
};

struct Mat3 {
    std::array<std::array<double, 3>, 3> m{};

    [[nodiscard]] Vec3 operator*(const Vec3 &v) const {
        return {
            m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z,
            m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
            m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z,
        };
    }

    [[nodiscard]] double determinant() const {
        return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
               m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
               m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    }

    [[nodiscard]] std::optional<Mat3> inverse(double epsilon = 1.0e-12) const {
        const double det = determinant();
        if (std::abs(det) <= epsilon) {
            return std::nullopt;
        }

        Mat3 result;
        result.m[0][0] = (m[1][1] * m[2][2] - m[1][2] * m[2][1]) / det;
        result.m[0][1] = (m[0][2] * m[2][1] - m[0][1] * m[2][2]) / det;
        result.m[0][2] = (m[0][1] * m[1][2] - m[0][2] * m[1][1]) / det;
        result.m[1][0] = (m[1][2] * m[2][0] - m[1][0] * m[2][2]) / det;
        result.m[1][1] = (m[0][0] * m[2][2] - m[0][2] * m[2][0]) / det;
        result.m[1][2] = (m[0][2] * m[1][0] - m[0][0] * m[1][2]) / det;
        result.m[2][0] = (m[1][0] * m[2][1] - m[1][1] * m[2][0]) / det;
        result.m[2][1] = (m[0][1] * m[2][0] - m[0][0] * m[2][1]) / det;
        result.m[2][2] = (m[0][0] * m[1][1] - m[0][1] * m[1][0]) / det;
        return result;
    }
};

} // namespace banjo
