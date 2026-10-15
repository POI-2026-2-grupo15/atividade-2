"""Métricas HTTP de uma janela fixa, separada da rampa e do aquecimento."""

import csv
import json
import math
from pathlib import Path
import statistics
import time


class Measurement:
    def __init__(self, output: Path, duration: float):
        self.output = output
        self.duration = duration
        self.start = None
        self.end = None
        self.started_count = 0
        self.completed_started = 0
        self.failures = 0
        self.completed = 0
        self.latencies = []
        self.success_latencies = []
        self.finalized = False
        self.file = (output / "requests.csv").open("x", newline="")
        self.writer = csv.DictWriter(self.file, fieldnames=[
            "started_epoch", "completed_epoch", "response_time_ms", "failure", "phase",
        ])
        self.writer.writeheader()
        self.file.flush()

    def begin(self, timestamp=None):
        self.start = time.time() if timestamp is None else timestamp
        self.end = self.start + self.duration
        self.save(False)

    def started(self, timestamp):
        if self.start is not None and self.start <= timestamp < self.end:
            self.started_count += 1

    def completed_request(self, started, completed, response_time, failed):
        inside = self.start is not None and self.start <= completed < self.end
        cohort = inside and started >= self.start
        phase = "measurement" if cohort else "carryover" if inside else "outside"
        self.writer.writerow({"started_epoch": started, "completed_epoch": completed,
                              "response_time_ms": response_time, "failure": int(failed), "phase": phase})
        self.file.flush()
        if inside:
            self.completed += 1
            self.failures += int(failed)
            if cohort:
                self.completed_started += 1
                self.latencies.append(response_time)
                if not failed:
                    self.success_latencies.append(response_time)

    def save(self, complete):
        self.finalized = complete
        ordered = sorted(self.latencies)
        successes = sorted(self.success_latencies)
        result = {
            "start_epoch": self.start, "end_epoch": self.end,
            "duration_seconds": self.duration, "complete": complete,
            "requests": self.completed, "failures": self.failures,
            "success_rps": (self.completed - self.failures) / self.duration if complete else None,
            "rps": self.completed / self.duration if complete else None,
            "mean_ms": statistics.mean(successes) if successes else None,
            "p95_ms": successes[math.ceil(len(successes) * 0.95) - 1] if successes else None,
            "all_mean_ms": statistics.mean(ordered) if ordered else None,
            "all_p95_ms": ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None,
            "latency_samples": len(successes), "all_latency_samples": len(ordered),
            "started_in_window": self.started_count,
            "in_flight_at_end": self.started_count - self.completed_started,
            "carryover_completed": self.completed - self.completed_started,
        }
        target = self.output / "measurement.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2) + "\n")
        temporary.replace(target)
        return result

    def close(self):
        self.file.close()
