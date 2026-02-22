#!/usr/bin/env python3
"""
RAPIDS-Accelerated User Intelligence for Link
GPU-powered real-time analytics on every conversation.

Requires: pip install cudf-cu12 cuml-cu12 (or appropriate CUDA version)
Falls back to pandas/sklearn if RAPIDS unavailable.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import cudf  # type: ignore
    from cuml.cluster import KMeans  # type: ignore
    from cuml.preprocessing import StandardScaler  # type: ignore
    RAPIDS_AVAILABLE = True
except Exception:
    RAPIDS_AVAILABLE = False
    cudf = None  # type: ignore
    KMeans = None  # type: ignore
    StandardScaler = None  # type: ignore

try:
    import pandas as pd  # type: ignore
    import numpy as np  # type: ignore
    from sklearn.cluster import KMeans as SKKMeans  # type: ignore
    from sklearn.preprocessing import StandardScaler as SKScaler  # type: ignore
except Exception as e:
    raise RuntimeError("pandas/numpy/sklearn required for CPU fallback") from e


@dataclass
class FeatureConfig:
    n_clusters: int = 8
    min_rows: int = 25
    max_rows: int = 250_000


class RapidsIntelligence:
    def __init__(self, config: FeatureConfig | None = None):
        self.config = config or FeatureConfig()

    def _to_dataframe(self, rows: List[Dict]):
        if RAPIDS_AVAILABLE:
            return cudf.DataFrame(rows)
        return pd.DataFrame(rows)

    def extract_features(self, rows: List[Dict]) -> Tuple[Dict[str, float], List[Dict]]:
        """
        Extracts aggregate and per-row features for clustering and trend detection.
        Expected row keys: user_id, msg_len, response_time_sec, sentiment, topic_id, hour
        """
        if not rows:
            return {}, []
        if len(rows) > self.config.max_rows:
            rows = rows[-self.config.max_rows :]

        df = self._to_dataframe(rows)
        numeric_cols = ["msg_len", "response_time_sec", "sentiment", "topic_id", "hour"]
        for col in numeric_cols:
            if col not in df.columns:
                df[col] = 0

        if RAPIDS_AVAILABLE:
            stats = {
                "avg_msg_len": float(df["msg_len"].mean()),
                "avg_response_time": float(df["response_time_sec"].mean()),
                "avg_sentiment": float(df["sentiment"].mean()),
            }
            enriched = df.to_pandas().to_dict("records")
        else:
            stats = {
                "avg_msg_len": float(df["msg_len"].mean()),
                "avg_response_time": float(df["response_time_sec"].mean()),
                "avg_sentiment": float(df["sentiment"].mean()),
            }
            enriched = df.to_dict("records")
        return stats, enriched

    def cluster_users(self, rows: List[Dict]) -> Dict[str, int]:
        """
        Clusters users by behavior, returning {user_id: cluster_id}.
        """
        if len(rows) < self.config.min_rows:
            return {}

        df = self._to_dataframe(rows)
        numeric_cols = ["msg_len", "response_time_sec", "sentiment", "topic_id", "hour"]
        X = df[numeric_cols]

        if RAPIDS_AVAILABLE:
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            model = KMeans(n_clusters=self.config.n_clusters, random_state=42)
            labels = model.fit_predict(X_scaled)
            df["cluster_id"] = labels
            output = df[["user_id", "cluster_id"]].to_pandas().to_dict("records")
        else:
            scaler = SKScaler()
            X_scaled = scaler.fit_transform(X)
            model = SKKMeans(n_clusters=self.config.n_clusters, random_state=42, n_init="auto")
            labels = model.fit_predict(X_scaled)
            df["cluster_id"] = labels
            output = df[["user_id", "cluster_id"]].to_dict("records")

        result: Dict[str, int] = {}
        for row in output:
            result[str(row["user_id"])] = int(row["cluster_id"])
        return result

    def detect_anomalies(self, rows: List[Dict]) -> List[Dict]:
        """
        Very simple anomaly detector based on z-score of response time and sentiment.
        """
        if not rows:
            return []
        df = self._to_dataframe(rows)
        for col in ["response_time_sec", "sentiment"]:
            if col not in df.columns:
                df[col] = 0

        if RAPIDS_AVAILABLE:
            resp = df["response_time_sec"].to_pandas()
            sent = df["sentiment"].to_pandas()
            anomalies = []
            for i, r in enumerate(resp):
                z = (r - resp.mean()) / (resp.std() + 1e-6)
                s = sent.iloc[i]
                if abs(z) > 3 or s < -0.8:
                    anomalies.append(df.iloc[i].to_pandas().to_dict())
            return anomalies
        else:
            resp = df["response_time_sec"]
            sent = df["sentiment"]
            anomalies = []
            resp_mean = resp.mean()
            resp_std = resp.std() + 1e-6
            for i, r in enumerate(resp):
                z = (r - resp_mean) / resp_std
                s = sent.iloc[i]
                if abs(z) > 3 or s < -0.8:
                    anomalies.append(df.iloc[i].to_dict())
            return anomalies


def _demo_rows() -> List[Dict]:
    import random
    rows = []
    for i in range(200):
        rows.append(
            {
                "user_id": f"u{i%20}",
                "msg_len": random.randint(3, 200),
                "response_time_sec": random.random() * 120,
                "sentiment": random.uniform(-1, 1),
                "topic_id": random.randint(0, 9),
                "hour": random.randint(0, 23),
            }
        )
    return rows


def main() -> None:
    rows = _demo_rows()
    intel = RapidsIntelligence()
    stats, _ = intel.extract_features(rows)
    clusters = intel.cluster_users(rows)
    anomalies = intel.detect_anomalies(rows)

    output = {
        "rapids_available": RAPIDS_AVAILABLE,
        "stats": stats,
        "cluster_count": len(set(clusters.values())) if clusters else 0,
        "anomaly_count": len(anomalies),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
