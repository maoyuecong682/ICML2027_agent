import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from p0_privacy.public_background import DEFAULT_OUTPUT
from p0_privacy.recovery_supplement import evaluate, load_jobs


class RuleSupplementTests(unittest.TestCase):
    def test_all_requested_views_run_with_network_connections_forbidden(self):
        background = json.loads(DEFAULT_OUTPUT.read_bytes())
        jobs = load_jobs()
        self.assertEqual(len(jobs), 50)
        with tempfile.TemporaryDirectory() as folder:
            with patch('socket.socket.connect', side_effect=AssertionError('Network is forbidden')):
                for key, job in jobs.items():
                    result = evaluate(key, job, background, Path(folder))
                    for arm, conditions in result['conditions'].items():
                        self.assertTrue(all(r['basis'] in {'background_guess', 'no_candidate'}
                                            and not r['evidence'] for r in conditions['none']['rows']))
                        if job['cohort'] == 'original3':
                            self.assertEqual(conditions['local']['rows'], conditions['shared']['rows'])
                    self.assertEqual(result['status'], 'complete')
            audits = list(Path(folder).glob('*/*.json'))
            self.assertEqual(len(audits), 50 * 2 * 3)
            self.assertTrue(all(json.loads(f.read_bytes())['llm_calls'] == 0 for f in audits))
            self.assertTrue(all(json.loads(f.read_bytes())['public_background_used_by_recoverer'] for f in audits))
            for f in audits:
                if f.stem.endswith('_none'):
                    self.assertTrue(all(not r['facts'] for v in json.loads(f.read_bytes())['receiver_inputs']
                                        for r in v['memory']['receivers']))


if __name__ == '__main__':
    unittest.main()
