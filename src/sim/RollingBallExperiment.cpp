#include "sim/RollingBallExperiment.hpp"

#include "fracture/ConnectedComponents.hpp"
#include "material/MaterialCompiler.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

namespace banjo {
namespace {

[[nodiscard]] MaterialDefinition makeIronMaterial() {
    MaterialDefinition material;
    material.name = "iron";
    material.model = MaterialModel::RigidOnly;
    material.density_kg_m3 = 7870.0;
    material.young_modulus_pa = 211.0e9;
    material.poisson_ratio = 0.29;
    material.tensile_strength_pa = 200.0e6;
    material.fracture_energy_j_m2 = 100000.0;
    material.friction = 0.55;
    material.restitution = 0.08;
    return material;
}

[[nodiscard]] MaterialDefinition makeGlassMaterial(std::uint64_t seed) {
    MaterialDefinition material;
    material.name = "brittle_glass_v1";
    material.model = MaterialModel::BrittleBond;
    material.density_kg_m3 = 2500.0;
    material.young_modulus_pa = 70.0e9;
    material.poisson_ratio = 0.22;
    material.tensile_strength_pa = 45.0e6;
    material.fracture_energy_j_m2 = 8.0;
    material.friction = 0.35;
    material.restitution = 0.12;
    material.damping_ratio = 0.015;
    material.strength_variation = 0.12;
    material.seed = seed;
    material.calibration.activation_energy_scale = 1.0;
    material.calibration.damage_strain_multiplier = 8.0;
    material.calibration.break_strain_multiplier = 16.0;
    return material;
}

void validateSettings(const ExperimentSettings &settings) {
    if (settings.radius_m <= 0.0 || settings.voxel_size_m <= 0.0 ||
        settings.neighbor_horizon_cells == 0U || settings.occupancy_samples_per_axis == 0U ||
        settings.rigid_step_s <= 0.0 || settings.material_step_s <= 0.0 ||
        settings.maximum_material_steps == 0U || settings.maximum_rigid_fragments == 0U ||
        settings.maximum_collision_points < 8U || settings.iron_speed_m_s <= 0.0) {
        throw std::invalid_argument("rolling-ball experiment settings are invalid");
    }
    if (settings.minimum_material_steps > settings.maximum_material_steps) {
        throw std::invalid_argument("minimum material steps exceed maximum material steps");
    }
}

[[nodiscard]] bool impactLess(const ImpactEvent &left, const ImpactEvent &right) {
    if (left.fixed_tick != right.fixed_tick) {
        return left.fixed_tick < right.fixed_tick;
    }
    if (left.body_a != right.body_a) {
        return left.body_a < right.body_a;
    }
    if (left.body_b != right.body_b) {
        return left.body_b < right.body_b;
    }
    if (left.contact_point_world_m.x != right.contact_point_world_m.x) {
        return left.contact_point_world_m.x < right.contact_point_world_m.x;
    }
    if (left.contact_point_world_m.y != right.contact_point_world_m.y) {
        return left.contact_point_world_m.y < right.contact_point_world_m.y;
    }
    return left.contact_point_world_m.z < right.contact_point_world_m.z;
}

} // namespace

std::string_view experimentPhaseName(ExperimentPhase phase) {
    switch (phase) {
    case ExperimentPhase::Rigid:
        return "rigid bodies";
    case ExperimentPhase::Fracturing:
        return "active voxel fracture";
    case ExperimentPhase::RigidFragments:
        return "rigid fragments";
    }
    return "unknown";
}

RollingBallExperiment::RollingBallExperiment(ExperimentSettings settings) {
    reset(std::move(settings));
}

RollingBallExperiment::~RollingBallExperiment() = default;
RollingBallExperiment::RollingBallExperiment(RollingBallExperiment &&) noexcept = default;
RollingBallExperiment &RollingBallExperiment::operator=(RollingBallExperiment &&) noexcept = default;

void RollingBallExperiment::reset(ExperimentSettings settings) {
    validateSettings(settings);

    // Destroy Jolt before constructing a replacement because Jolt owns process-global
    // type registration state in this bootstrap integration.
    rigid_world_.reset();
    active_glass_.reset();
    latest_components_.clear();
    fragment_build_ = {};
    debris_particles_.clear();
    activating_impact_.reset();

    settings_ = std::move(settings);
    iron_material_ = makeIronMaterial();
    glass_material_ = makeGlassMaterial(settings_.material_seed);
    compiled_glass_ = compileBrittleMaterial(
        glass_material_, settings_.voxel_size_m, settings_.neighbor_horizon_cells);
    glass_lattice_ = generateSphereLattice(
        {
            settings_.radius_m,
            settings_.voxel_size_m,
            settings_.neighbor_horizon_cells,
            settings_.occupancy_samples_per_axis,
        },
        compiled_glass_);

    solver_ = BrittleBondSolver({
        .substeps = 2,
        .constraint_iterations = 8,
        .floor_height_m = 0.0,
        .floor_friction = 0.4,
        .impact_internal_energy_fraction = settings_.impact_internal_energy_fraction,
        .maximum_internal_energy_j = settings_.maximum_internal_energy_j,
    });

    stats_ = {};
    stats_.phase = ExperimentPhase::Rigid;
    stats_.represented_glass_mass_kg = glass_lattice_.total_mass_kg;
    stats_.active_nodes = glass_lattice_.nodes.size();
    stats_.total_bonds = glass_lattice_.bonds.size();
    stats_.connected_components = 1U;

    last_broken_bonds_ = 0U;
    stable_material_steps_ = 0U;
    material_time_accumulator_s_ = 0.0;
    initializeWorld();
}

void RollingBallExperiment::initializeWorld() {
    rigid_world_ = std::make_unique<JoltWorld>();
    rigid_world_->setGravity(settings_.gravity_m_s2);
    rigid_world_->addFloor();
    rigid_world_->addBall({
        .body_id = kIronBallId,
        .radius_m = settings_.radius_m,
        .material = iron_material_,
        .position_world_m = {-1.50, settings_.radius_m + 0.001, 0.0},
        .linear_velocity_m_s = {settings_.iron_speed_m_s, 0.0, 0.0},
        .angular_velocity_rad_s = {0.0, 0.0, -settings_.iron_speed_m_s / settings_.radius_m},
    });
    rigid_world_->addBall({
        .body_id = kGlassBallId,
        .radius_m = settings_.radius_m,
        .material = glass_material_,
        .position_world_m = {0.0, settings_.radius_m + 0.001, 0.0},
        .linear_velocity_m_s = {},
        .angular_velocity_rad_s = {},
        .mass_override_kg = glass_lattice_.total_mass_kg,
    });
}

void RollingBallExperiment::stepFixed() {
    if (!rigid_world_) {
        throw std::logic_error("rolling-ball experiment has no rigid world");
    }

    switch (stats_.phase) {
    case ExperimentPhase::Rigid:
        stepRigidPhase();
        break;
    case ExperimentPhase::Fracturing:
        stepFracturingPhase();
        break;
    case ExperimentPhase::RigidFragments:
        stepRigidFragmentsPhase();
        break;
    }
}

void RollingBallExperiment::stepRigidPhase() {
    rigid_world_->step(settings_.rigid_step_s);
    ++stats_.rigid_steps;

    std::vector<ImpactEvent> impacts = rigid_world_->drainImpacts();
    std::sort(impacts.begin(), impacts.end(), impactLess);
    for (const ImpactEvent &impact : impacts) {
        if (!impact.involves(kGlassBallId)) {
            continue;
        }

        const ActivationDecision decision = activation_policy_.evaluate(
            impact,
            {
                kGlassBallId,
                settings_.radius_m,
                glass_material_,
                0.0,
            });
        stats_.impact_speed_m_s = impact.closing_speed_m_s;
        stats_.impact_energy_j = impact.available_normal_energy_j;
        stats_.activation_threshold_j = decision.threshold_energy_j;
        stats_.normalized_impact_energy = decision.normalized_energy;
        if (!decision.activate) {
            continue;
        }

        activating_impact_ = impact;
        const RigidSnapshot post_contact_glass = rigid_world_->snapshot(kGlassBallId);
        rigid_world_->removeAndDestroy(kGlassBallId);
        active_glass_ = solver_.activate(
            kGlassBallId,
            glass_lattice_,
            compiled_glass_,
            post_contact_glass,
            impact);
        stats_.phase = ExperimentPhase::Fracturing;
        stats_.broken_bonds = 0U;
        stats_.connected_components = 1U;
        return;
    }
}

void RollingBallExperiment::stepFracturingPhase() {
    rigid_world_->step(settings_.rigid_step_s);
    ++stats_.rigid_steps;
    (void)rigid_world_->drainImpacts();

    if (!active_glass_) {
        throw std::logic_error("fracturing phase has no active glass material");
    }

    material_time_accumulator_s_ += settings_.rigid_step_s;
    while (material_time_accumulator_s_ + 1.0e-12 >= settings_.material_step_s) {
        material_time_accumulator_s_ -= settings_.material_step_s;
        const MaterialStepStats material_stats = solver_.step(
            *active_glass_, settings_.material_step_s, settings_.gravity_m_s2);
        ++stats_.material_steps;

        stats_.broken_bonds = material_stats.total_broken_bonds;
        stats_.maximum_tensile_stretch = material_stats.maximum_tensile_stretch;
        stats_.active_kinetic_energy_j = material_stats.kinetic_energy_j;
        stats_.active_elastic_energy_j = material_stats.estimated_elastic_energy_j;
        stats_.maximum_node_speed_m_s = material_stats.maximum_speed_m_s;

        if (material_stats.total_broken_bonds == last_broken_bonds_) {
            ++stable_material_steps_;
        } else {
            stable_material_steps_ = 0U;
            last_broken_bonds_ = material_stats.total_broken_bonds;
        }

        if (material_stats.broken_bonds_this_step > 0U ||
            stats_.material_steps % 12U == 0U) {
            updateComponentCount();
        }

        const bool minimum_elapsed =
            stats_.material_steps >= settings_.minimum_material_steps;
        const bool fracture_is_stable =
            stable_material_steps_ >= settings_.stable_material_steps_before_handoff;
        const bool maximum_elapsed =
            stats_.material_steps >= settings_.maximum_material_steps;
        if ((minimum_elapsed && fracture_is_stable && stats_.broken_bonds > 0U) ||
            maximum_elapsed) {
            finalizeFragments();
            return;
        }
    }
}

void RollingBallExperiment::stepRigidFragmentsPhase() {
    rigid_world_->step(settings_.rigid_step_s);
    ++stats_.rigid_steps;
    (void)rigid_world_->drainImpacts();
    integrateDebris(settings_.rigid_step_s);
}

void RollingBallExperiment::updateComponentCount() {
    if (!active_glass_) {
        return;
    }
    latest_components_ = findConnectedComponents(*active_glass_);
    stats_.connected_components = latest_components_.size();
}

void RollingBallExperiment::finalizeFragments() {
    if (!active_glass_) {
        throw std::logic_error("cannot finalize fragments without active material");
    }
    updateComponentCount();
    if (latest_components_.empty()) {
        throw std::runtime_error("fractured material produced no connected components");
    }

    fragment_build_ = buildFragmentRepresentations(
        *active_glass_,
        latest_components_,
        {
            .first_body_id = 1000,
            .maximum_rigid_fragments = settings_.maximum_rigid_fragments,
            .minimum_nodes_per_rigid_fragment = settings_.minimum_nodes_per_rigid_fragment,
            .maximum_collision_points = settings_.maximum_collision_points,
            .friction = glass_material_.friction,
            .restitution = glass_material_.restitution,
        });
    rigid_world_->addFragments(fragment_build_.rigid_fragments);

    debris_particles_.reserve(fragment_build_.debris_particles.size());
    for (const DebrisParticleDescription &particle : fragment_build_.debris_particles) {
        debris_particles_.push_back({
            particle.position_world_m,
            particle.velocity_m_s,
            particle.angular_velocity_rad_s,
            particle.mass_kg,
            particle.radius_m,
        });
    }

    stats_.rigid_fragments = fragment_build_.rigid_fragments.size();
    stats_.debris_particles = debris_particles_.size();
    stats_.fragment_mass_kg = fragment_build_.total_mass_kg;
    stats_.mass_error_kg =
        fragment_build_.total_mass_kg - stats_.represented_glass_mass_kg;
    stats_.phase = ExperimentPhase::RigidFragments;
    active_glass_.reset();
}

void RollingBallExperiment::integrateDebris(double dt_s) {
    for (DebrisParticleState &particle : debris_particles_) {
        particle.velocity_m_s += dt_s * settings_.gravity_m_s2;
        particle.position_world_m += dt_s * particle.velocity_m_s;

        if (particle.position_world_m.y < particle.radius_m) {
            particle.position_world_m.y = particle.radius_m;
            if (particle.velocity_m_s.y < 0.0) {
                particle.velocity_m_s.y *= -0.20;
            }
            particle.velocity_m_s.x *= 0.97;
            particle.velocity_m_s.z *= 0.97;
            if (std::abs(particle.velocity_m_s.y) < 0.03) {
                particle.velocity_m_s.y = 0.0;
            }
        }
    }
}

std::optional<RigidSnapshot> RollingBallExperiment::rigidSnapshot(MatterBodyId body_id) const {
    if (!rigid_world_ || !rigid_world_->contains(body_id)) {
        return std::nullopt;
    }
    return rigid_world_->snapshot(body_id);
}

const ActiveMatter *RollingBallExperiment::activeMatter() const {
    return active_glass_ ? &*active_glass_ : nullptr;
}

} // namespace banjo
