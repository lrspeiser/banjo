export class SessionExpiredError extends Error {}

export async function requestScene(command,{endpoint='/api/gpu',fetcher=fetch}={}) {
  const response=await fetcher(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
  const reply=await response.json();
  if(response.status===410&&reply.code==='session_expired')throw new SessionExpiredError(reply.error);
  if(!response.ok)throw Error(reply.error);
  return reply;
}

// Recovery creates a fresh scene; never replay an interrupted action or batch.
export async function runSceneSteps({session,count,onState,onExpired,shouldStop=()=>false,getBatchSize=()=>1,request=requestScene}) {
  if(!Number.isInteger(count)||count<1||count>3840)throw RangeError('Invalid step count');
  try {
    for(let i=0;i<count&&!shouldStop();) {
      const proposed=getBatchSize();
      if(!Number.isInteger(proposed)||proposed<1||proposed>16)throw RangeError('Invalid physics batch');
      const steps=Math.min(proposed,count-i);
      onState(await request({op:'advance',session,steps}));i+=steps;
    }
    return true;
  } catch(error) {
    if(!(error instanceof SessionExpiredError))throw error;
    await onExpired();
    return false;
  }
}
