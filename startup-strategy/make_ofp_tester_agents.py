#!/usr/bin/env python3
"""Generate an OFP tester agent file for all startup-strategy services.

This writes JSON in the harness format:
[
  {"url": "http://localhost:8199/", "conversationalName": "Startup Strategy Convener"},
  ...
]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


STARTUP_AGENTS = [
    ("Startup Strategy Convener", 8199),
    ("Market Validator", 8200),
    ("Competitive Intelligence", 8201),
    ("Business Model Designer", 8202),
    ("Risk Identifier", 8203),
    ("Funding Strategist", 8204),
    ("Workforce Strategist", 8205),
    ("Devil's Advocate", 8206),
    ("Strategy Synthesizer", 8207),
]


def default_output_path() -> Path:
    """Prefer writing directly to the web-floor harness if that repo exists."""
    github_dir = Path(__file__).resolve().parents[1].parent
    candidate = github_dir / "floor-implementations" / "implementations" / "web-floor" / "harness" / "load_agents_startup_strategy.json"
    if candidate.parent.exists():
        return candidate
    return Path(__file__).resolve().with_name("load_agents_startup_strategy.json")


def build_agents(host: str, scheme: str = "http") -> list[dict[str, str]]:
    return [
        {
            "url": f"{scheme}://{host}:{port}/",
            "conversationalName": name,
        }
        for name, port in STARTUP_AGENTS
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate OFP tester load-agents JSON for startup-strategy agents")
    parser.add_argument("--host", default="localhost", help="Host or IP used in generated URLs (default: localhost)")
    parser.add_argument("--scheme", default="http", choices=["http", "https"], help="URL scheme (default: http)")
    parser.add_argument(
        "--out",
        default=str(default_output_path()),
        help="Output JSON path (default: harness load_agents_startup_strategy.json if available)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.out).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = build_agents(host=args.host, scheme=args.scheme)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote {len(payload)} startup agents to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
