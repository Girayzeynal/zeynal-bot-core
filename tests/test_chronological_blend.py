from unittest import TestCase
from hybrid_engine.chronological_blend import evaluate, EQUAL

def pair(fid, score, decision, final, actual=(100,100)):
    b=dict(league='NBA',season='2026/2027',fixture_id=fid,snapshot_sha256=fid,
           model_digest='base',prediction=[110,110],actual=list(actual),
           label_available_utc=final,fixture_start_utc=final-100,
           predicted_quarters=[[27.5,27.5]]*4,
           actual_periods={'home':[25]*4,'away':[25]*4})
    c=dict(b,prediction=list(score),candidate_archived_at_utc=decision,
           prediction_generated_at_utc=decision-1,predicted_quarters=[[score[0]/4,score[1]/4]]*4)
    return c,b

def protocol(family, rows):
    return {'family':family},{('NBA','2026/2027','base','base',
                               'PACE_EFFICIENCY' if family=='adaptive-v2' else 'V3'):rows}

class ChronologicalBlendTests(TestCase):
    def test_duplicates_do_not_add_games_and_future_labels_not_used(self):
        v2=[pair('a',(100,100),100,500),pair('b',(100,100),400,800),
            pair('c',(100,100),900,1200)]
        v3=[pair('a',(105,105),101,500),pair('b',(105,105),401,800),
            pair('c',(105,105),901,1200)]
        r=evaluate([protocol('adaptive-v2',v2),protocol('nba-v3',v3),
                    protocol('adaptive-v2',v2),protocol('current-assessment',v3)])
        self.assertEqual(r['n'],3)
        self.assertEqual(r['duplicate_records'],3)
        g=r['groups'][0]
        self.assertEqual([x['training_n'] for x in g['trace']],[0,0,2])
        self.assertEqual(g['trace'][1]['weights'],list(EQUAL))
        self.assertGreater(g['trace'][2]['weights'][1],g['trace'][2]['weights'][0])
        self.assertFalse(r['production_enabled'])
        self.assertEqual(g['metrics']['V2']['quarter_mae'],[0]*4)

    def test_earliest_publication_not_best_outcome(self):
        a=pair('a',(120,120),100,500)
        later=pair('a',(100,100),200,500)
        v3=pair('a',(105,105),101,500)
        r=evaluate([protocol('adaptive-v2',[later,a]),protocol('nba-v3',[v3])])
        self.assertEqual(r['groups'][0]['metrics']['V2']['total_mae'],40)

    def test_conflicting_same_clock_excluded(self):
        r=evaluate([protocol('adaptive-v2',[pair('a',(100,100),100,500),
                                           pair('a',(101,101),100,500)]),
                    protocol('nba-v3',[pair('a',(105,105),101,500)])])
        self.assertEqual((r['n'],r['conflicts']),(0,1))

    def test_same_time_final_not_training(self):
        r=evaluate([protocol('adaptive-v2',[pair('a',(100,100),100,500),
                                           pair('b',(100,100),500,900)]),
                    protocol('nba-v3',[pair('a',(105,105),101,500),
                                       pair('b',(105,105),500,900)])])
        self.assertEqual([x['training_n'] for x in r['groups'][0]['trace']],[0,0])
