"""Separate native reference/provider play across maps and real shortages.

python scripts/verify_ai_player.py --runner build/agent-progression/Release/banjo_live_world_run.exe --mode reference
python scripts/verify_ai_player.py --runner build/agent-progression/Release/banjo_live_world_run.exe --mode comparison

Comparison/live mode requires the app's local OPENAI_API_KEY configuration.
No key, native engine or successful provider play means no live qualification.
Each case owns an isolated server/world. User worlds and servers are untouched.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'playground'),str(ROOT)]
import server
import ai_player
import rover_brain

# Generator fixtures, not controller branches. Both current terrain families.
MAPS=((7,851269742,1),(4,1,0))
SCENARIOS=('normal','missing-starting-stock')


def token_totals(calls):
    complete=bool(calls) and all(c.get('usage') is not None for c in calls)
    return {'calls':len(calls),'usage_complete':complete,
        **{k:sum(c['usage'][k] for c in calls) if complete and all(c['usage'].get(k) is not None for c in calls) else None
           for k in ('input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens')}}


def validate_case(result):
    """Validate observed receipts; reaching a terminal status alone is not a pass."""
    problems=[]
    if result.get('error'):problems.append(result['error'])
    if result.get('other_guest_known'):problems.append('Another guest earned a technique')
    if result.get('other_guest_bag'):problems.append('Another guest received a packed product')
    if result.get('other_guest_wallet_j')!=0:problems.append('Another guest wallet changed')
    if result.get('persistence_state')!='saved':problems.append('Physical/source checkpoint is not saved')
    if not result.get('restart_retained'):problems.append('Actual server restart did not retain personal progress/runtime')
    if result['controller']=='live':
        if not result.get('calls'):problems.append('No live provider call was made')
        if not all(c.get('http_status')==200 and c.get('choice_in_catalog') for c in result.get('calls',[])):
            problems.append('A provider request failed or selected outside its observed catalog')
        if any(m!='openai' for m in result.get('history_modes',[])):problems.append('Live history contains a substituted/reference mode')
    elif result.get('calls'):problems.append('Reference run made a provider call')
    if result['scenario']=='normal':
        if result.get('character_status')!='complete':problems.append('Normal play did not complete')
        if not result.get('all_chains_complete'):problems.append('Declared chains are incomplete')
        if len(result.get('known',[]))<2:problems.append('Tool and processing techniques were not both earned')
        required={'move','select-target','inspect','acquire','use-tool','watch-batch','compare-recipes','build','pack'}
        if not required<=set(result.get('actions',[])):problems.append('Expanded player actions were not exercised')
        if not result.get('packed_built_product'):problems.append('No own built product was packed')
        if not result.get('source_evidence'):problems.append('No personal source evidence was retained')
    else:
        if result.get('character_status')!='blocked':problems.append('Scarcity did not produce an explicit blocker')
        if result.get('known') or result.get('packed_built_product') or result.get('all_chains_complete'):
            problems.append('Scarcity improperly awarded later progress')
        if not result.get('shortage_observed'):problems.append('The reported blocker does not identify the removed supply')
    return problems


class RecordedProvider:
    """Real transport only. No scripted choices, reference fallback or retries."""
    def __init__(self,key,model,calls,checkpoint):
        self.client=rover_brain.OpenAIDecider(key,model)
        self.calls,self.checkpoint=calls,checkpoint

    def ask(self,state,questions):
        if len(self.calls)>=ai_player.MAX_DECISIONS:raise ValueError('Provider case call budget reached')
        call={'index':len(self.calls)+1,'model':self.client.model,'choice_in_catalog':False,
              'choice':None,'http_status':None,'response_status':None,'usage':None,'latency_s':None}
        self.calls.append(call)
        self.checkpoint()
        try:
            answer=self.client.ask(state,questions)
            choice=answer.get('next',{}).get('choice')
            call['choice_in_catalog']=choice in questions['next']['criteria']
            # Retain bounded action ids, never raw prompts/provider response text.
            call['choice']=choice if call['choice_in_catalog'] else None
            return answer
        except ValueError as exc:
            call['error']=str(exc)
            raise
        finally:
            call.update(self.client.last_call or {})
            self.checkpoint()


def provenance(runner):
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).splitlines()
    diff=subprocess.check_output(['git','diff','HEAD'],cwd=ROOT)
    return {'commit':commit,'working_tree_dirty':bool(dirty),'changed_files':dirty,
            'tracked_diff_sha256':hashlib.sha256(diff).hexdigest(),
            'verification_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'runner_sha256':hashlib.sha256(runner.read_bytes()).hexdigest() if runner.is_file() else None,
            'runner':str(runner),'platform':platform.platform(),'python':platform.python_version()}


def save_report(path,report,key=''):
    path.parent.mkdir(parents=True,exist_ok=True)
    encoded=json.dumps(report,indent=2,allow_nan=False)
    if key:encoded=encoded.replace(key,'[redacted]')
    temporary=path.with_suffix('.tmp')
    temporary.write_text(encoded,encoding='utf-8');temporary.replace(path)


def run_case(args,controller,map_fixture,scenario,key,model,report,checkpoint):
    # Imported after selecting the exact runner; existing fixture constants
    # cannot silently select another native binary or skip native work.
    sys.path.insert(0,str(ROOT/'tests'))
    import ai_player_tests
    fixture=ai_player_tests.AutonomousGuests()
    terrain,goods,choice=map_fixture
    result={'controller':controller,'model':model if controller=='live' else None,
        'terrain_seed':terrain,'goods_seed':goods,'scenario':scenario,'calls':[],
        'status':'running','restart_retained':False}
    report['cases'].append(result);checkpoint()
    started=time.monotonic()
    with mock.patch.dict(os.environ,{'BANJO_DECIDER':'reflex'}):
        fixture.setUp()
        try:
            with mock.patch.object(server.secrets,'randbelow',side_effect=[choice,goods-1]):
                world,owner,app=fixture.setup_world()
            result['world']=world
            shortage=None
            if scenario!='normal':
                camp=fixture.post('/api/workshop/goals',{},world)
                requirement=next(g['requirement'] for g in camp['goals'] if g['requirement']['kind']=='stock-purchase')
                shortage=requirement['substance']
                market=fixture.post('/api/workshop/market',{},world)
                offers=[o for o in market['offers'] if o.get('substance')==shortage]
                if not offers:raise ValueError('No offered supply matches the starting stock requirement')
                with server.workshop_library._connect(app) as db:
                    for offer in offers:db.execute('UPDATE market_stock SET remaining=0 WHERE item_id=?',(offer['id'],))
                result['fixture']={'removed_supply':shortage,'offers':[o['id'] for o in offers]}
            if controller=='live':
                app.api_key,app.model=key,model
                app.ai_players.decider_factory=lambda:RecordedProvider(key,model,result['calls'],checkpoint)
            bot=fixture.post('/api/world/ai',{'action':'start','mode':'openai' if controller=='live' else 'reference',
                'name':f'{controller} map {terrain}'},world)
            result['character']=bot['id'];last_progress=None
            deadline=time.monotonic()+args.case_timeout
            while True:
                final=fixture.post('/api/world/ai',{'action':'watch','id':bot['id']},world)
                character=final['character']
                progress=(character['decisions'],character['status'])
                if progress!=last_progress:
                    print(f"{controller} terrain {terrain} {scenario}: {progress[0]} decisions / {progress[1]}",flush=True)
                    last_progress=progress
                if character['status'] in ('complete','blocked'):break
                if time.monotonic()>=deadline:
                    fixture.post('/api/world/ai',{'action':'pause','id':bot['id']},world)
                    app.ai_players.workers[bot['id']][0].join(timeout=35)
                    raise ValueError('Case wall-time budget reached; owned character paused, no retry')
                time.sleep(.25)
            profile=app.room.player_records[bot['id']]
            history=deepcopy(profile['ai']['history'])
            chains=[fixture.post('/api/workshop/goals',{'chain':c['id']},world,profile['token']) for c in final['goals']['chains']]
            journal=server.journal_of(app,bot['id'])
            other=fixture.post('/api/world/inventory/shown',{'session':app.live.session.id},world)
            result.update(character_status=character['status'],message=character.get('message'),
                decisions=character['decisions'],native_t_s=app.live.session.state['t'],
                known=sorted(journal.knows()),tech_tree_total=len(final['skills']),
                source_evidence=[{k:e.get(k) for k in ('id','source','test','passes','result')} for e in journal.data['evidence'].values()],
                actions=sorted({h['action'] for h in history}),history_modes=[h['mode'] for h in history],
                history=[{k:h.get(k) for k in ('action','choice','mode','model','result','seconds','goal','chain')} for h in history],
                all_chains_complete=all(c['complete'] for c in chains),
                goals_complete=sum(g['complete'] for c in chains for g in c['goals']),
                goals_total=sum(len(c['goals']) for c in chains),
                packed_built_product=bool(final['state']['inventory']['record']['stowed']),
                other_guest_known=sorted(server.journal_of(app,owner['id']).knows()),
                other_guest_bag=other['record']['stowed'],
                other_guest_wallet_j=fixture.post('/api/workshop/market',{},world)['balance_j'],
                shortage_observed=bool(shortage and shortage in (character.get('message') or '').lower()))
            if not server.keep_world(app,'AI verification restart boundary'):raise ValueError('Physical/source checkpoint failed')
            # The active inventory object is authoritative until RoomStore
            # snapshots it. The profile's original inventory is only a load seed.
            before_inventory=deepcopy(final['state']['inventory']['record'])
            before_known=journal.knows();before_evidence=set(journal.data['evidence'])
            before_runtime=app.brains.runtime()
            fixture.stop();fixture.start()
            fixture.post('/api/world/open',{},world)
            restored=fixture.post('/api/world/ai',{'action':'watch','id':bot['id']},world)
            restored_app=fixture.app.hub.get(world)
            restored_journal=server.journal_of(restored_app,bot['id'])
            result['restart_checks']={
                'inventory':restored['state']['inventory']['record']==before_inventory,
                'knowledge':restored_journal.knows()==before_known,
                'evidence':set(restored_journal.data['evidence'])==before_evidence,
                'machine_runtime':restored_app.brains.runtime()==before_runtime,
                'player_outbox':not restored_app.room.player_evidence_pending,
                'machine_outbox':not restored_app.room.machine_evidence_pending}
            result['restart_retained']=all(result['restart_checks'].values())
            result['persistence_state']=restored_app.room.persistence['state']
        except (AssertionError,ValueError,OSError,RuntimeError,KeyError,StopIteration) as exc:
            result['error']=f'{type(exc).__name__}: {exc}'
        finally:
            fixture.tearDown()
            result['wall_s']=round(time.monotonic()-started,3)
            result['tokens']=token_totals(result['calls'])
            result['problems']=validate_case(result)
            result['status']='passed' if not result['problems'] else 'failed'
            checkpoint()
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runner',type=Path,default=Path(os.environ.get('BANJO_LIVE_ENGINE','build/agent-progression/Release/banjo_live_world_run.exe')))
    parser.add_argument('--mode',choices=('reference','live','comparison'),default='comparison')
    parser.add_argument('--model',default=None)
    parser.add_argument('--case-timeout',type=float,default=900)
    parser.add_argument('--out',type=Path,default=ROOT/'build/ai-player-verification/report.json')
    args=parser.parse_args(argv)
    if not 30<=args.case_timeout<=1800:parser.error('case-timeout must be 30..1800 seconds')
    args.runner=args.runner.expanduser().resolve()
    engine=args.runner.with_name('banjo_platform_cli.exe' if os.name=='nt' else 'banjo_platform_cli')
    key,configured_model=server.local_configuration();model=args.model or configured_model
    report={'schema':'banjo.ai-player-verification.v1','mode':args.mode,'model':model,
        'source':provenance(args.runner),'status':'running','reference_verified':False,'live_provider_verified':False,
        'comparison_verified':False,'cases':[],'provider_tokens':token_totals([]),
        'limits':{'decisions_per_case':ai_player.MAX_DECISIONS,'provider_calls_per_case':ai_player.MAX_DECISIONS,
                  'max_output_tokens_per_call':800,'case_wall_timeout_s':args.case_timeout,
                  'native_dt_s':1/240,'scene_cell_m':.05,'unattended_clock':False,
                  'robot_decider':'reflex','stock_and_outcome_grants':False}}
    problems=[]
    if not args.runner.is_file() or not engine.is_file():problems.append('The selected native runner and adjacent platform CLI are required')
    if args.mode!='reference' and not key:problems.append('OPENAI_API_KEY is not configured locally; live provider verification has not run')
    checkpoint=lambda:save_report(args.out,report,key)
    if problems:
        report.update(status='unavailable',problems=problems);checkpoint()
        print('; '.join(problems));print(f'Report: {args.out.resolve()}');return 2
    os.environ['BANJO_LIVE_ENGINE']=str(args.runner)
    modes=('reference','live') if args.mode=='comparison' else (args.mode,)
    checkpoint()
    for controller in modes:
        for map_fixture in MAPS:
            for scenario in SCENARIOS:
                result=run_case(args,controller,map_fixture,scenario,key,model,report,checkpoint)
                # Authentication failure is the same external blocker on every
                # map. Do not spend more requests retrying it on another seed.
                if any(c.get('http_status') in (401,403) for c in result['calls']):break
            if any(c.get('http_status') in (401,403) for r in report['cases'] for c in r['calls']):break
    expected={(terrain,scenario) for terrain,_,_ in MAPS for scenario in SCENARIOS}
    for controller,field in (('reference','reference_verified'),('live','live_provider_verified')):
        subset=[r for r in report['cases'] if r['controller']==controller]
        report[field]=({(r['terrain_seed'],r['scenario']) for r in subset}==expected and all(r['status']=='passed' for r in subset))
    report['comparison_verified']=report['reference_verified'] and report['live_provider_verified']
    report['status']='passed' if all(report[c+'_verified'] for c in
        ('reference','live_provider') if (c=='reference' and 'reference' in modes) or (c=='live_provider' and 'live' in modes)) else 'failed'
    report['provider_tokens']=token_totals([c for r in report['cases'] for c in r['calls']])
    checkpoint();print(f'Report: {args.out.resolve()}')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
