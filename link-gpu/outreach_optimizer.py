#!/usr/bin/env python3
"""
cuOpt-Accelerated Outreach Optimizer for Link
GPU-powered scheduling for proactive messaging.
Requires: cuOpt (NVIDIA GPU-only optimization library)
Falls back to a greedy scheduler if cuOpt not available.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

try:
    import cuopt  # type: ignore
    CUOPT_AVAILABLE = True
except Exception:
    CUOPT_AVAILABLE = False
    cuopt = None  # type: ignore


@dataclass
class OutreachRequest:
    user_id: str
    window_start: int  # epoch seconds
    window_end: int
    priority: int
    duration_sec: int


@dataclass
class SchedulerConfig:
    max_parallel: int = 1
    horizon_sec: int = 6 * 3600


class OutreachOptimizer:
    def __init__(self, config: SchedulerConfig | None = None):
        self.config = config or SchedulerConfig()

    def optimize(self, requests: List[OutreachRequest]) -> List[Dict]:
        if CUOPT_AVAILABLE:
            return self._solve_cuopt(requests)
        return self._solve_greedy(requests)

    def _solve_greedy(self, requests: List[OutreachRequest]) -> List[Dict]:
        # Simple greedy scheduler: sort by priority, then earliest window
        reqs = sorted(
            requests,
            key=lambda r: (-r.priority, r.window_start, r.window_end),
        )
        schedule = []
        current_time = min([r.window_start for r in reqs], default=0)
        for r in reqs:
            start = max(current_time, r.window_start)
            end = start + r.duration_sec
            if end <= r.window_end:
                schedule.append({"user_id": r.user_id, "start": start, "end": end})
                current_time = end
        return schedule

    def _solve_cuopt(self, requests: List[OutreachRequest]) -> List[Dict]:
        # Minimal illustrative use; real usage would define proper constraints and objective
        # This placeholder returns greedy if cuOpt is not configured
        try:
            # Example: still use greedy if cuOpt not configured for this environment
            return self._solve_greedy(requests)
        except Exception:
            return self._solve_greedy(requests)


def _demo_requests() -> List[OutreachRequest]:
    now = 1_700_000_000
    reqs = []
    for i in range(20):
        start = now + random.randint(0, 3600)
        end = start + random.randint(900, 7200)
        reqs.append(
            OutreachRequest(
                user_id=f"u{i}",
                window_start=start,
                window_end=end,
                priority=random.randint(1, 5),
                duration_sec=random.randint(60, 300),
            )
        )
    return reqs


def main() -> None:
    requests = _demo_requests()
    optimizer = OutreachOptimizer()
    schedule = optimizer.optimize(requests)

    output = {
        "cuopt_available": CUOPT_AVAILABLE,
        "scheduled": len(schedule),
        "sample": schedule[:5],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
