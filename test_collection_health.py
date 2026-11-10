import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('radar', Path(__file__).with_name('career_radar_v13.py'))
radar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(radar)

class CollectionHealthTests(unittest.TestCase):
    def run_case(self, hits, errors, extract=None, mode='dry_run'):
        with tempfile.TemporaryDirectory() as folder:
            old = os.getcwd()
            os.chdir(folder)
            try:
                with patch.object(radar, 'STATE', Path('seen.json')), patch.object(radar, 'search', return_value=(hits, errors, [])), patch.object(radar, 'extract', return_value=extract), patch.object(radar, 'send') as send, patch.dict(os.environ, RADAR_MODE=mode):
                    failure = None
                    try:
                        radar.main()
                    except RuntimeError as exc:
                        failure = str(exc)
                    send.assert_not_called()
                    return json.loads(Path('career_radar_report.json').read_text()), failure
            finally:
                os.chdir(old)

    def test_empty_discovery_is_not_healthy(self):
        report, failure = self.run_case({}, [])
        self.assertEqual(report['health'], 'no_candidates')
        self.assertIsNotNone(failure)

    def test_total_search_failure_is_reported(self):
        report, failure = self.run_case({}, [{'query': q, 'error': 'timeout'} for q in radar.QUERIES])
        self.assertEqual(report['health'], 'search_failed')
        self.assertIsNotNone(failure)

    def test_partial_failure_blocks_live_mail(self):
        report, failure = self.run_case({'https://example.com/job':'재단 채용'}, [{'error':'timeout'}], mode='live')
        self.assertEqual(report['health'], 'partial_failure')
        self.assertIn('notification withheld', failure)

    def test_valid_discovery_without_matching_job_is_healthy(self):
        report, failure = self.run_case({'https://example.com/job':'재단 채용'}, [])
        self.assertEqual(report['health'], 'ok')
        self.assertIsNone(failure)

    def test_dry_run_never_sends_matching_jobs(self):
        job = dict(institution='재단', employment='계약직', location='서울', deadline='2026-12-01', job='행정 채용', qualification='원문 확인', url='https://example.com/job')
        report, failure = self.run_case({job['url']:job['job']}, [], job)
        self.assertEqual(len(report['jobs']), 1)
        self.assertIsNone(failure)

if __name__ == '__main__':
    unittest.main()
