// Keep one pointer's original intention while the native world keeps moving.
// This module chooses intentions only; native admission still decides custody.
export function worldGesture(event, selection) {
    return {pointerId:event.pointerId,x:event.clientX,y:event.clientY,
        lastX:event.clientX,lastY:event.clientY,moved:false,
        threshold:event.pointerType==='touch'?16:8,
        selection:selection?{...selection,point:[...selection.point]}:null};
}
export function moveWorldGesture(gesture,event) {
    if(!gesture || event.pointerId!==gesture.pointerId)return false;
    if(Math.hypot(event.clientX-gesture.x,event.clientY-gesture.y)>gesture.threshold)gesture.moved=true;
    return true;
}
export function finishWorldGesture(gesture,event) {
    moveWorldGesture(gesture,event);
    return gesture && event.pointerId===gesture.pointerId && !gesture.moved ? gesture.selection : null;
}
export function worldUnavailable(code) {
    return ['expired','stopped','input_budget'].includes(code);
}
export function connectedWorldParts(instance,state) {
    const present=new Set(state.bodies.map(body=>body.name));
    const parts=new Set(present.has(instance)?[instance]:[]);
    for(const name of parts)for(const joint of state.joints || []){
        if(joint.kind!=='fixing' || !joint.attached || joint.away || joint.comes_off_n>0)continue;
        const other=joint.a===name?joint.b:joint.b===name?joint.a:null;
        if(present.has(other))parts.add(other);
    }
    return [...parts];
}
