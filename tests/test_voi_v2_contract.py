import unittest
from app.core.diagnostic_belief import validation_utility
from app.core.information_value import action_values, select_action
from app.core.information_outcomes import InformationOutcomes
from app.core.voi_planning import plan_voi


def toy():
    return {'prior':{'A':.5,'B':.5}, 'terminal_utility':validation_utility(['A','B']), 'horizon':2,
            'actions':[{'id':'t','type':'request_test','target':'T', 'outcomes':[
                {'id':'positive','likelihood':{'A':.9,'B':.1}},
                {'id':'negative','likelihood':{'A':.1,'B':.9}}]}]}

class ContractTests(unittest.TestCase):
    def test_accuracy_only_math(self):
        m=toy(); r=action_values(m['prior'],m['actions'],m)[0]
        self.assertAlmostEqual(r['voi'],.4)
        self.assertEqual(r['cost_penalty'],0)
    def test_horizon_passed_to_policy(self):
        m=toy(); cs=[{'action_id':'t','type':'Test','action':'request_test','target':'T','outcome_model':'t'},
                     {'action_id':'diagnose','type':'Diagnose','action':'diagnose','target':None,'outcome_model':None}]
        result=select_action(cs,selector='bayesian_voi',belief=m['prior'],artifact=m)
        self.assertEqual(result['horizon'],2)
        self.assertEqual(result['selected_action']['action_id'],'t')
    def test_costs_ignored(self):
        m=toy(); a=action_values(m['prior'],m['actions'],m)
        m['cost_weights']={'money':10000000};m['actions'][0]['cost']={'money':100000}
        self.assertEqual(a,action_values(m['prior'],m['actions'],m))
    def test_conditional_bellman(self):
        m=toy(); r=plan_voi(m['prior'],m['actions'],m['terminal_utility'],horizon=3)
        self.assertAlmostEqual(r['optimal_value'],.9)
    def test_v2_costless_validation(self):
        v2={'schema_version':2,'model_id':'toy','revision':'v2',
            'provenance':{'synthetic':True,'review_status':'unreviewed','assumptions':['toy only']},
            'diagnoses':{'A':'general_medicine','B':'general_medicine'}, 'prior':{'A':.5,'B':.5},
            'terminal_utility':validation_utility(['A','B']),'horizon':1,
            'actions':[{'id':'t','type':'request_test','target':'T','outcomes':[
                {'id':'positive','likelihood':{'A':.9,'B':.1}, 'observation':{'source':'objective_findings','text':'T: positive'},'supports_diagnoses':['A']},
                {'id':'negative','likelihood':{'A':.1,'B':.9}, 'observation':{'source':'objective_findings','text':'T: negative'},'supports_diagnoses':['B']}]}]}
        self.assertEqual(InformationOutcomes(v2).artifact['provenance']['cost_free_schema_source'],2)

if __name__=='__main__': unittest.main()
