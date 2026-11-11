import json
import unittest
from tools.translate_review import parse_review


class TranslationReviewTests(unittest.TestCase):
    def test_recomputes_score_and_rejects_model_pass(self):
        data = {'criteria': {'fidelity': 5, 'naturalness': 10, 'read_aloud': 10,
                             'cultural_clarity': 10, 'consistency': 10},
                'score': 10, 'pass': True}
        result = parse_review('Kết quả: ```json\n'+json.dumps(data)+'\n```')
        self.assertEqual(result['score'], 8.5)
        self.assertFalse(result['pass'])

    def test_missing_or_nonfinite_criterion_is_rejected(self):
        for criteria in ({'fidelity': 8}, dict.fromkeys(
                ('fidelity', 'naturalness', 'read_aloud', 'cultural_clarity', 'consistency'), float('nan'))):
            with self.assertRaises(ValueError):
                parse_review(json.dumps({'criteria': criteria}))
