"""Bounded autonomous guests using the same authenticated HTTP actions as people.

Model choices are plans, not success evidence. The native game, market and
personal goal evaluator decide what happened. No AI token is sent to viewers.
"""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import math
import threading
import time
from typing import Any
from urllib import request, error
import uuid

import inventory_room
import ai_actions
import player_world
import rover_brain
import world_access

MAX_DECISIONS = 64
MAX_AGENTS = 4
CADENCE_S = .8


class Manager:
    def __init__(self, app: Any, port: int, keep: Any, journal: Any, registry: Any):
        self.app, self.port, self.keep, self.journal, self.registry = app, port, keep, journal, registry
        self.lock = threading.RLock()
        self.workers: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.decider_factory = lambda: rover_brain.OpenAIDecider(app.api_key, app.model)
        self.cadence_s = CADENCE_S
        # Restart never silently resumes paid calls. Tokens, bags, journals,
        # evidence and history survive; an owner explicitly resumes play.
        for profile in player_world.records(app).values():
            ai = profile.get("ai")
            if isinstance(ai, dict) and ai.get("status") in ("running", "thinking", "walking"):
                profile["ai"] = {**ai, "status": "paused", "message": "Paused after server restart"}

    def _profile(self, ident: Any) -> dict[str, Any]:
        profile = player_world.records(self.app).get(str(ident))
        if profile is None or not isinstance(profile.get("ai"), dict):
            raise ValueError("This world has no AI character with that id")
        return profile

    def _save(self, profile: dict[str, Any], **updates: Any) -> None:
        with world_access.gate(self.app).enter(exclusive=True), world_access.state_lock(self.app):
            with player_world.lock_of(self.app):
                worker = self.workers.get(profile["id"])
                if worker and worker[1].is_set() and updates.get("status") in ("running", "thinking", "walking"):
                    updates.pop("status", None)
                    updates.pop("message", None)
                profile["ai"] = {**profile["ai"], **updates}
            if self.app.live.session and self.app.live_holder == "world":
                if not self.keep(self.app, "AI character checkpoint"):
                    raise ValueError("The AI character awaits a durable world save")
            elif not self.app.store.save(self.app.room):
                raise ValueError("The AI character could not be saved")

    def _post(self, profile: dict[str, Any], path: str, body: dict[str, Any], cookie: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "X-Banjo-Token": self.app.csrf_token,
                   "X-Banjo-World": self.app.world_id, "X-Banjo-Player": profile["token"]}
        if cookie: headers["Cookie"] = cookie
        req = request.Request(f"http://127.0.0.1:{self.port}" + path, method="POST", headers=headers,
                              data=json.dumps(body, allow_nan=False).encode())
        try:
            with request.urlopen(req, timeout=30) as response: return json.load(response)
        except error.HTTPError as exc:
            try: message = json.load(exc).get("error", f"Game refused HTTP {exc.code}")
            except (ValueError, OSError): message = f"Game refused HTTP {exc.code}"
            raise ValueError(message) from None

    def handle(self, owner: str, body: Any, cookie: str = "") -> dict[str, Any]:
        if not isinstance(body, dict) or set(body) - {"action", "id", "name", "mode", "full"}:
            raise ValueError("Expected an AI character action")
        action = body.get("action", "list")
        if action == "list":
            with player_world.lock_of(self.app):
                profiles = list(player_world.records(self.app).values())
            return {"schema": "banjo.ai-players.v1", "model_available": bool(self.app.api_key),
                    "characters": [self.summary(p, owner) for p in profiles
                                   if isinstance(p.get("ai"), dict)]}
        if "full" in body and not isinstance(body["full"], bool): raise ValueError("full must be true or false")
        if action == "watch": return self.watch(self._profile(body.get("id")), owner, body.get("full", False))
        if action not in ("start", "pause"): raise ValueError("Use list, start, pause or watch")
        with self.lock:
            if body.get("id"):
                profile = self._profile(body["id"])
                if profile["ai"]["controller"] != owner:
                    raise ValueError("Only this character's creator can start or pause it")
            else:
                if action != "start": raise ValueError("Name the character to pause")
                mode = body.get("mode", "openai")
                if mode not in ("openai", "reference"): raise ValueError("Use OpenAI or reference mode")
                if mode == "openai" and not self.app.api_key:
                    raise ValueError("Configure OPENAI_API_KEY to start an AI character, or select Reference bot")
                with player_world.lock_of(self.app):
                    count = sum(bool(p.get("ai")) for p in player_world.records(self.app).values())
                if count >= MAX_AGENTS:
                    raise ValueError("This world supports four AI characters")
                # Joining publishes host accounts beside the last native save.
                # Checkpoint the advancing world first, as human joining does,
                # and exclude clock/receiving changes until the profile is saved.
                with world_access.gate(self.app).enter(exclusive=True), world_access.state_lock(self.app):
                    if self.app.live.session and self.app.live_holder == "world":
                        if not self.keep(self.app,"before joining an AI character"):
                            raise ValueError("The current world could not be saved; retry starting after saving recovers")
                    joined = player_world.join(self.app, name=body.get("name") or "Banjo explorer")
                    profile = player_world.records(self.app)[joined["id"]]
                    profile["ai"] = {"controller": owner, "mode": mode, "status": "paused", "decisions": 0,
                                     "history": [], "memory": {}, "message": "Ready to play the available goal chains"}
                    self._save(profile)
            old = self.workers.get(profile["id"])
            if action == "pause":
                if old: old[1].set()
                # An in-flight model call may finish, but its choice is checked
                # against the stop event before any game action is executed.
                self._save(profile, status="paused", message="Paused by its creator")
            elif not old or not old[0].is_alive():
                if profile["ai"]["mode"] == "openai" and not self.app.api_key:
                    raise ValueError("The configured model is unavailable")
                self._save(profile, status="running", decisions=0, message="Following the next supported goal")
                stop = threading.Event()
                worker = threading.Thread(target=self._run, args=(profile, stop, cookie), daemon=True,
                                          name=f"banjo-ai-{profile['id'][:8]}")
                self.workers[profile["id"]] = (worker, stop)
                worker.start()
            elif old[1].is_set():
                raise ValueError("The character is finishing its current request; resume in a moment")
            return self.summary(profile, owner)

    def summary(self, profile: dict[str, Any], owner: str) -> dict[str, Any]:
        ai = profile["ai"]
        return {"id": profile["id"], "name": profile["name"], "pose": deepcopy(profile.get("pose")),
                "mode": ai["mode"], "status": ai["status"], "message": ai.get("message"),
                "decisions": ai["decisions"], "decision_budget": MAX_DECISIONS,
                "can_control": ai["controller"] == owner, "memory":deepcopy(ai.get('memory',{})),
                "history": deepcopy(ai.get("history", [])[-20:])}

    def watch(self, profile: dict[str, Any], owner: str, full: bool = False) -> dict[str, Any]:
        if not self.app.live.session or self.app.live_holder != "world":
            raise ValueError("Start the character before watching its world")
        import starter_goals
        import progression
        ident = profile["id"]
        state = (self.app.live.rejoin(self.app, shared=True) if full else
                 self.app.live.act({"session": self.app.live.session.id, "op": "poses", "actor": ident}))
        if state is None: raise ValueError("The character's world could not be read")
        self.app.brains.settle(state)
        state['brains']=self.app.brains.summaries()
        state["session"] = self.app.live.session.id
        state["scene"] = self.app.room.scene
        state["inventory"] = inventory_room.shown(self.app, ident)
        state["players"] = player_world.visible(self.app)
        player_world.personalize_hand(state, ident)
        state["notebook"] = progression.notebook(self.journal(self.app, ident), self.registry())
        goals = starter_goals.view(self.app, ident, {'chain':'active'})
        return {"character": self.summary(profile, owner), "goals": goals,
                "skills": progression.tech_tree(self.journal(self.app, ident), self.registry()), "state": state}

    def _person(self, profile, cookie, aim=None, eyes=None):
        pose=profile.get('pose') or {}
        eyes=eyes or pose.get('eyes_m') or [0,1.62,3]
        sid=self.app.live.session.id
        survey=self._post(profile,'/api/live/act',{'session':sid,'op':'survey','at':[eyes[0],eyes[2]]},cookie)['survey']
        if not survey.get('on_the_ground'):raise ValueError('The selected position is outside native terrain')
        ground=survey['ground_m']; eyes=[eyes[0],ground+1.62,eyes[2]]
        ray=[aim[k]-eyes[k] for k in range(3)] if aim else pose.get('look_direction') or [1,-1.5,0]
        horizontal=math.hypot(ray[0],ray[2])
        facing=[ray[0]/horizontal,0,ray[2]/horizontal] if horizontal>.001 else [1,0,0]
        return {'standing_m':[eyes[0],ground,eyes[2]],'eyes_m':eyes,'facing':facing,'look_direction':ray,
                **({'aim_m':aim} if aim else {})}

    def _move(self, profile, stop, cookie, aim, stand_off_m=1.2):
        self._save(profile,status='walking',message='Walking toward the selected target')
        start=(profile.get('pose') or {}).get('eyes_m',[0,1.62,3])
        sid=self.app.live.session.id
        def survey(x,z):
            return self._post(profile,'/api/live/act',{'session':sid,'op':'survey','at':[x,z]},cookie)['survey']
        route=ai_actions.walking_route(start,aim,stand_off_m,survey,stop.is_set)
        for x,y,z in route:
            if stop.is_set():return
            surveyed=survey(x,z)
            if not surveyed.get('on_the_ground'):raise ValueError('The route leaves native terrain')
            if (surveyed.get('water') or {}).get('depth_m',0)>.2:raise ValueError('The walking route enters deep water')
            y=surveyed['ground_m']
            dx,dz=aim[0]-x,aim[2]-z;length=math.hypot(dx,dz)
            direction=[dx/length,dz/length] if length>.01 else [1,0]
            person={'standing_m':[x,y,z],'eyes_m':[x,y+1.62,z],'facing':[direction[0],0,direction[1]],
                    'look_direction':[aim[0]-x,aim[1]-y-1.62,aim[2]-z]}
            self._post(profile,'/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':48,'person':person},cookie)
            stop.wait(.2)
        if not stop.is_set():self._save(profile,status='running',message='Near the selected target')

    def _observe(self,profile,cookie):
        goals=self._post(profile,'/api/workshop/goals',{'chain':'active'},cookie)
        opened=self._post(profile,'/api/world/open',{},cookie)
        market=self._post(profile,'/api/workshop/market',{},cookie)
        skills=self._post(profile,'/api/workshop/skills',{},cookie)['techniques']
        inventory=self._post(profile,'/api/world/inventory/shown',{'session':opened['session']},cookie)
        req=ai_actions.requirement_of(goals) or {}
        book=(self._post(profile,'/api/workshop/recipes',{},cookie)
              if req.get('kind') in ('admitted-recipe','funded-box-surface','personal-test',
                                    'personal-stock','funded-ground-tool','own-tool-test')
                 or profile['ai'].get('memory',{}).get('fabrication_build') else {})
        funding=(self._post(profile,'/api/world/fabrication/state',
                 {'session':opened['session'],'scene':opened['scene']},cookie)
                 if profile['ai'].get('memory',{}).get('fabrication_build') else None)
        return {'goals':goals,'next_goal':goals['next_goal'],'market':market,'balance_j':market['balance_j'],
                'skills':skills,'tech_tree':skills,'inventory':inventory,'recipes':book.get('templates',[]),
                'stockpiles':book.get('stockpiles',[]),
                'native':opened,'pose':deepcopy(profile.get('pose')),'fabrication':funding}

    def _run(self,profile,stop,cookie):
        try:
            opened=self._post(profile,'/api/world/open',{},cookie)
            if profile.get('pose') is None:
                # Report a genuine native standing pose before choosing actions.
                if opened.get('arrival_unavailable'):raise ValueError(opened['arrival_unavailable'])
                spawn=(opened.get('arrival') or {}).get('eye_m') or (opened.get('gameplay') or {}).get('spawn_m') or (opened.get('terrain') or {}).get('view',{}).get('eye_m')
                if not spawn:raise ValueError('The world offers no player arrival position')
                self._post(profile,'/api/live/act',{'session':self.app.live.session.id,'op':'step','dt':1/240,
                    'n':1,'person':self._person(profile,cookie,eyes=spawn)},cookie)
            while not stop.is_set():
                state=self._observe(profile,cookie);goals=state['goals']
                if goals['complete'] and not profile['ai'].get('memory',{}).get('fabrication_build'):
                    self._save(profile,status='complete',message='All currently declared goal chains complete; see the separate personal tech tree')
                    return
                if profile['ai']['decisions']>=MAX_DECISIONS:
                    self._save(profile,status='blocked',message=f'The {MAX_DECISIONS}-decision budget was reached; inspect progress before resuming')
                    return
                actions=ai_actions.catalog(state,profile['ai'].get('memory',{}))
                began=time.monotonic();self._save(profile,status='thinking',message='Choosing from observed player actions')
                if profile['ai']['mode']=='openai':
                    questions={'next':{'type':'choice','instructions':
                        'Play this character through the available goal chains using only offered actions. '
                        'Targets, prices and recipes in action_catalog are current observations. Compare all recipe gaps; '
                        'select actual equipment, move within reach, acquire and inspect tools, use supported ground actions, '
                        'and personally watch supported batches. An action receipt is not automatically goal or skill success. '
                        'Continue a pending reviewed build through funding, native work and placement; '
                        'a charging or work phase is not a finished product. '
                        'Never invent supplies, completion, physical laws or evidence. Stop only for a real blocker.',
                        'criteria':{a['id']:a['label'] for a in actions}}}
                    decision=self.decider_factory().ask(ai_actions.model_view(state,actions,profile['ai']['history']),questions)['next']
                    pick,confidence=decision['choice'],decision['confidence']
                else:pick,confidence=ai_actions.reference_pick(state,actions),None
                if stop.is_set():return
                action=next((a for a in actions if a['id']==pick),None)
                if action is None:raise ValueError('The planner chose an unsupported action')
                ident=uuid.uuid4().hex
                entry={'id':ident,'action':action['verb'],'choice':pick,'label':action['label'],'mode':profile['ai']['mode'],
                    'model':self.app.model if confidence is not None else None,'confidence':confidence,
                    'seconds':round(time.monotonic()-began,3),'chain':goals['chain_id'],'goal':goals['next_goal'],
                    'result':'pending','at_unix_s':time.time()}
                history=(profile['ai']['history']+[entry])[-128:]
                self._save(profile,status='running',decisions=profile['ai']['decisions']+1,history=history,message=action['label'])
                if action['verb']=='wait':
                    blockers=action['blockers'] or ['No offered action can advance the observed requirement']
                    self._save(profile,status='blocked',history=history[:-1]+[{**entry,'result':'blocked','blockers':blockers}],
                        message='; '.join(blockers)[:240]);return
                result=self._execute(profile,stop,cookie,action,state,ident)
                entry={**entry,'result':'committed' if result else 'cancelled','receipt':result}
                self._save(profile,history=history[:-1]+[entry],message=f"Action ended: {action['label']}")
                if stop.is_set():return
                stop.wait(self.cadence_s)
        except Exception as exc:
            if not stop.is_set():
                history=deepcopy(profile['ai'].get('history',[]))
                if history and history[-1]['result']=='pending':history[-1].update(result='refused',error=str(exc)[:240])
                try:self._save(profile,status='blocked',message=str(exc)[:240],history=history)
                except Exception:logging.getLogger('banjo').exception('AI character checkpoint failed')

    def _fabricated_build(self,profile,stop,cookie,action,ident,common,funding):
        """One recoverable player operation per decision; never author free output.

        Pending write arguments are saved before HTTP and replayed unchanged if
        its acknowledgement is lost. Stock comes only from this character's rack;
        existing station supplies are already funded. Work/charging use accepted
        native time. A pause/restart leaves a real workpiece to resume.
        """
        memory=deepcopy(profile['ai'].get('memory',{}))
        pending=memory.get('fabrication_build')
        if pending is None:
            pending={'candidate':deepcopy(action['recipe']['candidate']),'job_id':ident}
            memory['fabrication_build']=pending
            self._save(profile,memory=memory)
        def save():self._save(profile,memory=memory)
        def write(op,fields):
            if stop.is_set():return {}
            if 'request' not in pending:
                pending['request']={'op':op,'body':{**common,**fields,'request_id':uuid.uuid4().hex}}
                save()
            call=pending['request']
            try:reply=self._post(profile,'/api/world/fabrication/'+call['op'],call['body'],cookie)
            except ValueError as exc:
                # These explicit refusals precede spending. Unknown failures
                # retain the request, including potentially committed saves.
                if any(s in str(exc).lower() for s in ('source rack changed','native source changed',
                    'fabrication revision changed','source world changed','source room changed',
                    'plan expired','preview expired','preview belongs to a different world session',
                    'changed after preview')):
                    pending.pop('request',None)
                    if 'plan expired' in str(exc).lower():pending.pop('plan',None)
                    save()
                    return {'phase':'refresh','job_id':pending['job_id'],'reason':str(exc)}
                raise
            pending.pop('request',None)
            if call['op']=='commit':
                pending['installed']={k:reply.get(k) for k in ('root_body','mass_kg','resources_charged')}
            save()
            return {'phase':call['op'],'job_id':pending['job_id'],
                    **({'body':reply['root_body'],'mass_kg':reply['mass_kg']} if call['op']=='commit' else {})}
        if stop.is_set():return {}
        if pending.get('request'):
            call=pending['request']
            return write(call['op'],call['body'])
        if not funding['configured']:raise ValueError('The pending workpiece has no declared workbench process')
        state=funding['state'];job=state['jobs'].get(pending['job_id'])
        if pending.get('installed') or job and job['status']=='installed':
            result=pending.get('installed') or {'root_body':job['root_body'],'mass_kg':job['product_kg']}
            memory.pop('fabrication_build');save()
            return {'phase':'installed','body':result['root_body'],'mass_kg':result['mass_kg']}
        if job:
            if job['status']=='paused':return write('resume',{'job_id':pending['job_id'],'revision':state['revision']})
            if job['status']=='running':
                if job['condition']!='working':raise ValueError('Workbench '+job['condition']+'; retain the pending workpiece')
                seconds=max(1,min(10,math.ceil((job['required_j']-job['work_j'])/
                    (state['config']['power_w']*state['config']['efficiency']))))
                self._post(profile,'/api/world/fabrication/wait',{**common,'seconds':seconds},cookie)
                return {'phase':'work','job_id':pending['job_id']}
            if job['status']!='ready':raise ValueError('The pending workpiece is not placeable')
            eyes=(profile.get('pose') or {}).get('eyes_m',[0,1.62,3]);failures=[]
            for dx,dz in ((3,0),(-3,0),(0,3),(0,-3),(3,3),(-3,-3)):
                if stop.is_set():return {}
                try:
                    preview=self._post(profile,'/api/world/fabrication/preview',
                        {**common,'job_id':pending['job_id'],'position_m':[eyes[0]+dx,eyes[2]+dz]},cookie)
                    break
                except ValueError as exc:failures.append(str(exc))
            else:raise ValueError('No admitted placement near this player: '+'; '.join(failures)[:200])
            return write('commit',{'job_id':pending['job_id'],'preview_id':preview['preview_id']})
        if 'plan' not in pending:
            plan=self._post(profile,'/api/world/fabrication/plan_make',
                {**common,'candidate':pending['candidate']},cookie)
            if not plan['available']:raise ValueError(plan['reason'])
            pending['plan']=plan;save()
            return {'phase':'review','quote':{k:plan['quote'][k] for k in
                ('material','stock_kg','product_kg','supply_required_j','minimum_duration_s')},'job_id':pending['job_id']}
        plan=pending['plan'];quote=plan['quote']
        materials=quote.get('stock_materials_kg') or {quote['material']:quote['stock_kg']}
        for material,kg in materials.items():
            shortage=max(0.,kg-state['stock_kg'].get(material,0.))
            if shortage<=1e-10:continue
            source=next((s for s in funding['stock_sources'] if s['pool']=='personal'
                         and s['material']==material and s['mass_kg']>0),None)
            if source is None:raise ValueError('This character needs '+material+' in its own material inventory')
            return write('fund_stock',{'material':material,'mass_kg':min(shortage,source['mass_kg']),
                'pool':'personal','rack_hash':source['rack_hash'],'revision':state['revision']})
        for name,kg in quote.get('assembly_goods_kg',{}).items():
            shortage=max(0.,kg-state.get('goods_stock_kg',{}).get(name,0.))
            if shortage<=1e-10:continue
            source=next((s for s in funding['goods_sources'] if s['pool']=='personal'
                         and s['material']==name and s['mass_kg']>0),None)
            if source is None:raise ValueError('This character needs processed '+name+' in its own inventory')
            return write('fund_goods',{'material':name,'mass_kg':min(shortage,source['mass_kg']),
                'pool':'personal','rack_hash':source['rack_hash'],'revision':state['revision']})
        needed=max(0.,quote['supply_required_j']-state['energy_j'])
        if needed>1e-10:
            sources=[s for s in funding['energy_sources'] if s['max_power_w']>0 and s['charge_j']>0]
            source=next((s for s in sources if s['connected']),None) or next(iter(sources),None)
            if source is None:raise ValueError('No charged battery with a finite output rating is available')
            # Bind identity/rating while sunlight and other loads change meters.
            # The receiving adapter still checks current charge/power under its
            # world lock; pending writes retain their exact retry arguments.
            source_hash=source.get('store_binding_hash') or source['store_hash']
            if not source['connected']:
                return write('connect_energy',{'store':source['id'],'store_hash':source_hash,
                    'power_w':min(source['max_power_w'],state['config']['power_w']),'revision':state['revision']})
            amount=min(needed,source['transfer_available_j'])
            if amount<.000001:
                self._post(profile,'/api/world/fabrication/wait',{**common,'seconds':1},cookie)
                return {'phase':'charging','job_id':pending['job_id']}
            return write('fund_energy',{'store_hash':source_hash,'joules':amount,'revision':state['revision']})
        if any(j['status']=='running' for j in state['jobs'].values()):
            raise ValueError('The workbench is occupied; retain the reviewed build')
        pending['request']={'op':'start_make','body':{**common,'plan_id':plan['plan_id'],
            'revision':state['revision'],'request_id':pending['job_id']}}
        save()
        return write('start_make',{})

    def _execute(self,profile,stop,cookie,action,state,ident):
        verb=action['verb'];memory=deepcopy(profile['ai'].get('memory',{}));sid=state['native']['session']
        target=action.get('target') or {}
        if verb=='compare-recipes':
            memory.update(comparison_signature=action['signature'],comparison=action['comparison'])
            self._save(profile,memory=memory)
            return {'recipes':[{k:r[k] for k in ('id','name','ready','missing','mass_kg')} for r in action['comparison']]}
        if verb=='select-recipe':
            memory['selected_recipe']=action['recipe']['id'];self._save(profile,memory=memory)
            return {'selected_recipe':action['recipe']['name']}
        if verb=='select-target':
            memory['selected_target']=target;memory.pop('watching',None);self._save(profile,memory=memory)
            return {'selected_target':target.get('machine') or target['body']}
        if verb=='move':
            self._move(profile,stop,cookie,action['aim'],action['stand_off_m'])
            return {'pose':deepcopy(profile.get('pose'))} if not stop.is_set() else {}
        if verb=='bank':
            reply=self._post(profile,'/api/workshop/market',{'action':'bank','joules':500,'request_id':ident},cookie)
            return {'balance_j':reply['balance_j']}
        if verb=='buy':
            reply=self._post(profile,'/api/workshop/market',{'action':'buy','item_id':action['item'],
                'quoted_price_j':action['quoted_price_j'],'request_id':ident},cookie)
            return {'balance_j':reply['balance_j'],'paid_j':action['quoted_price_j'],'item':action['item']}
        if verb=='collect':
            at=action['at_m']
            reply=self._post(profile,'/api/world/goods/collect',{'session':sid,'pile':action['pile'],
                'request_id':ident,'person':self._person(profile,cookie,at)},cookie)
            return {'pile':action['pile'],'collected':reply['collected']}
        if verb in ('build','continue-build'):
            source=self._post(profile,'/api/world/workshop/context',{},cookie)
            common={k:source[k] for k in ('session','scene')}
            funding=self._post(profile,'/api/world/fabrication/state',common,cookie)
            if funding['configured'] or memory.get('fabrication_build'):
                return self._fabricated_build(profile,stop,cookie,action,ident,common,funding)
            eyes=(profile.get('pose') or {}).get('eyes_m',[0,1.62,3]);failures=[]
            for dx,dz in ((3,0),(-3,0),(0,3),(0,-3),(3,3),(-3,-3)):
                if stop.is_set():return {}
                try:
                    preview=self._post(profile,'/api/world/workshop/preview',{'session':source['session'],'scene':source['scene'],
                        'candidate':action['recipe']['candidate'],'mode':'authoring','position_m':[eyes[0]+dx,eyes[2]+dz]},cookie)
                    break
                except ValueError as exc:failures.append(str(exc))
            else:raise ValueError('No admitted placement near this player: '+'; '.join(failures)[:200])
            if stop.is_set():return {}
            reply=self._post(profile,'/api/world/workshop/commit',{'session':preview['session'],'scene':preview['scene'],
                'preview_id':preview['preview_id'],'request_id':ident},cookie)
            return {'body':reply['root_body'],'mass_kg':reply['mass_kg'],'resources_charged':reply['resources_charged']}
        if verb in ('pack','acquire'):
            op='take' if verb=='pack' else 'equip' if target.get('where')=='stowed' else 'take_up'
            reply=self._post(profile,'/api/world/inventory',{'session':sid,'op':op,'item':target['body'],'request':ident,
                'revision':state['inventory']['record']['revision'],'person':self._person(profile,cookie,target['at_m'])},cookie)
            if not reply.get('ok'):raise ValueError(reply.get('why') or 'The player inventory refused this item')
            return {'body':target['body'],'revision':reply['record']['revision']}
        if verb=='inspect':
            reply=self._post(profile,'/api/world/action',{'session':sid,'object':target['body'],'primary':True,
                'person':self._person(profile,cookie,target['at_m'])},cookie)
            if reply.get('refused'):raise ValueError(reply['refused'])
            return {'object':target['body'],'study':(reply.get('state') or {}).get('study'),'said':reply.get('said')}
        if verb=='use-tool':
            person=self._person(profile,cookie,action['at_m'])
            resolved=self._post(profile,'/api/world/tool',{'session':sid,'person':person,'at_m':action['at_m']},cookie)
            if not resolved.get('enabled') or (resolved.get('ring') or {}).get('state')=='warn':
                raise ValueError(resolved.get('reason') or 'The selected native tool action is unavailable')
            # Like the browser: one use request waits while ordinary steps run
            # without sending a new held pose that could cancel the stroke.
            replies=[];errors=[]
            def use():
                try:replies.append(self._post(profile,'/api/world/tool/use',{'session':sid,'person':person,'at_m':action['at_m']},cookie))
                except Exception as exc:errors.append(exc)
            worker=threading.Thread(target=use,daemon=True);worker.start()
            while worker.is_alive():
                self._post(profile,'/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':12},cookie)
                # Finish an already started physical stroke even after pause;
                # the stop check prevents any subsequent decision/action.
                time.sleep(.05)
            worker.join()
            if errors:raise errors[0]
            reply=replies[0]
            if reply.get('refused'):raise ValueError(reply['refused'])
            return {'result':reply.get('result'),'said':reply.get('said'),'learning_pending':reply.get('learning_pending',False)}
        if verb=='power-on':
            # Learning targets use names; the native command takes the current
            # numeric program id. Resolve it just before acting, as the page
            # does. A fresh request sender keeps the native count small.
            native=self._post(profile,'/api/live/act',{'session':sid,'op':'poses'},cookie)
            program=next((p for p in (native.get('machines') or {}).get('programs',[])
                          if p.get('name')==target['machine']),None)
            if program is None:raise ValueError('The selected machine is no longer present')
            reply=self._post(profile,'/api/world/machine',{'session':sid,'program':program['id'],'power':True,
                'sender':ident,'seq':1},cookie)
            if reply.get('operated')!='applied':raise ValueError('Machine did not accept the power command')
            return reply
        if verb in ('watch-batch','observe'):
            person=self._person(profile,cookie,target['at_m'])
            reply=self._post(profile,'/api/world/watch-machine',{'session':sid,'machine':target['machine'],'person':person},cookie)
            memory['watching']=target['machine'];self._save(profile,memory=memory)
            if verb=='observe':
                # Twenty half-second observation intervals, plus API time. Reconsider
                # early when a durable goal changes, rather than paying for a
                # model decision every second of an unchanged heating phase.
                began_t=state['native']['t']
                for index in range(20):
                    if stop.is_set():break
                    self._post(profile,'/api/live/act',{'session':sid,'op':'step','dt':1/240,'n':120,'person':person},cookie)
                    if index%4==3:
                        goals=self._post(profile,'/api/workshop/goals',{'chain':'active'},cookie)
                        if (goals['chain_id'],goals['next_goal']) != (state['goals']['chain_id'],state['goals']['next_goal']):
                            return {**reply,'goal_changed':True,'observed_from_t_s':began_t}
                    stop.wait(.5)
            return reply
        raise ValueError('No implemented execution for this offered action')

    def shutdown(self) -> None:
        for _, stop in self.workers.values(): stop.set()
