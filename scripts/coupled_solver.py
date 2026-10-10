"""One private nonlinear controller for explicit CPU and CUDA backends."""
import numpy as np

class TrialFailure(RuntimeError):
    def __init__(self,message,details=None):
        super().__init__(message);self.details=details or {}

class CoupledNewton:
    def solve(self,h,gravity=-9.81,maximum_iterations=24):
        xp=self.array_api
        original=self.bodies[:,14:20].reshape(-1);y=original[self.dynamic]*self.active_weights
        count=len(y);tolerance=1e-10*max(1.,float(xp.linalg.norm(y)))
        trace=[];last_trial=None;jacobian=None;jacobian_point=None;self.last_solve=None
        fractions=(1.,.1,.01) if self.newton_strategy=='ranked' else (1.,)
        guesses=None;order=[0];start_index=0;start_scores=None
        def refuse(message):
            # Failure-only observations never replace an accepted physical state.
            # Retain the actual last evaluated candidate, rather than inferring
            # the cause from the timestep at which subdivision eventually stops.
            details=dict(dt_s=h,gravity_m_s2=gravity,equation_tolerance=tolerance,iterations=trace,
                initial_bodies=self.to_host(self.bodies).tolist(),initial_edges=self.to_host(self.edges).tolist(),
                iterate_weighted_velocity=self.to_host(y).tolist(),finite_difference_weighted_scale=1e-12,
                finite_difference_displacement_floor_kg_half_m=1e-17,
                newton_strategy=self.newton_strategy,line_search=self.line_search,linear_backend=self.linear_backend,starting_fractions=list(fractions),starting_scores=start_scores,
                attempted_fractions=[fractions[i] for i in order[:start_index+1]])
            if last_trial is not None:
                result,values,velocity=last_trial
                details['last_evaluated']=dict(weighted_velocity=self.to_host(values).tolist(),
                    velocity=self.to_host(velocity).tolist(),poses_wxyz=self.to_host(result['poses']).tolist(),
                    residual=self.to_host(result['residual']).tolist(),forces=self.to_host(result['forces']).tolist(),
                    ledger=self.to_host(result['ledger']).tolist(),faults=self.to_host(result['faults']).tolist(),
                    material_history=self.to_host(result['history']).tolist())
            if jacobian is not None:
                matrix=self.to_host(jacobian)
                if np.isfinite(matrix).all():
                    singular=np.linalg.svd(matrix,compute_uv=False)
                    details['jacobian_singular_values']=singular.tolist();details['jacobian']=matrix.tolist()
                    details['jacobian_weighted_velocity']=self.to_host(jacobian_point).tolist()
            raise TrialFailure(message,details)
        def trials(values,base=None):
            nonlocal last_trial
            values=values.reshape(-1,count);velocity=xp.broadcast_to(original,(len(values),len(original))).copy()
            velocity[:,self.dynamic]=values/self.active_weights
            result=self.evaluate(velocity,h,gravity,_jacobian_base=base if self.pipeline in ('parallel','local-jacobian') else None)
            last_trial=result,values,velocity.reshape(-1,self.n,6)
            return result,result['residual'].reshape(len(values),-1)[:,self.dynamic],velocity.reshape(-1,self.n,6)
        if self.newton_strategy=='ranked':
            # Numerical starting guesses only: contract the candidate midpoint
            # motion toward zero. No accepted velocity or history is assigned.
            # A stiff implicit root can be close to that limit even when the
            # original velocity guess enters a different softening branch.
            guesses=xp.asarray([2*f-1 for f in fractions])[:,None]*y[None]
            probe,r,_=trials(guesses)
            scores=xp.where(probe['faults']==0,xp.linalg.norm(r,axis=1),xp.inf)
            host_scores=self.to_host(scores);start_scores=[float(x) if np.isfinite(x) else None for x in host_scores]
            order=np.argsort(host_scores,kind='stable').tolist()
            if start_scores[order[0]] is None:refuse('All Newton starting trials refused')
            y=guesses[order[0]].copy()
        for iteration in range(maximum_iterations):
            out,residual,velocity=trials(y)
            if int(out['faults'][0]):refuse('Coupled trial fault '+str(int(out['faults'][0])))
            norm=float(xp.linalg.norm(residual[0]))
            row=dict(iteration=iteration,starting_fraction=fractions[order[start_index]],equation_residual=norm,line_search=[]);trace.append(row)
            if norm<=tolerance:
                self.last_solve=dict(strategy=self.newton_strategy,starting_scores=start_scores,
                    attempted_fractions=[fractions[i] for i in order[:start_index+1]],converged_fraction=fractions[order[start_index]],iteration_evaluations=len(trace))
                return {k:out[k][0].copy() for k in ('poses','residual','history','forces','ledger','faults')},velocity[0].copy(),iteration,norm
            # Energy-weighted finite cells have sub-micrometre cohesive ranges.
            # A 1e-7 sqrt(J) perturbation crossed compression/damage branches
            # and produced a secant matrix rather than the local Jacobian.
            # Contact now retains origin/displacement low parts instead of
            # rounding the compression into world coordinates. The previous
            # 1e-16 weighted displacement floor can now create a nonlocal
            # secant at microsecond steps. Retain the 1e-12 velocity scale and
            # a finer 1e-17 displacement floor for finite-frame arithmetic;
            # independent roots and refinement controls retain the tolerance.
            # Midpoint translation/turn changes by h*delta/2. This is private
            # numerical differentiation, never an accepted velocity assignment.
            epsilon=xp.maximum(1e-12*xp.maximum(1.,abs(y)),2e-17/h)
            perturbed=xp.repeat(y[None],2*count,axis=0)
            ids=xp.arange(count);perturbed[ids,ids]+=epsilon;perturbed[count+ids,ids]-=epsilon
            diff,r,_=trials(perturbed,base=out)
            if bool(xp.any(diff['faults'])):refuse('Jacobian trial crosses a geometry/numeric boundary')
            jacobian=((r[:count]-r[count:])/(2*epsilon[:,None])).T
            jacobian_point=y
            if self.linear is not None:
                delta,status=self.linear.enqueue(jacobian,residual[0])
                # The nonlinear loop is still host controlled. One combined
                # observation replaces two LU status reads and a finite scan.
                # A future resident controller consumes this device status.
                reason,rf,rs=self.to_host(status)
                row['linear_status']=dict(reason=int(reason),factor_info=int(rf),solve_info=int(rs))
                if reason==2 or reason==4:refuse('Singular coupled Newton Jacobian')
                if reason:refuse('Nonfinite coupled Newton direction')
            else:
                try:
                    delta=self.solve_linear(jacobian,residual[0])
                except np.linalg.LinAlgError:refuse('Singular coupled Newton Jacobian')
                if not bool(xp.isfinite(delta).all()):refuse('Nonfinite coupled Newton direction')
            accepted=False
            scales=(1.,.5,.25,.125,.0625,.03125,.015625,.0078125)
            if self.line_search=='batch-tail':
                # Independent PRIVATE probes of the same Newton direction.
                # Their material input/history/dt are identical. Retain the
                # first accepted scale in the original order; later probes
                # never change accepted physics or manufacture another root.
                # Preserve the common full-step fast path. Only when it fails
                # do the remaining seven independent candidates run together.
                for group in (scales[:1],scales[1:]):
                    candidates=y[None]-xp.asarray(group)[:,None]*delta[None]
                    probe,r,v=trials(candidates)
                    # Identical vector reduction for every row, rather than
                    # an axis reduction with a different arithmetic ordering.
                    norms=xp.stack([xp.linalg.norm(r[i]) for i in range(len(group))])
                    # One bounded host observation. Fault codes fit exactly in
                    # FP64; physical arrays remain resident and authoritative.
                    host_faults,host_norms=self.to_host(xp.stack((probe['faults'],norms)))
                    for i,scale in enumerate(group):
                        fault=int(host_faults[i]);probe_norm=float(host_norms[i]) if fault==0 else None
                        row['line_search'].append(dict(scale=scale,fault=fault,equation_residual=probe_norm))
                        # Retain only the last CONSIDERED failure candidate,
                        # just as serial evaluation, not seven unused states.
                        last_trial={k:probe[k][i:i+1] for k in ('poses','residual','history','forces','ledger','faults')},candidates[i:i+1],v[i:i+1]
                        if fault==0 and probe_norm<norm*(1-1e-4*scale):y=candidates[i].copy();accepted=True;break
                    if accepted:break
            else:
                for scale in scales:
                    candidate=y-scale*delta;probe,r,_=trials(candidate)
                    fault=int(probe['faults'][0]);probe_norm=float(xp.linalg.norm(r[0])) if fault==0 else None
                    row['line_search'].append(dict(scale=scale,fault=fault,equation_residual=probe_norm))
                    if fault==0 and probe_norm<norm*(1-1e-4*scale):y=candidate;accepted=True;break
            if not accepted:
                # All starts share the SAME total 24-iteration limit. Restart
                # only the private nonlinear iterate; the physical input,
                # constitutive history, equation and admission gates are fixed.
                if guesses is not None and iteration+1<maximum_iterations and start_index+1<len(order) and start_scores[order[start_index+1]] is not None:
                    start_index+=1;y=guesses[order[start_index]].copy();continue
                refuse('Coupled Newton line search did not reduce the equation residual')
            if iteration+1==maximum_iterations and probe_norm<=tolerance:
                # The final permitted update already evaluated the complete
                # nonlinear trial and passed the SAME convergence threshold.
                # Do not require an extra outer iteration merely to observe it.
                # This advances no extra update and changes no physical gate.
                self.last_solve=dict(strategy=self.newton_strategy,starting_scores=start_scores,
                    attempted_fractions=[fractions[i] for i in order[:start_index+1]],
                    converged_fraction=fractions[order[start_index]],iteration_evaluations=len(trace),
                    converged_on_final_update=True)
                final,_,final_velocity=last_trial
                return {k:final[k][0].copy() for k in ('poses','residual','history','forces','ledger','faults')},final_velocity[0].copy(),iteration+1,probe_norm
        refuse('Coupled Newton iteration budget exceeded')
