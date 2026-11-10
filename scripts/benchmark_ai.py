# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
"""ULTRON AI speed benchmark.

Measures time to first word and total time per AI provider and per
response mode (Instant / Balanced / Deep), through ULTRON Core itself, and
how long a simple command takes. Run it before and after an update to
compare.

    uv run scripts/benchmark_ai.py
    uv run scripts/benchmark_ai.py --runs 5 --providers freellmapi,ollama

It signs in as you (password is asked, never stored), temporarily points
routing at one provider at a time, and restores your settings afterwards.
Each run sends a few tiny requests to each provider (free-tier quota).
Results are printed and saved to .ultron-bench/ (git-ignored).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

PROMPT = "Reply in one short sentence: what is the capital of France?"
COMMAND = "how is my pc doing"
PACE_SECONDS = 3.2  # stays under Core's default 20 messages/minute


def median(xs: list[float]) -> float | None:
    return round(statistics.median(xs)) if xs else None


class Bench:
    def __init__(self, url: str, email: str, password: str) -> None:
        self.c = httpx.Client(base_url=url.rstrip("/") + "/api/v1", timeout=300)
        r = self.c.post(
            "/auth/login",
            json={"email": email, "password": password, "device_name": "ULTRON benchmark", "platform": "windows"},
        )
        if r.status_code != 200:
            sys.exit(f"Sign-in failed ({r.status_code}): {r.text[:200]}")
        self.c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        self.refresh = r.json()["refresh_token"]
        self.supports_modes = True

    def close(self) -> None:
        try:
            self.c.post("/auth/logout")
        finally:
            self.c.close()

    def stream(self, cid: str, text: str, mode: str | None) -> dict:
        body: dict = {"content": text, "stream": True, "utc_offset_minutes": 0}
        if mode and self.supports_modes:
            body["response_mode"] = mode
        t0 = time.perf_counter()
        out: dict = {"ok": False}
        event = None
        with self.c.stream("POST", f"/conversations/{cid}/messages", json=body) as r:
            if r.status_code == 422 and mode:
                self.supports_modes = False  # older Core without response modes
                return self.stream(cid, text, None)
            if r.status_code == 429:
                time.sleep(60)
                return self.stream(cid, text, mode)
            if r.status_code != 200:
                return {"ok": False, "error": f"HTTP {r.status_code}: {r.read()[:200]!r}"}
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                    if event == "delta" and "client_first_ms" not in out:
                        out["client_first_ms"] = (time.perf_counter() - t0) * 1000
                elif line.startswith("data: ") and event in ("provider.selected", "message.completed", "error"):
                    data = json.loads(line[6:])
                    if event == "provider.selected":
                        out["provider"], out["model"] = data.get("provider"), data.get("model")
                    elif event == "message.completed":
                        m = data.get("assistant_message") or {}
                        out.update(
                            ok=True,
                            server_first_ms=m.get("first_token_ms"),
                            server_total_ms=m.get("duration_ms"),
                            provider=m.get("provider") or out.get("provider"),
                            model=m.get("model") or out.get("model"),
                        )
                    else:
                        out["error"] = data.get("message") or data.get("code")
        out["client_total_ms"] = (time.perf_counter() - t0) * 1000
        return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("ULTRON_BENCH_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--email", default=os.environ.get("ULTRON_BENCH_EMAIL"))
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--modes", default="instant,balanced,deep")
    ap.add_argument("--providers", default="", help="comma-separated; default: every ready provider")
    ap.add_argument("--label", default="", help="e.g. before / after")
    args = ap.parse_args()
    email = args.email or input("ULTRON email: ")
    password = os.environ.get("ULTRON_BENCH_PASSWORD") or getpass.getpass("ULTRON password: ")

    b = Bench(args.url, email, password)
    prefs = b.c.get("/ai/preferences").json()
    status = b.c.get("/ai/status").json()
    ready = [p for p in status["providers"] if p["status"] == "ready"]
    wanted = [n.strip() for n in args.providers.split(",") if n.strip()]
    targets = [p for p in ready if not wanted or p["name"] in wanted]
    if not targets:
        sys.exit("No ready AI provider to measure (check System -> AI sources).")
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    restore = {k: prefs[k] for k in ("mode", "cloud_order", "private_by_default") if k in prefs}
    for k in ("memory_enabled", "memory_saving_paused", "time_format", "address_as", "response_mode"):
        if k in prefs:
            restore[k] = prefs[k]
    cid = b.c.post("/conversations", json={"title": "ULTRON benchmark", "is_private": False}).json()["id"]
    results: list[dict] = []
    try:
        # A simple command: should never need an AI model.
        times = []
        for _ in range(args.runs):
            t0 = time.perf_counter()
            r = b.c.post("/assistant/command", json={"text": COMMAND})
            times.append((time.perf_counter() - t0) * 1000)
        results.append({"what": f'command "{COMMAND}"', "median_ms": median(times), "status": r.status_code})
        times = []
        for _ in range(args.runs):
            out = b.stream(cid, COMMAND, None)
            times.append(out.get("client_first_ms") or out["client_total_ms"])
            time.sleep(PACE_SECONDS)
        results.append({"what": f'chat "{COMMAND}"', "median_ms": median(times), "via": out.get("provider")})

        # Your normal routing first (what you really get), then each provider alone.
        for p in [{"name": "(routing)", "kind": "auto"}, *targets]:
            if p["kind"] == "auto":
                routing = {}
            elif p["kind"] == "local":
                routing = {"mode": "local_only"}
            else:
                routing = {"mode": "cloud_only", "cloud_order": [p["name"]]}
            b.c.put("/ai/preferences", json={**restore, **routing})
            for mode in modes if b.supports_modes else ["(no modes)"]:
                runs = []
                for _ in range(args.runs):
                    runs.append(b.stream(cid, PROMPT, None if mode.startswith("(") else mode))
                    time.sleep(PACE_SECONDS)
                ok = [x for x in runs if x.get("ok")]
                results.append(
                    {
                        "provider": p["name"],
                        "mode": mode,
                        "ok": f"{len(ok)}/{len(runs)}",
                        "first_word_ms": median([x["client_first_ms"] for x in ok if "client_first_ms" in x]),
                        "total_ms": median([x["client_total_ms"] for x in ok]),
                        "server_first_word_ms": median([x["server_first_ms"] for x in ok if x.get("server_first_ms")]),
                        "answered_by": sorted({f"{x.get('provider')}/{x.get('model')}" for x in ok}),
                        "errors": sorted({x["error"] for x in runs if x.get("error")}),
                    }
                )
                print(json.dumps(results[-1]), flush=True)
    finally:
        b.c.put("/ai/preferences", json=restore)
        b.c.delete(f"/conversations/{cid}")
        b.close()

    print("\nULTRON benchmark", args.label, datetime.now().strftime("%Y-%m-%d %I:%M %p"))
    for r in results[:2]:
        print(f"  {r['what']:<34} {r['median_ms']} ms")
    print(f"  {'provider':<12} {'mode':<10} {'ok':<5} {'first word':>11} {'total':>9}  answered by")
    for r in results[2:]:
        fw = f"{r['first_word_ms']} ms" if r["first_word_ms"] is not None else "-"
        tt = f"{r['total_ms']} ms" if r["total_ms"] is not None else "-"
        print(f"  {r['provider']:<12} {r['mode']:<10} {r['ok']:<5} {fw:>11} {tt:>9}  {', '.join(r['answered_by'])}")
        for e in r["errors"]:
            print(f"      error: {e}")
    out_dir = Path(__file__).resolve().parents[1] / ".ultron-bench"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"benchmark-{args.label or 'run'}-{datetime.now():%Y%m%d-%H%M}.json"
    path.write_text(json.dumps({"label": args.label, "url": args.url, "results": results}, indent=2))
    print(f"\nSaved {path}")


if __name__ == "__main__":
    main()
