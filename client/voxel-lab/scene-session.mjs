export class SessionExpiredError extends Error {}

export async function requestScene(command,{endpoint='/api/gpu',fetcher=fetch}={}) {
  const response=await fetcher(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(command)});
  const reply=await response.json();
  if(response.status===410&&reply.code==='session_expired')throw new SessionExpiredError(reply.error);
  if(!response.ok)throw Error(reply.error);
  return reply;
}

// Recovery creates a fresh scene; never replay an interrupted action or batch.
export async function runSceneSteps({session,count,onState,onExpired,shouldStop=()=>false,request=requestScene}) {
  if(!Number.isInteger(count)||count<1||count>3840)throw RangeError('Invalid step count');
  try {
    for(let i=0;i<count&&!shouldStop();i++)onState(await request({op:'advance',session,steps:1}));
    return true;
  } catch(error) {
    if(!(error instanceof SessionExpiredError))throw error;
    await onExpired();
    return false;
  }
}
