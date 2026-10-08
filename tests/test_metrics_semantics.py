import csv
import io
import unittest
from benchmark.metrics import summary
from benchmark.reports import csv_text


def unit(index,status,verdict=None,category=None,seed=11,usage=None):
    return {'id':str(index),'model_index':0,'seed':seed,'status':status,'run_id':str(index),
            'record':{'unit_id':str(index),'verdict':verdict,'failure_category':category,
                      'seed_requested':seed,'usage':usage,'tool_calls':index,'model_calls':99}}


def experiment(protocol='final_only'):
    return {'manifest':{'protocol':protocol,'seeds':[11,22,33],
                        'models':[{'provider':'fake','model':'test'}]},
            'units':[unit(1,'Finished','AC',usage={'input_tokens':10,'output_tokens':5}),
                     unit(2,'Finished','WA',seed=22),
                     unit(3,'Failed',category='agent_failure',usage={'input_tokens':3,'output_tokens':None}),
                     unit(4,'Failed',category='model_failure'),
                     unit(5,'Failed',category='judge_failure'),
                     unit(6,'Failed',category='infrastructure_failure'),
                     unit(7,'Pending'),unit(8,'Running')]}


class MetricsSemanticsTests(unittest.TestCase):
    def test_hand_calculated_numerators_and_denominators(self):
        g=summary(experiment())['groups'][0]
        self.assertEqual(g['planned_units'],8)
        self.assertEqual(g['completed_units'],6)
        self.assertEqual(g['attempted'],7)
        self.assertEqual(g['pending_units'],1)
        self.assertEqual(g['running_units'],1)
        self.assertEqual(g['evaluable'],3)
        self.assertEqual(g['excluded'],3)
        self.assertEqual(g['solved'],1)
        self.assertEqual(g['evaluable_solve_rate'],1/3)
        self.assertEqual(g['solve_rate'],1/3)
        self.assertEqual(g['end_to_end_success_rate'],1/6)
        self.assertEqual(g['end_to_end_success_rate_denominator'],6)
        self.assertEqual(g['pass@1'],1/2)
        self.assertEqual(g['pass@1_denominator'],2)
        self.assertIsNone(g['final_end_to_end_success_rate'])
        self.assertFalse(g['experiment_complete'])
        for counts in g['failure_breakdown'].values():
            self.assertEqual(counts,{'count':1,'rate':1/6,'share_of_failures':1/5})
        self.assertEqual(g['verdict_counts']['AC'],1)
        self.assertEqual(g['verdict_counts']['WA'],1)

    def test_missing_usage_and_partial_observation(self):
        g=summary(experiment())['overall']
        self.assertFalse(g['usage_complete'])
        self.assertEqual(g['usage_observed_units'],2)
        self.assertEqual(g['mean_input_tokens'],6.5)
        self.assertEqual(g['mean_output_tokens'],5)
        self.assertEqual(g['mean_total_tokens'],15)
        self.assertIsNone(g['tokens_per_solved_problem'])

    def test_final_denominator_requires_all_planned_units(self):
        b=experiment()
        for u in b['units'][6:]:u.update(status='Failed');u['record']['failure_category']='infrastructure_failure'
        g=summary(b)['overall']
        self.assertTrue(g['experiment_complete'])
        self.assertEqual(g['final_end_to_end_success_rate'],1/8)
        self.assertEqual(g['end_to_end_success_rate_denominator'],8)
        self.assertEqual(g['evaluable'],3)
        self.assertEqual(g['failure_breakdown']['infrastructure_failure']['count'],3)

    def test_only_pending_and_running_have_null_rates(self):
        b=experiment();b['units']=b['units'][6:]
        g=summary(b)['overall']
        for key in ('solve_rate','pass@1','end_to_end_success_rate','final_end_to_end_success_rate','mean_total_tokens','tokens_per_solved_problem'):
            self.assertIsNone(g[key])
        self.assertEqual(g['completed_units'],0)
        self.assertEqual(g['excluded'],0)

    def test_stale_ac_on_failure_never_counts_solved(self):
        b=experiment();b['units']=[unit(1,'Failed','AC','agent_failure')]
        g=summary(b)['overall']
        self.assertEqual(g['solved'],0)
        self.assertEqual(g['evaluable'],1)
        self.assertEqual(g['solve_rate'],0)
        self.assertEqual(g['end_to_end_success_rate'],0)

    def test_invalid_finished_or_uncategorized_failure_excluded(self):
        b=experiment();b['units']=[unit(1,'Finished','SE'),unit(2,'Failed'),unit(3,'Finished')]
        g=summary(b)['overall']
        self.assertEqual(g['evaluable'],0)
        self.assertEqual(g['failure_breakdown']['judge_failure']['count'],1)
        self.assertEqual(g['failure_breakdown']['infrastructure_failure']['count'],2)
        self.assertEqual(g['end_to_end_success_rate'],0)

    def test_first_seed_not_replaced_and_revisions_not_samples(self):
        b=experiment();b['units']=[unit(1,'Failed',category='model_failure'),unit(2,'Finished','AC',seed=22)]
        b['units'][1]['record']['attempts']=[{'verdict':'WA'}]*10+[{'verdict':'AC'}]
        g=summary(b)['overall']
        self.assertIsNone(g['pass@1'])
        self.assertEqual(g['pass@1_denominator'],0)
        self.assertEqual(g['solved'],1)
        self.assertEqual(g['completed_units'],2)

    def test_protocols_keep_independent_run_semantics(self):
        final=summary(experiment('final_only'));iterative=summary(experiment('iterative'))
        self.assertEqual(final['overall'],iterative['overall'])
        self.assertEqual(iterative['protocol'],'iterative')
        self.assertIn('not single-code-generation',iterative['definitions']['iterative'])

    def test_models_are_grouped_separately(self):
        b=experiment();b['manifest']['models'].append({'provider':'fake','model':'other'})
        second=unit(9,'Finished','AC');second['model_index']=1;b['units'].append(second)
        s=summary(b)
        self.assertEqual(s['groups'][1]['end_to_end_success_rate'],1)
        self.assertEqual(s['groups'][0]['end_to_end_success_rate'],1/6)
        self.assertEqual(s['overall']['end_to_end_success_rate'],2/7)

    def test_zero_usage_is_available_and_csv_preserves_missing(self):
        b=experiment();b['units']=[unit(1,'Finished','AC',usage={'input_tokens':0,'output_tokens':0}),unit(2,'Running')]
        g=summary(b)['overall']
        self.assertTrue(g['usage_complete'])
        self.assertEqual(g['tokens_per_solved_problem'],0)
        rows=list(csv.DictReader(io.StringIO(csv_text(b))))
        self.assertEqual(rows[0]['total_tokens'],'0')
        self.assertEqual(rows[1]['total_tokens'],'')
        self.assertEqual(rows[1]['status'],'Running')
        self.assertEqual(rows[0]['unit_id'],'1')

    def test_group_final_rate_waits_for_whole_experiment(self):
        b=experiment();b['manifest']['models'].append({'provider':'fake','model':'other'})
        second=unit(9,'Finished','AC');second['model_index']=1;b['units'].append(second)
        g=summary(b)['groups'][1]
        self.assertTrue(g['group_complete'])
        self.assertFalse(g['experiment_complete'])
        self.assertIsNone(g['final_end_to_end_success_rate'])
        self.assertEqual(g['end_to_end_success_rate'],1)

    def test_malformed_usage_is_missing_and_cannot_overwrite_csv_identity(self):
        for usage in ({},[],{'input_tokens':-1,'output_tokens':'5'}, {'input_tokens':True,'output_tokens':float('nan')}):
            b=experiment();b['units']=[unit(1,'Finished','AC',usage=usage)]
            g=summary(b)['overall']
            self.assertFalse(g['usage_complete'])
            self.assertEqual(g['usage_observed_units'],0)
            self.assertIsNone(g['mean_input_tokens'])
            self.assertIsNone(g['tokens_per_solved_problem'])
            row=list(csv.DictReader(io.StringIO(csv_text(b))))[0]
            self.assertEqual(row['total_tokens'],'')
        b['units'][0]['record']['usage']={'input_tokens':10,'output_tokens':20,'unit_id':'FAKE'}
        row=list(csv.DictReader(io.StringIO(csv_text(b))))[0]
        self.assertEqual(row['unit_id'],'1')
        self.assertEqual(row['total_tokens'],'30')
