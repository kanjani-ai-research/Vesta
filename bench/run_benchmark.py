"""Query benchmark: precision/recall + latency of uses() against Vesta's own
repository, scored against ground truth read independently in ground_truth.py.

Run: .venv/bin/python bench/run_benchmark.py
Writes bench/results.json and prints a summary table.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vesta.graph import Graph  # noqa: E402
from vesta.held import graph_for  # noqa: E402
from vesta.sidecar import _matching  # noqa: E402

from ground_truth import REPO, TARGETS, find_true_callers  # noqa: E402


def query(graph: Graph, name: str) -> tuple[list[str], float]:
    """What uses() would report as callers, and how long it took — calling
    the REAL vesta.sidecar._matching directly (not a reimplementation), so a
    fix or regression in the actual production code path is what this
    benchmark measures, not a hand-copy of it that can drift out of sync."""
    started = time.perf_counter()
    found = _matching(graph, name)
    reported: list[str] = []
    for node in found:
        for edge in graph.referenced_by(node.id):
            other = graph.nodes.get(edge.source)
            if other is not None:
                reported.append(f"{other.path}::{other.qualified}")
    took = time.perf_counter() - started
    return sorted(set(reported)), took


def score(reported: list[str], truth: set[str]) -> dict:
    reported_set = set(reported)
    correct = reported_set & truth
    precision = len(correct) / len(reported_set) if reported_set else (1.0 if not truth else 0.0)
    recall = len(correct) / len(truth) if truth else (1.0 if not reported_set else 0.0)
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "reported": sorted(reported_set),
        "true": sorted(truth),
        "missed": sorted(truth - reported_set),
        "spurious": sorted(reported_set - truth),
    }


def main() -> int:
    print(f"Building graph for {REPO} ...")
    build_started = time.perf_counter()
    graph = graph_for(REPO, rebuild=True)
    build_took = time.perf_counter() - build_started
    print(f"  {graph.describe()}  (built in {build_took:.2f}s)")
    print()

    results = []
    latencies = []
    for target in TARGETS:
        truth = find_true_callers(target)
        # target.qualified, not target.name: a bare name that is genuinely
        # ambiguous across the repo (main appears ~14 times) is meant to be
        # asked disambiguated, the way a real user hitting that ambiguity
        # would — querying the bare form here silently mixed in every OTHER
        # file's own main() as "reported," which was this benchmark's own
        # bug, not Vesta's (confirmed: querying "instead.main" directly
        # resolves to exactly the one real node).
        reported, took = query(graph, target.qualified)
        latencies.append(took)
        s = score(reported, truth)
        s.update({"name": target.name, "qualified": target.qualified,
                  "kind": target.kind, "latency_ms": round(took * 1000, 3)})
        results.append(s)
        flag = "" if s["precision"] == 1.0 and s["recall"] == 1.0 else "  <-- MISMATCH"
        print(f"{target.qualified:30s} truth={len(truth):3d}  reported={len(s['reported']):3d}  "
              f"P={s['precision']:.2f}  R={s['recall']:.2f}  {took*1000:.2f}ms{flag}")

    latencies.sort()
    n = len(latencies)
    p50 = latencies[n // 2] if n else 0.0
    p95 = latencies[min(n - 1, int(n * 0.95))] if n else 0.0
    mean_p = sum(r["precision"] for r in results) / len(results)
    mean_r = sum(r["recall"] for r in results) / len(results)

    summary = {
        "repo": str(REPO),
        "graph": graph.describe(),
        "graph_build_seconds": round(build_took, 3),
        "n_queries": len(results),
        "mean_precision": round(mean_p, 3),
        "mean_recall": round(mean_r, 3),
        "latency_p50_ms": round(p50 * 1000, 3),
        "latency_p95_ms": round(p95 * 1000, 3),
        "results": results,
    }

    out = Path(__file__).resolve().parent / "results.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    print(f"mean precision={mean_p:.3f}  mean recall={mean_r:.3f}")
    print(f"latency p50={p50*1000:.2f}ms  p95={p95*1000:.2f}ms")
    print(f"written to {out}")

    mismatches = [r for r in results if r["precision"] < 1.0 or r["recall"] < 1.0]
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
