"""Loopback-only concurrent HTTP check of staging's shared read quota."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import statistics
import time
from urllib.parse import urlparse
import httpx


def run(base_url: str, requests: int = 300, workers: int = 24) -> dict:
    parsed = urlparse(base_url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.scheme != "http":
        raise ValueError("The staging load test accepts only a loopback HTTP URL")

    def probe(index: int):
        started = time.perf_counter()
        headers = {"X-SmartHedge-Client-IP": f"198.51.100.{index % 250 + 1}",
                   "X-Forwarded-For": f"203.0.113.{index % 250 + 1}"}
        with httpx.Client(timeout=15) as client:
            response = client.get(base_url.rstrip("/") + "/api/v1/health", headers=headers)
        return response.status_code, (time.perf_counter() - started) * 1000

    start_window = int(time.time() // 60)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(probe, range(requests)))
    if int(time.time() // 60) != start_window:
        raise RuntimeError("Load crossed a rate-limit minute boundary; rerun for a comparable result")
    counts = Counter(status for status, _ in results)
    latencies = sorted(ms for _, ms in results)
    result = {"requests": requests, "workers": workers, "status_counts": dict(counts),
              "p50_ms": round(statistics.median(latencies)),
              "p95_ms": round(latencies[int(0.95 * (len(latencies) - 1))])}
    if any(status not in {200, 429} for status in counts) or counts[200] > 240 or counts[429] == 0:
        raise AssertionError(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    print(json.dumps(run(args.base_url, args.requests, args.workers), sort_keys=True))
