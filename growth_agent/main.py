import argparse
import csv
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from growth_agent.benchmark import benchmark
from growth_agent.config import Settings
from growth_agent.data.generator import SCENARIOS, generate_data
from growth_agent.logging_config import configure_logging
from growth_agent.models import AnalysisRequest
from growth_agent.service.pipeline import GrowthPipeline


def load_request(path: Path) -> AnalysisRequest:
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Input file exceeds 4 MiB")
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            records = list(csv.DictReader(stream))
        for row in records:
            for key in ("visitors", "new_users"):
                row[key] = int(row[key])
            row["spend"] = float(row.get("spend") or 0)
        return AnalysisRequest.model_validate({"records": records})
    return AnalysisRequest.model_validate_json(path.read_text(encoding="utf-8-sig"))


def write_json(value: dict, output: Path | None):
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    else:
        print(text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Growth Decision Agent — simulated data by default"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "analyze"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path)
        command.add_argument("--llm", action="store_true")
        if name == "analyze":
            command.add_argument("input", type=Path)
    generate = sub.add_parser("generate")
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--scenario", choices=SCENARIOS, default="mixed_drop")
    generate.add_argument("--output", type=Path, required=True)
    bench = sub.add_parser("benchmark")
    bench.add_argument("--seeds", type=int, default=20)
    bench.add_argument("--iterations", type=int, default=30)
    bench.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        configure_logging("WARNING" if args.command == "benchmark" else settings.log_level)
        if args.command == "generate":
            payload, labels = generate_data(seed=args.seed, scenario=args.scenario)
            write_json(payload, args.output)
            write_json(
                {
                    "data_kind": "synthetic",
                    "seed": args.seed,
                    "scenario": args.scenario,
                    "labels": labels,
                },
                args.output.with_suffix(".labels.json"),
            )
        elif args.command == "benchmark":
            write_json(benchmark(args.seeds, args.iterations), args.output)
        else:
            request = (
                load_request(args.input)
                if args.command == "analyze"
                else AnalysisRequest.model_validate(generate_data()[0])
            )
            if args.llm:
                request = request.model_copy(update={"use_llm": True})
            report = GrowthPipeline(settings).run(request)
            write_json(report.model_dump(mode="json"), args.output)
        return 0
    except (OSError, ValueError, KeyError, ValidationError) as exc:
        print(
            json.dumps(
                {
                    "error": "invalid_input_or_configuration",
                    "type": type(exc).__name__,
                    "hint": "Check input schema, file permissions and configuration.",
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
