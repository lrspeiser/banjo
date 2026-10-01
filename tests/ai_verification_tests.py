"""Qualification/transport-report boundaries; these are not live-model results."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import json

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('verify_ai_player',ROOT/'scripts/verify_ai_player.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)


def observed_case():
    return {'controller':'reference','scenario':'normal','calls':[],
        'character_status':'complete','all_chains_complete':True,'known':['tool','process'],
        'actions':['move','select-target','inspect','acquire','use-tool','watch-batch','compare-recipes','build','pack'],
        'packed_built_product':True,'source_evidence':[{'id':'source'}],
        'other_guest_known':[],'other_guest_bag':[],'other_guest_wallet_j':0,
        'persistence_state':'saved','restart_retained':True,'history_modes':['reference']}


class Qualification(unittest.TestCase):
    def test_terminal_complete_alone_does_not_qualify_gameplay(self):
        case=observed_case();self.assertEqual([],verify.validate_case(case))
        for field,value in [('all_chains_complete',False),('known',[]),('actions',[]),
                            ('source_evidence',[]),('restart_retained',False),('packed_built_product',False)]:
            changed=deepcopy(case);changed[field]=value
            self.assertTrue(verify.validate_case(changed),field)

    def test_reference_or_fake_history_cannot_qualify_live_provider(self):
        case=observed_case();case['controller']='live'
        self.assertTrue(verify.validate_case(case))
        case['calls']=[{'http_status':200,'choice_in_catalog':True}]
        self.assertTrue(verify.validate_case(case),'Reference history passed as live')
        case['history_modes']=['openai'];self.assertEqual([],verify.validate_case(case))
        case['calls'][0]['http_status']=401;self.assertTrue(verify.validate_case(case))

    def test_scarcity_requires_explicit_blocker_and_no_later_reward(self):
        case=observed_case();case.update(scenario='missing-starting-stock',character_status='blocked',
            all_chains_complete=False,known=[],packed_built_product=False,shortage_observed=True)
        self.assertEqual([],verify.validate_case(case))
        case['known']=['free technique'];self.assertTrue(verify.validate_case(case))
        case['known']=[];case['shortage_observed']=False;self.assertTrue(verify.validate_case(case))

    def test_guest_awards_and_unsaved_source_fail_even_when_bot_completes(self):
        for field,value in [('other_guest_known',['free skill']),('other_guest_wallet_j',1),
                            ('other_guest_bag',['free product']),('persistence_state','failed')]:
            case=observed_case();case[field]=value;self.assertTrue(verify.validate_case(case),field)

    def test_subset_token_counts_are_not_added_to_total_and_unknown_stays_unknown(self):
        usage={'input_tokens':10,'output_tokens':5,'total_tokens':15,'cached_tokens':8,'reasoning_tokens':3}
        summed=verify.token_totals([{'usage':usage},{'usage':usage}])
        self.assertEqual(30,summed['total_tokens']);self.assertEqual(16,summed['cached_tokens'])
        self.assertEqual(6,summed['reasoning_tokens']);self.assertTrue(summed['usage_complete'])
        unknown=verify.token_totals([{'usage':usage},{'usage':None}])
        self.assertFalse(unknown['usage_complete']);self.assertIsNone(unknown['total_tokens'])

    def test_missing_key_fails_before_creating_world_and_writes_unavailable_report(self):
        with tempfile.TemporaryDirectory() as temp:
            runner=Path(temp)/'banjo_live_world_run.exe';runner.touch()
            adjacent='banjo_platform_cli.exe' if verify.os.name=='nt' else 'banjo_platform_cli'
            runner.with_name(adjacent).touch();report=Path(temp)/'report.json'
            with mock.patch.object(verify.server,'local_configuration',return_value=('','gpt-5-mini')), \
                 mock.patch.object(verify,'provenance',return_value={'unit_fixture':True}), \
                 mock.patch.object(verify,'run_case') as run:
                code=verify.main(['--runner',str(runner),'--mode','comparison','--out',str(report)])
            self.assertEqual(2,code);run.assert_not_called()
            saved=json.loads(report.read_text());self.assertEqual('unavailable',saved['status'])
            self.assertEqual([],saved['cases']);self.assertFalse(saved['live_provider_verified'])
            self.assertEqual(0,saved['provider_tokens']['calls'])

    def test_recorded_client_uses_transport_choice_and_preserves_failure_measurements(self):
        calls=[];checkpoints=[]
        recorder=verify.RecordedProvider('not-a-live-key','model',calls,lambda:checkpoints.append(1))
        questions={'next':{'criteria':{'actual-choice':'Inspect'}}}
        recorder.client=mock.Mock(model='fixture-model',last_call={'http_status':200,'usage':None,'latency_s':.1})
        recorder.client.ask.return_value={'next':{'choice':'actual-choice'}}
        self.assertEqual('actual-choice',recorder.ask({},questions)['next']['choice'])
        self.assertTrue(calls[0]['choice_in_catalog']);self.assertEqual(2,len(checkpoints))
        recorder.client.ask.side_effect=ValueError('the model answered HTTP 401')
        recorder.client.last_call={'http_status':401,'usage':None,'latency_s':.2}
        with self.assertRaises(ValueError):recorder.ask({},questions)
        self.assertEqual(401,calls[1]['http_status']);self.assertIsNone(calls[1]['usage'])
        self.assertNotIn('not-a-live-key',json.dumps(calls))

    def test_call_budget_refuses_transport_without_falling_back(self):
        calls=[{} for _ in range(verify.ai_player.MAX_DECISIONS)]
        recorder=verify.RecordedProvider('not-a-live-key','model',calls,lambda:None)
        recorder.client=mock.Mock()
        with self.assertRaisesRegex(ValueError,'budget'):recorder.ask({}, {})
        recorder.client.ask.assert_not_called()


if __name__=='__main__':unittest.main()
