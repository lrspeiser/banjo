// CPU backend of the fast explicit lattice lane: the same phases, in the same
// order and with the same element functions as the CUDA kernel, executed by
// one thread. It is the fallback when the build has no CUDA and the reference
// the kernel is proven equal to.

#include "fastlattice/FastLattice.hpp"
#include "fastlattice/LatticeWorking.hpp"
#include "fastlattice/ExternalLoads.hpp"
#include "fastlattice/VerletBonds.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace banjo::fastlattice {
namespace {

template <typename Real>
class CpuLatticeBackend final : public LatticeBackend {
public:
    explicit CpuLatticeBackend(LatticeSchedule schedule) : schedule_(std::move(schedule)) {}

    bool runReversibleTrial(const std::function<bool()> &trial) override {
        if constexpr (!std::is_same_v<Real,double>) {
            throw std::invalid_argument("lattice trials require serial double CPU");
        } else {
            if (!trial||!L_.node_count||trial_depth_) throw std::invalid_argument("invalid lattice trial; nesting is forbidden");
            std::size_t bytes=working_.payloadBytes()+external_.payloadBytes()+gravity_.payloadBytes()+sizeof(status_)+
                sizeof(S_)+sizeof(sphere_)+sizeof(origin_)+sizeof(dirty_start_)+sizeof(contact_rebuild_)+
                sizeof(energy_flat_fraction_)+sizeof(phase_clock_)+
                first_failure_bonds_.size()*sizeof(std::uint32_t)+frames_.size()*sizeof(FrameCapture);
            for (const auto &frame:frames_) bytes+=frame.u.size()*sizeof(float)+frame.alive.size()+frame.damage.size()*sizeof(float);
            for (const auto &source:status_.external_sources) bytes+=sizeof(source)+source.source.size();
            if (bytes>16U*1024U*1024U) throw std::invalid_argument("lattice trial exceeds 16 MiB payload budget");
            auto working=working_;auto external=external_;auto gravity=gravity_;auto status=status_;
            auto frames=frames_;auto failures=first_failure_bonds_;
            const auto settings=S_;const auto sphere=sphere_;const auto origin=origin_;
            const bool dirty=dirty_start_,rebuild=contact_rebuild_;
            const double fraction=energy_flat_fraction_;const auto phase=phase_clock_;
            const auto restore=[&] {
                working_=std::move(working);L_=working_.arrays();external_=std::move(external);gravity_=std::move(gravity);
                status_=std::move(status);frames_=std::move(frames);first_failure_bonds_=std::move(failures);
                S_=settings;sphere_=sphere;origin_=origin;dirty_start_=dirty;contact_rebuild_=rebuild;
                energy_flat_fraction_=fraction;phase_clock_=phase;
            };
            ++trial_depth_;bool accepted=false;
            try {accepted=trial();}catch (...) {--trial_depth_;restore();throw;}
            --trial_depth_;if (!accepted) restore();return accepted;
        }
    }

    [[nodiscard]] std::string name() const override {
        return std::string("cpu-") + (sizeof(Real) == 4 ? "float" : "double");
    }

    void upload(const LatticeState &state, const StepSettings<double> &settings,
                const SphereState<double> &sphere) override {
        if (trial_depth_) throw std::logic_error("lattice upload is forbidden during a trial");
        if (settings.bond_integrator!=kBondXpbd&&settings.bond_integrator!=kBondVelocityVerlet)
            throw std::invalid_argument("unknown bond integrator");
        if (settings.bond_integrator==kBondVelocityVerlet) {
            const auto nodes=static_cast<std::size_t>(state.node_count),bonds=static_cast<std::size_t>(state.bond_count);
            if (state.x0.size()!=3*nodes||state.u.size()!=3*nodes||state.u_prev.size()!=3*nodes||state.v.size()!=3*nodes||
                state.mass.size()!=nodes||state.inv_mass.size()!=nodes||state.alive.size()!=bonds||
                state.bond_a.size()!=bonds||state.bond_b.size()!=bonds||state.compliance.size()!=bonds||
                state.rest_length.size()!=bonds||state.rest_edge.size()!=3*bonds||state.plastic_extension.size()!=bonds||
                state.plastic_strain.size()!=bonds)
                throw std::invalid_argument("Verlet reference needs complete node/bond arrays");
        }
        auto staged=WorkingLattice<Real>::fromState(state,schedule_);
        // Contact selection is qualified only in this bounded reference. Larger
        // lattices keep their existing backend support; the contact API refuses.
        std::unique_ptr<MaterialContactTopology> staged_topology;
        if constexpr(std::is_same_v<Real,double>) {
            if(settings.bond_integrator==kBondVelocityVerlet&&state.node_count&&state.node_count<=1024&&state.bond_count<=65536) {
                if(state.bond_a.size()!=state.bond_count||state.bond_b.size()!=state.bond_count)
                    throw std::invalid_argument("live contact topology needs complete canonical bonds");
                staged_topology=std::make_unique<MaterialContactTopology>(state.node_count,state.bond_a,state.bond_b);
            }
        }
        CpuExternalLoads<Real> staged_gravity;staged_gravity.reset(state.origin);
        if (settings.bond_integrator==kBondVelocityVerlet) {
            const auto arrays=staged.arrays();const auto converted=convertSettings<Real>(settings);
            verlet::validate(arrays,converted);verlet::checkStep(arrays,converted);
            if (!finite(state.origin)) throw std::invalid_argument("Verlet reference needs a finite world origin");
            std::vector<Vec3> forces(arrays.node_count);
            for (std::uint32_t i=0;i<arrays.node_count;++i) forces[i]=double(arrays.mass[i])*verlet::widen(converted.gravity);
            staged_gravity.set(forces,std::numeric_limits<std::uint64_t>::max(),arrays,true);
        }
        working_ = std::move(staged);
        contact_topology_=std::move(staged_topology);
        L_ = working_.arrays();
        S_ = convertSettings<Real>(settings);
        sphere_ = convertSphere<Real>(sphere);
        status_ = {};
        status_.bond_integrator=S_.bond_integrator;
        external_.reset(state.origin);
        gravity_=std::move(staged_gravity);
        origin_=state.origin;
        dirty_start_ = true;
        contact_rebuild_ = true;
        status_.energy_audited = S_.audit_energy != 0 || S_.bond_integrator==kBondVelocityVerlet;
        frames_.clear();
        first_failure_bonds_.clear();
    }

    void setExternalForces(const std::vector<Vec3> &forces, std::uint64_t substeps) override {
        external_.set(forces,substeps,L_,S_.bond_integrator==kBondVelocityVerlet);
    }
    void setExternalWrenches(const std::vector<ExternalWrench> &wrenches, std::uint64_t substeps) override {
        external_.setWrenches(wrenches,substeps,L_);
    }
    [[nodiscard]] double externalContactTimestep() const override {
        if constexpr(std::is_same_v<Real,double>) {
        if(!L_.node_count||!std::isfinite(S_.dt)||S_.dt<=0)throw std::invalid_argument("external contact needs an uploaded finite timestep");
        return S_.dt;
        }else throw std::invalid_argument("external point contact requires serial double CPU");
    }
    [[nodiscard]] ActiveNodeState externalContactPoint(std::uint32_t i) const override {
        if constexpr(std::is_same_v<Real,double>) {
        (void)externalContactTimestep();
        if(i>=L_.node_count||!std::isfinite(L_.mass[i])||L_.mass[i]<=0||!std::isfinite(L_.inv_mass[i])||L_.inv_mass[i]<=0)
            throw std::invalid_argument("external contact needs a finite movable schedule node");
        ActiveNodeState point;point.mass_kg=L_.mass[i];
        point.position_world_m=origin_+Vec3{L_.x0[3*i]+L_.u[3*i],L_.x0[3*i+1]+L_.u[3*i+1],L_.x0[3*i+2]+L_.u[3*i+2]};
        point.previous_position_world_m=origin_+Vec3{L_.x0[3*i]+L_.u_prev[3*i],L_.x0[3*i+1]+L_.u_prev[3*i+1],L_.x0[3*i+2]+L_.u_prev[3*i+2]};
        point.velocity_m_s={L_.v[3*i],L_.v[3*i+1],L_.v[3*i+2]};
        if(!finite(point.position_world_m)||!finite(point.previous_position_world_m)||!finite(point.velocity_m_s))
            throw std::invalid_argument("external contact point is nonfinite");
        return point;
        }else throw std::invalid_argument("external point contact requires serial double CPU");
    }
    [[nodiscard]] ExternalPointTransferLedger validateExternalPointVelocity(std::uint32_t i,const ActiveNodeState &expected,Vec3 velocity) const override {
        const ExternalPointVelocity entry{i,expected,velocity};
        return validateExternalPointVelocities({&entry,1});
    }
    [[nodiscard]] ExternalPointTransferLedger validateExternalPointVelocities(std::span<const ExternalPointVelocity> entries) const override {
        if constexpr(std::is_same_v<Real,double>) {
        if(entries.empty()||entries.size()>64)throw std::invalid_argument("external contact transfer needs 1..64 nodes");
        ExternalPointTransferLedger out;out.transfers=1;
        const auto equal=[](Vec3 a,Vec3 b){return a.x==b.x&&a.y==b.y&&a.z==b.z;};
        for(std::size_t j=0;j<entries.size();++j) {
        const auto &[i,expected,velocity]=entries[j];
        for(std::size_t k=0;k<j;++k)if(entries[k].node==i)throw std::invalid_argument("duplicate external contact node");
        const auto current=externalContactPoint(i);
        if(!equal(expected.position_world_m,current.position_world_m)||!equal(expected.previous_position_world_m,current.previous_position_world_m)||
            !equal(expected.velocity_m_s,current.velocity_m_s)||expected.mass_kg!=current.mass_kg||
            !equal(expected.spin_angular_velocity_rad_s,{})||!finite(velocity))
            throw std::invalid_argument("external point transfer has stale or invalid state");
        const Vec3 impulse=current.mass_kg*(velocity-current.velocity_m_s);
        out.impulse_n_s+=impulse;
        out.angular_impulse_kg_m2_s+=cross(current.position_world_m,impulse);
        out.work_j+=.5*current.mass_kg*dot(velocity-current.velocity_m_s,velocity+current.velocity_m_s);
        if(!finite(impulse)||!finite(out.impulse_n_s)||!finite(out.angular_impulse_kg_m2_s)||!std::isfinite(out.work_j))
            throw std::overflow_error("external contact region ledger overflow");
        }
        (void)combinedPointLedger(status_.external_point_transfer,out);
        return out;
        }else throw std::invalid_argument("external point contact requires serial double CPU");
    }
    ExternalPointTransferLedger applyExternalPointVelocity(std::uint32_t i,const ActiveNodeState &expected,Vec3 velocity) override {
        const ExternalPointVelocity entry{i,expected,velocity};
        return applyExternalPointVelocities({&entry,1});
    }
    ExternalPointTransferLedger applyExternalPointVelocities(std::span<const ExternalPointVelocity> entries) override {
        if constexpr(std::is_same_v<Real,double>) {
        const auto receipt=validateExternalPointVelocities(entries);
        const auto total=combinedPointLedger(status_.external_point_transfer,receipt);
        for(const auto &[i,expected,velocity]:entries) {
        (void)expected;
        L_.v[3*i]=static_cast<Real>(velocity.x);L_.v[3*i+1]=static_cast<Real>(velocity.y);L_.v[3*i+2]=static_cast<Real>(velocity.z);
        }
        status_.external_point_transfer=total;return receipt;
        }else throw std::invalid_argument("external point contact requires serial double CPU");
    }
    [[nodiscard]] MaterialContactRegion externalContactRegion(std::uint32_t seed,const MaterialContactRegionSettings &settings) const override {
        if constexpr(std::is_same_v<Real,double>) {
            (void)externalContactTimestep();
            if(!contact_topology_)throw std::invalid_argument("live contact regions need bounded serial-double Verlet");
            auto out=contact_topology_->select(seed,working_.alive,settings,
                [&](std::uint32_t i){return externalContactPoint(i).position_world_m;},
                [&](std::uint32_t i){return working_.inv_mass[i]>0;});
            out.target_step=status_.total_steps;return out;
        }else throw std::invalid_argument("live material contact requires serial double CPU");
    }

    RunStatus run(const RunControl &control) override {
        energy_flat_fraction_ = control.energy_flat_fraction;
        const auto start = std::chrono::steady_clock::now();
        status_.exit_reason = 0;
        std::uint64_t done = 0;
        while (done < control.max_steps) {
            const std::uint64_t step = status_.total_steps;
            if (control.capture_stride != 0 && step % control.capture_stride == 0 &&
                status_.frames_captured < control.max_frames) {
                frames_.push_back(captureFrame(working_, step, sphere_));
                ++status_.frames_captured;
            }
            const bool failed = advance(step);
            status_.total_steps = step + 1;
            ++done;
            if (failed) {
                if (status_.first_failure_step == std::numeric_limits<std::uint64_t>::max())
                    status_.first_failure_step = step;
                status_.last_failure_step = step;
                ++status_.failure_rounds;
            }
            const double available = control.removable_energy_j + status_.external_load.work_j + status_.external_point_transfer.work_j + status_.gravity_load.work_j;
            status_.exit_reason = control.removable_energy_j > 0 && available <= 0 ? 6 :
                latticeExitReason(status_.total_steps, status_.broken_bonds,
                status_.last_failure_step, control.quiet_steps, control.min_steps,
                control.no_failure_steps, control.energy_flat_steps,
                status_.last_energy_gain_step, control.calm_steps,
                status_.last_damage_gain_step, status_.max_damage,
                control.calm_damage_margin, status_.removed_energy_j,
                control.removable_energy_j > 0 ? available : 0.0);
            if (status_.exit_reason != 0) break;
        }
        if (status_.exit_reason == 0 && done >= control.max_steps) status_.exit_reason = 3;
        ++status_.launches;
        status_.wall_seconds += std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        return status_;
    }

    void download(LatticeState &state, SphereState<double> &sphere) override {
        working_.toState(state);
        sphere = widenSphere(sphere_);
    }

    std::vector<FrameCapture> takeFrames() override {
        std::vector<FrameCapture> out;
        out.swap(frames_);
        status_.frames_captured = 0;
        return out;
    }

    [[nodiscard]] const RunStatus &status() const override { return status_; }
    [[nodiscard]] std::vector<std::uint32_t> firstFailureBonds() const override { return first_failure_bonds_; }

private:
    // Immutable across every trial; upload/configuration are forbidden in trials.
    std::unique_ptr<MaterialContactTopology> contact_topology_;
    static bool finite(Vec3 v) {return std::isfinite(v.x)&&std::isfinite(v.y)&&std::isfinite(v.z);}
    static ExternalPointTransferLedger combinedPointLedger(const ExternalPointTransferLedger &a,const ExternalPointTransferLedger &b) {
        if(a.transfers>std::numeric_limits<std::uint64_t>::max()-b.transfers)throw std::overflow_error("external point count overflow");
        ExternalPointTransferLedger out;out.transfers=a.transfers+b.transfers;
        out.impulse_n_s=a.impulse_n_s+b.impulse_n_s;out.angular_impulse_kg_m2_s=a.angular_impulse_kg_m2_s+b.angular_impulse_kg_m2_s;
        out.work_j=a.work_j+b.work_j;
        if(!finite(b.impulse_n_s)||!finite(b.angular_impulse_kg_m2_s)||!std::isfinite(b.work_j)||
            !finite(out.impulse_n_s)||!finite(out.angular_impulse_kg_m2_s)||!std::isfinite(out.work_j))
            throw std::overflow_error("external point transfer ledger overflow");
        return out;
    }
    template <typename Body>
    void sweep(std::uint32_t block, std::uint32_t boundary, Body &&body) {
        for (std::uint32_t c = 0; c < L_.color_count; ++c) {
            const std::size_t key = (static_cast<std::size_t>(block) * 2U + boundary) * L_.color_count + c;
            for (std::uint32_t j = L_.range_begin[key]; j < L_.range_end[key]; ++j) body(j);
        }
    }

    template <typename Body>
    void sweepAll(Body &&body) {
        for (std::uint32_t block = 0; block < L_.block_count; ++block) sweep(block, 0U, body);
        for (std::uint32_t block = 0; block < L_.block_count; block += 2U) sweep(block, 1U, body);
        for (std::uint32_t block = 1; block < L_.block_count; block += 2U) sweep(block, 1U, body);
    }

    void mark(unsigned phase) {
        const auto now = std::chrono::steady_clock::now();
        status_.phase_seconds[phase] += std::chrono::duration<double>(now - phase_clock_).count();
        phase_clock_ = now;
    }

    // One substep; returns whether any bond failed.
    bool advance(std::uint64_t step) {
        if (S_.bond_integrator==kBondVelocityVerlet) return advanceVerlet(step);
        const bool direct = S_.direct_arithmetic != 0;
        const std::uint32_t N = L_.node_count, B = L_.bond_count;
        (void)step;
        phase_clock_ = std::chrono::steady_clock::now();
        if (dirty_start_) {
            for (std::uint32_t i = 0; i < N; ++i) nodeStrain(L_, i, direct, S_.plate_half_thickness, S_.plastic_yield_stretch);
            mark(1);
            for (std::uint32_t j = 0; j < B; ++j)
                if (L_.alive[j]) bondStartSample(L_, j, direct);
            mark(2);
            dirty_start_ = false;
        }
        // Kick, classify, ordered candidate lists per block.
        external_.kick(L_,S_.dt,status_.external_load,&status_.external_sources);
        SphereState<Real> kicked = sphere_;
        kicked.velocity = kicked.velocity + S_.dt * S_.gravity;
        for (std::uint32_t block = 0; block < L_.block_count; ++block) {
            std::uint32_t count = 0;
            for (std::uint32_t i = L_.node_block_begin[block]; i < L_.node_block_begin[block + 1]; ++i) {
                if (!nodeKickAndClassify(L_, S_, kicked, i)) continue;
                if (count < kMaxCandidatesPerBlock)
                    L_.candidate_list[block * kMaxCandidatesPerBlock + count] = i;
                else
                    ++status_.contact.candidate_overflow;
                ++count;
            }
            L_.candidate_count[block] = count < kMaxCandidatesPerBlock ? count : kMaxCandidatesPerBlock;
        }
        sphere_ = kicked;
        mark(3);
        if (S_.sphere_enabled) {
            const double before = S_.audit_energy ? latticeKineticEnergy(L_) : 0.0;
            sphereContactPass(L_, S_, sphere_, 1, status_.contact);
            if (S_.audit_energy) status_.striker_dissipated_j += before - latticeKineticEnergy(L_);
        }
        mark(4);
        for (std::uint32_t iteration = 0; iteration < S_.constraint_iterations; ++iteration) {
            const bool first = iteration == 0;
            for (std::uint32_t block = 0; block < L_.block_count; ++block)
                sweep(block, 0U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            mark(5);
            for (std::uint32_t block = 0; block < L_.block_count; block += 2U)
                sweep(block, 1U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            for (std::uint32_t block = 1; block < L_.block_count; block += 2U)
                sweep(block, 1U, [&](std::uint32_t j) { bondSolve(L_, j, S_.dt, direct, first); });
            mark(6);
            for (std::uint32_t i = 0; i < N; ++i) nodeSupportProject(L_, S_, i);
            mark(7);
        }
        for (std::uint32_t i = 0; i < N; ++i) nodeVelocityUpdate(L_, S_, i);
        mark(8);
        if (S_.damping_fraction > Real(0)) {
            const double before = S_.audit_energy ? latticeKineticEnergy(L_) : 0.0;
            sweepAll([&](std::uint32_t j) { bondDamp(L_, j, S_.damping_fraction, direct); });
            if (S_.audit_energy) status_.damping_dissipated_j += before - latticeKineticEnergy(L_);
            for (std::uint32_t i = 0; i < N; ++i)
                if (!L_.candidate[i]) nodeSupportVelocity(L_, S_, i);
            mark(9);
        }
        if (S_.sphere_enabled) {
            const double before = S_.audit_energy ? latticeKineticEnergy(L_) : 0.0;
            sphereContactPass(L_, S_, sphere_, 2, status_.contact);
            if (S_.audit_energy) status_.striker_dissipated_j += before - latticeKineticEnergy(L_);
        }
        mark(10);
        if (S_.node_contact.mode != kNodeContactOff) {
            if (contact_rebuild_ || nodeContactStale(L_, S_)) {
                for (std::uint32_t i = 0; i < N; ++i) nodeContactStoreCell(L_, S_, i);
                nodeContactHashBuild(L_, S_);
                for (std::uint32_t i = 0; i < N; ++i)
                    status_.node_contact.pair_overflow += nodeContactGather(L_, S_, i);
                status_.node_contact.pairs_listed += nodeContactActiveList(L_);
                ++status_.node_contact.rebuilds;
                contact_rebuild_ = false;
            }
            mark(14);
            nodeContactPass(L_, S_, status_.node_contact);
            mark(15);
        }
        return finishStep(direct,N,B);
    }

    bool finishStep(bool direct,std::uint32_t N,std::uint32_t B) {
        for (std::uint32_t i = 0; i < N; ++i) nodeStrain(L_, i, direct, S_.plate_half_thickness, S_.plastic_yield_stretch);
        mark(11);
        bool any_failed = false;
        const bool first_failure_round = status_.broken_bonds == 0;
        for (std::uint32_t j = 0; j < B; ++j) {
            if (!L_.alive[j]) continue;
            const Real old_plastic=L_.plastic_extension[j];
            const FailureOutcome out = bondEndSampleAndFailure(L_, S_, j, direct);
            if (S_.bond_integrator==kBondVelocityVerlet) {
                const double increment=std::abs(double(L_.plastic_extension[j]-old_plastic));
                status_.plastic_return_numerical_loss_j+=.5*(1+double(S_.plastic_hardening))*increment*increment/double(L_.compliance[j]);
            }
            status_.max_tensile_stretch = std::max(status_.max_tensile_stretch, out.peak_tensile);
            status_.max_compressive_strain = std::max(status_.max_compressive_strain, out.peak_compressive);
            status_.max_shear_strain = std::max(status_.max_shear_strain, out.peak_shear);
            status_.plastic_work_j += out.plastic_increment_j;
            status_.max_plastic_stretch = std::max(status_.max_plastic_stretch, out.plastic_stretch);
            // See the parallel backend: the worst bond's progress toward
            // failure, and the substep it last climbed at, which is what
            // exit reason 5 waits on.
            if (out.damage > status_.max_damage + 1.0e-6) {
                status_.max_damage = out.damage;
                status_.last_damage_gain_step = status_.total_steps;
            }
            if (!out.broke) continue;
            any_failed = true;
            if (first_failure_round) first_failure_bonds_.push_back(j);
            status_.removed_energy_j += out.removed_energy_j;
            // See the parallel backend: the substep at which removed energy
            // last grew materially, which is what exit reason 4 waits on.
            if (out.removed_energy_j >
                energy_flat_fraction_ * std::max(status_.removed_energy_j, 1.0e-12))
                status_.last_energy_gain_step = status_.total_steps;
            ++status_.broken_bonds;
            L_.node_dirty[L_.bond_a[j]] = 1;
            L_.node_dirty[L_.bond_b[j]] = 1;
        }
        mark(12);
        status_.rank_deficient_nodes = working_.rank_deficient_nodes.front();
        sphere_.center = sphere_.center + S_.dt * sphere_.velocity;
        sphereSupportContact(S_, sphere_, status_.contact);
        // A failure changes which pairs no live bond holds, so the pair list is
        // rebuilt before it is used again.
        if (any_failed) dirty_start_ = contact_rebuild_ = true;
        mark(13);
        return any_failed;
    }

    bool advanceVerlet(std::uint64_t step) {
        (void)step;
        const bool direct=S_.direct_arithmetic!=0;
        const auto mechanical=[&](){return latticeKineticEnergy(L_)+latticeElasticEnergy(L_,direct);};
        const auto losses=[&](){return status_.damping_dissipated_j+status_.removed_energy_j+
            status_.plastic_work_j+status_.plastic_return_numerical_loss_j;};
        const double before=mechanical(),loss_before=losses();
        const double work_before=status_.external_load.work_j+status_.gravity_load.work_j;
        phase_clock_=std::chrono::steady_clock::now();
        if (dirty_start_) {
            for (std::uint32_t i=0;i<L_.node_count;++i) nodeStrain(L_,i,direct,S_.plate_half_thickness,S_.plastic_yield_stretch);
            mark(1);
            for (std::uint32_t j=0;j<L_.bond_count;++j) if (L_.alive[j]) bondStartSample(L_,j,direct);
            mark(2);dirty_start_=false;
        }
        // Two half kicks consume one load substep. All spring forces at a
        // kick use the same positions; no position projection or v rebuild.
        external_.kick(L_,Real(.5)*S_.dt,status_.external_load,&status_.external_sources,false,&status_.fixed_boundary);
        gravity_.kick(L_,Real(.5)*S_.dt,status_.gravity_load,nullptr,false,&status_.fixed_boundary);mark(3);
        verlet::kick(L_,S_,origin_,status_);mark(4);
        verlet::drift(L_,S_.dt);mark(5);
        verlet::kick(L_,S_,origin_,status_);mark(8);
        external_.kick(L_,Real(.5)*S_.dt,status_.external_load,&status_.external_sources,true,&status_.fixed_boundary);
        gravity_.kick(L_,Real(.5)*S_.dt,status_.gravity_load,nullptr,true,&status_.fixed_boundary);mark(10);
        if (S_.damping_fraction>Real(0)) {
            const double kinetic=latticeKineticEnergy(L_);
            sweepAll([&](std::uint32_t j){bondDamp(L_,j,S_.damping_fraction,direct);});
            status_.damping_dissipated_j+=kinetic-latticeKineticEnergy(L_);mark(9);
        }
        const bool failed=finishStep(direct,L_.node_count,L_.bond_count);
        const double error=mechanical()-before+losses()-loss_before-
            (status_.external_load.work_j+status_.gravity_load.work_j-work_before);
        if (!std::isfinite(error)||!std::isfinite(status_.integration_numerical_energy_j+error))
            throw std::overflow_error("Verlet measured integration energy overflow");
        status_.integration_numerical_energy_j+=error;
        return failed;
    }

    std::chrono::steady_clock::time_point phase_clock_{};

    LatticeSchedule schedule_;
    WorkingLattice<Real> working_;
    LatticeArrays<Real> L_{};
    StepSettings<Real> S_{};
    SphereState<Real> sphere_{};
    RunStatus status_{};
    CpuExternalLoads<Real> external_;
    CpuExternalLoads<Real> gravity_;
    unsigned trial_depth_{};
    Vec3 origin_{};
    // RunControl::energy_flat_fraction, held here because the substep that
    // accumulates removed energy does not see the control.
    double energy_flat_fraction_{1.0e-3};
    bool dirty_start_{true};
    bool contact_rebuild_{true};
    std::vector<FrameCapture> frames_;
    std::vector<std::uint32_t> first_failure_bonds_;
};

} // namespace

std::unique_ptr<LatticeBackend> makeCpuLatticeBackend(
    const LatticeSchedule &schedule, Precision precision) {
    if (precision == Precision::Float) return std::make_unique<CpuLatticeBackend<float>>(schedule);
    return std::make_unique<CpuLatticeBackend<double>>(schedule);
}

} // namespace banjo::fastlattice
