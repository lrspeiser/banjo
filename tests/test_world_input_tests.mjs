import assert from 'node:assert/strict';
import {test} from 'node:test';
import {worldGesture,moveWorldGesture,finishWorldGesture,worldUnavailable,connectedWorldParts} from '../client/experiments/world-input.js';
import {impactRows} from '../client/experiments/world-impact.js';

const pointer=(x,y,type='touch',id=1)=>({clientX:x,clientY:y,pointerType:type,pointerId:id});
test('finger drift and moving native geometry retain the original selected body and point',()=>{
    const observed={instance:'unfamiliar-tool-component',point:[.65,.7,.2]};
    const gesture=worldGesture(pointer(200,100),observed);
    observed.point[0]=90; // next native observation must not mutate the press
    moveWorldGesture(gesture,pointer(210,104));
    assert.deepEqual(finishWorldGesture(gesture,pointer(210,104)),{
        instance:'unfamiliar-tool-component',point:[.65,.7,.2]});
});
test('orbit gestures and another finger cannot become pickup commands',()=>{
    const gesture=worldGesture(pointer(200,100),{instance:'tool',point:[0,0,0]});
    assert.equal(moveWorldGesture(gesture,pointer(400,400,'touch',2)),false);
    assert.equal(finishWorldGesture(gesture,pointer(200,100,'touch',2)),null);
    moveWorldGesture(gesture,pointer(225,100));
    moveWorldGesture(gesture,pointer(200,100));
    assert.equal(finishWorldGesture(gesture,pointer(200,100)),null);
    assert.equal(finishWorldGesture(null,pointer(200,100)),null);
});
test('expired, stopped and exhausted sessions require recovery; ordinary refusals do not',()=>{
    for(const reason of ['expired','stopped','input_budget'])assert.equal(worldUnavailable(reason),true);
    for(const reason of ['out_of_reach','target_changed',undefined])assert.equal(worldUnavailable(reason),false);
});
test('hover selects the whole fixed assembly from any component, excluding detached or hinged neighbours',()=>{
    const state={bodies:['edge','shaft','grip','stand','wheel'].map(name=>({name})),joints:[
        {a:'edge',b:'shaft',kind:'fixing',attached:true},
        {a:'shaft',b:'grip',kind:'fixing',attached:true},
        {a:'shaft',b:'stand',kind:'fixing',attached:false},
        {a:'shaft',b:'wheel',kind:'hinge',attached:true}]};
    assert.deepEqual(new Set(connectedWorldParts('edge',state)),new Set(['edge','shaft','grip']));
    assert.deepEqual(new Set(connectedWorldParts('grip',state)),new Set(['edge','shaft','grip']));
    assert.deepEqual(connectedWorldParts('missing',state),[]);
});
test('impact presentation distinguishes admission, actual contact and unavailable fracture or energy',()=>{
    const report={requested_target_m:[.3,.12,.3],status:'completed',expectation:{native_preview:{admitted:true}},actual:{
        physical_hit:{contacted:true,target:'ground-slab',contact_part:'head',obstruction:'',target_m:[.3,.12,.3],
            contact_speed_m_s:1.92,peak_tip_speed_m_s:2.8,swing_rotation_rad:.8,target_displacement_m:[.01,0,0],
            hand_work_j:-.31,started_s:1,ended_s:1.2,phase:'ended'},observed_new_bodies:[],observed_removed_bodies:[],observed_body_mass_change_kg:0}};
    const rows=Object.fromEntries(impactRows(report));
    assert.equal(rows['Actual result'],'Target contacted');assert.equal(rows['Contact speed'],'1.920 m/s');
    assert.equal(rows['Signed hand work'],'-0.310 J');assert.equal(rows['Target travel'],'1.000 cm');
    assert.match(rows['Engine admission'],/not guaranteed/);assert.match(rows['Cracks / broken bonds'],/Unavailable/);
    assert.match(rows['Contact impulse / full energy balance'],/not qualified/);
    report.actual=null;report.status='refused';report.command_outcome={reason:'not_holding'};
    const refused=Object.fromEntries(impactRows(report));assert.equal(refused['Actual result'],'not_holding');
    assert.equal(refused['Signed hand work'],'Unavailable');assert.equal(refused['New bodies observed'],'Unavailable');
});
