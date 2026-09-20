"""The lab assistant edits declarations; it never executes model-generated code."""
import json
import threading
from urllib import request, error
import physics_trials

_LOCK = threading.Lock()
SYSTEM = """You edit bounded Banjo physics experiment recipes. Return JSON with exactly
document and explanation. The document uses banjo.physics-trial.v1 from the supplied
catalog/example. Keep geometry, checks and settings unchanged unless the user asks
to change them. Never weaken a check just to pass it. Body dimensions, positions and
velocities are initial conditions. wield/move apply a force-limited grip; there is
no teleport, set-speed or game-specific magic. Use only listed native operations.
Connections are declared before time advances. Geometry changes are lab authoring,
not physically paid manufacture. Do not invent unsupported physics. For an
unsupported request return document:null with an explanation. No code or markdown."""
def propose(app, body):
    physics_trials.obj(body, {"message","document"}, {"message","document"}, "plan")
    message=body["message"]
    if not isinstance(message,str) or not 1<=len(message)<=2000: raise ValueError("Use a message of 1..2000 characters")
    document,_=physics_trials.validate(body["document"])
    if not getattr(app,"api_key",None): raise ValueError("Configure the local lab assistant key")
    if not _LOCK.acquire(blocking=False): raise ValueError("The lab assistant is already editing a recipe")
    try:
        payload={"model":app.model,"store":False,"max_output_tokens":6000,
                 "reasoning":{"effort":"low"},"text":{"format":{"type":"json_object"}},
                 "input":[{"role":"system","content":SYSTEM},{"role":"user","content":json.dumps({
                     "message":message,"document":document,"catalog":physics_trials.catalog()})}]}
        req=request.Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode(),
                            headers={"Content-Type":"application/json","Authorization":"Bearer "+app.api_key},method="POST")
        try:
            with request.urlopen(req,timeout=90) as response: answer=json.load(response)
        except error.HTTPError as exc: raise ValueError("Lab assistant request failed (HTTP "+str(exc.code)+")") from None
        if answer.get("status") not in (None,"completed"): raise ValueError("The assistant did not finish the recipe")
        texts=[c.get("text","") for o in answer.get("output",[]) for c in o.get("content",[]) if c.get("type")=="output_text"]
        proposed=json.loads("".join(texts))
        physics_trials.obj(proposed, {"document","explanation"}, {"document","explanation"}, "assistant proposal")
        if not isinstance(proposed["explanation"],str): raise ValueError("Missing assistant explanation")
        if proposed["document"] is not None:
            proposed["document"],_=physics_trials.validate(proposed["document"])
        return {**proposed,"model":app.model,"response_id":answer.get("id"),"usage":answer.get("usage",{}),
                "executed":False}
    except (error.URLError, TimeoutError) as exc:
        raise ValueError("The lab assistant could not be reached") from None
    finally: _LOCK.release()
