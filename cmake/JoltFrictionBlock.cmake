# Opt-in coupled disk/interval friction on the existing observed native path.
# Dependency sources stay unchanged; shared class layouts are build-local.
function(banjo_jolt_friction_block target source_dir)
    set(overlay "${CMAKE_CURRENT_BINARY_DIR}/jolt-force-observation-overlay")
    file(READ "${overlay}/Jolt/Physics/Collision/ContactListener.h" settings)
    string(REPLACE "bool mBanjoMidpointContact = false;" "bool mBanjoMidpointContact = false;\n\tbool mBanjoBlockFriction = false;" settings "${settings}")
    file(CONFIGURE OUTPUT "${overlay}/Jolt/Physics/Collision/ContactListener.h" CONTENT "${settings}" @ONLY)
    file(READ "${source_dir}/Jolt/Physics/Constraints/ContactConstraintManager.h" header)
    set(marker "\t\tfloat\t\t\t\t\tmCombinedFriction;")
    string(FIND "${header}" "${marker}" pos)
    if(pos LESS 0)
        message(FATAL_ERROR "Pinned Jolt contact block layout changed")
    endif()
    string(REPLACE "${marker}" "\t\tbool mBanjoBlockFriction;\n\t\tdouble mBanjoFrictionK[9];\n\t\tfloat mBanjoTwistLength;\n${marker}" header "${header}")
    file(CONFIGURE OUTPUT "${overlay}/Jolt/Physics/Constraints/ContactConstraintManager.h" CONTENT "${header}" @ONLY)
    file(MAKE_DIRECTORY "${overlay}/Jolt/Physics/Constraints/ConstraintPart")
    # The gradient getters use the same native Jacobian/bias expressions, with
    # no subtraction of nearly equal accumulated float impulses.
    foreach(part ContactConstraintPart AngularFrictionConstraintPart)
        file(READ "${source_dir}/Jolt/Physics/Constraints/ConstraintPart/${part}.h" part_header)
        if(part STREQUAL ContactConstraintPart)
            set(start "\tJPH_INLINE float\t\t\tSolveVelocityConstraintGetTotalLambda(")
            set(end "\t/// Part 2 of AxisConstraint::SolveVelocityConstraint")
            string(FIND "${part_header}" "${start}" begin)
            string(FIND "${part_header}" "${end}" finish)
            if(begin LESS 0 OR finish LESS begin)
                message(FATAL_ERROR "Pinned Jolt tangent gradient changed")
            endif()
            math(EXPR count "${finish}-${begin}")
            string(SUBSTRING "${part_header}" ${begin} ${count} getter)
            string(REPLACE "SolveVelocityConstraintGetTotalLambda" "GetBanjoGradient" getter "${getter}")
            string(REPLACE "return this->mTotalLambda + lambda;" "return mBias - jv;" getter "${getter}")
            string(REPLACE "float lambda = this->mEffectiveMass * (jv - mBias);" "" getter "${getter}")
        else()
            set(getter [=[
    float GetBanjoGradient(Vec3Arg w1, Vec3Arg w2, Vec3Arg axis) const {
        float jv=0;
        if constexpr(Type1 != EMotionType::Static) jv+=axis.Dot(w1);
        if constexpr(Type2 != EMotionType::Static) jv-=axis.Dot(w2);
        return mBias-jv;
    }
    bool ApplyBanjoTotalLambda(Vec3 &w1, Vec3 &w2, float total) {
        float delta=total-this->mTotalLambda;this->mTotalLambda=total;
        return ApplyVelocityStep(w1,w2,delta);
    }
]=])
        endif()
        if(part STREQUAL ContactConstraintPart)
            string(REPLACE "${start}" "${getter}${start}" part_header "${part_header}")
        else()
            string(REPLACE "public:" "public:\n${getter}" part_header "${part_header}")
        endif()
        file(CONFIGURE OUTPUT "${overlay}/Jolt/Physics/Constraints/ConstraintPart/${part}.h" CONTENT "${part_header}" @ONLY)
    endforeach()
    file(READ "${overlay}/Jolt/Physics/Constraints/ContactConstraintManager.cpp" implementation)
    set(create "constraint->mCombinedFriction = inSettings.mCombinedFriction;")
    string(FIND "${implementation}" "${create}" pos)
    if(pos LESS 0)
        message(FATAL_ERROR "Pinned Jolt contact creation changed")
    endif()
    string(REPLACE "${create}" "${create}\n\tconstraint->mBanjoBlockFriction = inSettings.mBanjoBlockFriction;" implementation "${implementation}")
    set(setup [=[
        if(mBanjoBlockFriction) {
            mBanjoTwistLength=1.0f;
            if(mNumContactPoints>1) {
                mBanjoTwistLength=0;
                for(uint32 i=0;i<mNumContactPoints;++i)
                    mBanjoTwistLength=max(mBanjoTwistLength,mContactPoints[i].mDistanceToFrictionCenter);
                if(mBanjoTwistLength<=0)mBanjoTwistLength=1.0f;
            }
            const Vec3 linear[3]={inWorldSpaceTangent1,inWorldSpaceTangent2,Vec3::sZero()};
            const Vec3 spin1[3]={r1.Cross(linear[0]),r1.Cross(linear[1]),mBanjoTwistLength*inWorldSpaceNormal};
            const Vec3 spin2[3]={r2.Cross(linear[0]),r2.Cross(linear[1]),mBanjoTwistLength*inWorldSpaceNormal};
            for(uint32 i=0;i<3;++i)for(uint32 j=i;j<3;++j) {
                double value=0;
                if constexpr(Type1==EMotionType::Dynamic)
                    value+=double(inInvM1)*linear[i].Dot(linear[j])+spin1[i].Dot(inInvI1.Multiply3x3(spin1[j]));
                if constexpr(Type2==EMotionType::Dynamic)
                    value+=double(inInvM2)*linear[i].Dot(linear[j])+spin2[i].Dot(inInvI2.Multiply3x3(spin2[j]));
                mBanjoFrictionK[3*i+j]=mBanjoFrictionK[3*j+i]=value;
            }
            if(!mAngularFrictionConstraint.IsActive()) {
                mBanjoFrictionK[2]=mBanjoFrictionK[5]=mBanjoFrictionK[6]=mBanjoFrictionK[7]=0;
                mBanjoFrictionK[8]=1;
            }
        }
]=])
    set(setup_marker "\t\t\tmAngularFrictionConstraint.Deactivate();\n\t}\n\telse")
    string(FIND "${implementation}" "${setup_marker}" pos)
    if(pos LESS 0)
        message(FATAL_ERROR "Pinned Jolt friction initialization changed")
    endif()
    string(REPLACE "${setup_marker}" "\t\t\tmAngularFrictionConstraint.Deactivate();\n${setup}\t}\n\telse" implementation "${implementation}")
    set(solve [=[
    Vec3 ws_normal = constraint.GetWorldSpaceNormal();
    if(constraint.mBanjoBlockFriction && linear_friction_active) {
        const double length=constraint.mBanjoTwistLength;
        std::array<double,9> k;for(unsigned i=0;i<9;++i)k[i]=constraint.mBanjoFrictionK[i];
        const std::array<double,3> current={constraint.mFrictionConstraint1.GetTotalLambda(),constraint.mFrictionConstraint2.GetTotalLambda(),angular_friction_active?constraint.mAngularFrictionConstraint.GetTotalLambda()/length:0};
        std::array<double,3> q={constraint.mFrictionConstraint1.GetBanjoGradient(linear_velocity1,angular_velocity1,linear_velocity2,angular_velocity2,t1),constraint.mFrictionConstraint2.GetBanjoGradient(linear_velocity1,angular_velocity1,linear_velocity2,angular_velocity2,t2),angular_friction_active?length*constraint.mAngularFrictionConstraint.GetBanjoGradient(angular_velocity1,angular_velocity2,ws_normal):0};
        for(unsigned i=0;i<3;++i)for(unsigned j=0;j<3;++j)q[i]-=k[3*i+j]*current[j];
        const auto p=banjo::solveContactFrictionBlock(k,q,max_linear_lambda,angular_friction_active?max_angular_lambda/length:0);
        any_impulse_applied |= constraint.mFrictionConstraint1.SolveVelocityConstraintApplyLambda(linear_velocity1,angular_velocity1,linear_velocity2,angular_velocity2,constraint.mInvMass1,constraint.mInvMass2,t1,float(p[0]));
        any_impulse_applied |= constraint.mFrictionConstraint2.SolveVelocityConstraintApplyLambda(linear_velocity1,angular_velocity1,linear_velocity2,angular_velocity2,constraint.mInvMass1,constraint.mInvMass2,t2,float(p[1]));
        if(angular_friction_active)any_impulse_applied |= constraint.mAngularFrictionConstraint.ApplyBanjoTotalLambda(angular_velocity1,angular_velocity2,float(p[2]*length));
    } else {
]=])
    set(solve_marker "\t// First apply friction constraint (non-penetration is more important than friction)")
    set(normal_marker "\t// Then apply all non-penetration constraints")
    string(FIND "${implementation}" "${solve_marker}" pos)
    string(FIND "${implementation}" "${normal_marker}" pos2)
    if(pos LESS 0 OR pos2 LESS pos)
        message(FATAL_ERROR "Pinned Jolt friction iteration changed")
    endif()
    string(REPLACE "\tVec3 ws_normal = constraint.GetWorldSpaceNormal();\n\tif (angular_friction_active" "\tif (angular_friction_active" implementation "${implementation}")
    string(REPLACE "${solve_marker}" "${solve}${solve_marker}" implementation "${implementation}")
    string(REPLACE "${normal_marker}" "\t}\n${normal_marker}" implementation "${implementation}")
    set(implementation "#include \"physics/ContactFrictionBlock.hpp\"\n${implementation}")
    file(CONFIGURE OUTPUT "${overlay}/Jolt/Physics/Constraints/ContactConstraintManager.cpp" CONTENT "${implementation}" @ONLY)
endfunction()
