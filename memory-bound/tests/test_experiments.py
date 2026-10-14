"""Protege a validade da janela e da matriz, inclusive sem requisições concluídas."""

import json
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from experiment_metrics import make_plan, summarize_resources
from measurement import Measurement


class ExperimentTests(unittest.TestCase):
    def test_matrix_has_three_repetitions_and_changes_order(self):
        plan = make_plan([500, 1024, 2048, 4096], [1, 2, 4, 8], 3)
        self.assertEqual(len(plan), 48)
        self.assertEqual(set(Counter((r['ram_mib'], r['users']) for r in plan).values()), {3})
        orders = [[(r['ram_mib'], r['users']) for r in plan if r['repetition'] == rep] for rep in (1, 2, 3)]
        self.assertNotEqual(orders[0], orders[1])
        self.assertNotEqual(orders[1], orders[2])
        self.assertEqual(len({tuple(sorted(r.items())) for r in plan}), 48)

    def test_warmup_carryover_and_pending_requests_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            meter = Measurement(Path(directory), 10)
            try:
                meter.completed_request(1, 2, 1000, False)  # aquecimento
                meter.begin(10)
                meter.completed_request(9, 11, 2000, False)  # vazão, sem latência
                meter.started(11)
                meter.completed_request(11, 12, 1000, False)
                meter.started(13)
                meter.completed_request(13, 14, 500, True)
                meter.started(19)
                meter.completed_request(19, 21, 2000, False)  # além da janela
                result = meter.save(True)
                self.assertEqual(result['requests'], 3)
                self.assertEqual(result['failures'], 1)
                self.assertEqual(result['carryover_completed'], 1)
                self.assertEqual(result['in_flight_at_end'], 1)
                self.assertEqual(result['latency_samples'], 1)
                self.assertEqual(result['all_latency_samples'], 2)
                self.assertEqual(result['mean_ms'], 1000)
                self.assertEqual(result['all_mean_ms'], 750)
                self.assertEqual(result['p95_ms'], 1000)
                self.assertEqual(result['success_rps'], 0.2)
            finally:
                meter.close()

    def test_empty_window_has_zero_throughput_but_no_fake_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            meter = Measurement(Path(directory), 10)
            try:
                meter.begin(10)
                result = meter.save(True)
                self.assertEqual(result['success_rps'], 0)
                self.assertIsNone(result['mean_ms'])
                self.assertIsNone(result['p95_ms'])
            finally:
                meter.close()

    def test_incomplete_window_cannot_report_valid_throughput(self):
        with tempfile.TemporaryDirectory() as directory:
            meter = Measurement(Path(directory), 10)
            try:
                meter.begin(10)
                meter.started(11)
                meter.save(False)
                result = json.loads((Path(directory) / 'measurement.json').read_text())
                self.assertFalse(result['complete'])
                self.assertIsNone(result['success_rps'])
            finally:
                meter.close()

    def test_missing_resource_collection_remains_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            result = summarize_resources(Path(directory), {'start_epoch': 10, 'end_epoch': 20}, 6, 0.5)
            self.assertFalse(result['resource_window_covered'])
            self.assertEqual(result['resource_samples'], 0)
            self.assertIsNone(result['cpu_percent_of_limit'])
            self.assertIsNone(result['memory_peak_mib'])

    def test_gaps_in_resource_collection_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            point = Path(directory)
            rows = [
                {'timestamp_utc': datetime.fromtimestamp(t, timezone.utc).isoformat(),
                 'elapsed_seconds': t, 'container_cpu_usage_usec': cpu,
                 'container_memory_bytes': 20 * 2**20, 'app_rss_bytes': 10 * 2**20,
                 'container_oom_kill': oom}
                for t, cpu, oom in ((11, 0, 0), (19, 4000000, 2))
            ]
            with (point / 'monitor.csv').open('w', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            result = summarize_resources(point, {'start_epoch': 10, 'end_epoch': 20}, 6, 0.5)
            self.assertFalse(result['resource_window_covered'])
            self.assertEqual(result['resource_max_gap_seconds'], 8)
            self.assertEqual(result['sampled_oom_kill_delta'], 2)
            self.assertAlmostEqual(result['cpu_percent_of_limit'], 100 * 4 / 8 / 6)


if __name__ == '__main__':
    unittest.main()
