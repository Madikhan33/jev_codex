"""CLI dispatch. Hook startup does not import the installer or the TypeSafe SDK."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jev-codex")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("hook", "doctor", "configure"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path)

    classify = commands.add_parser("classify", help="Classify text using the TypeSafe API")
    classify.add_argument("prompt", nargs="?")
    classify.add_argument("--context", default="")
    classify.add_argument("--top-k", type=int)
    classify.add_argument("--config", type=Path)

    prompts = commands.add_parser("prompts", help="Print actual Jev questions without API calls")
    prompts.add_argument("--stage", choices=("detection", "profiles"), default="detection")
    prompts.add_argument("--category", action="append", default=[])
    prompts.add_argument("--config", type=Path)
    session = commands.add_parser("session", help="Task context and reported dispatch lifecycle")
    session.add_argument(
        "action",
        choices=(
            "enable",
            "disable",
            "show",
            "save",
            "clear",
            "route",
            "plan",
            "record",
            "trace",
            "research",
            "message",
        ),
    )
    session.add_argument("--session-id")
    session.add_argument("--project")
    session.add_argument("--turn-id")
    session.add_argument("--expected-revision", type=int)
    session.add_argument("--config", type=Path)
    commands.add_parser("install", add_help=False)
    commands.add_parser("uninstall", add_help=False)
    return parser


def print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def classify_command(args: argparse.Namespace, settings: dict[str, Any]) -> int:
    from .catalog import load_catalog
    from .routing import classify
    from .sdk import JevTransport
    from .settings import catalog_directory, get_api_key

    catalog = load_catalog(catalog_directory(settings))
    prompt = args.prompt if args.prompt is not None else sys.stdin.read()
    policy = catalog["policy"]
    with JevTransport(
        get_api_key(settings),
        model=policy["jev_model"],
        timeout=policy["request_timeout_seconds"],
    ) as transport:
        result = classify(
            prompt, transport, context=args.context, top_k=args.top_k, catalog=catalog
        )
    print_json(result)
    return 0


def prompts_command(args: argparse.Namespace, settings: dict[str, Any]) -> int:
    from .catalog import load_catalog
    from .questions import detection_questions, profile_questions
    from .settings import catalog_directory

    catalog = load_catalog(catalog_directory(settings))
    selected = list(dict.fromkeys(args.category))
    unknown = set(selected) - set(catalog["categories"])
    if unknown:
        print("Unknown category; see jev_router/prompts/domains.toml.", file=sys.stderr)
        return 1
    if args.stage == "profiles":
        if not selected:
            print("Profile preview requires at least one --category.", file=sys.stderr)
            return 1
        questions = profile_questions(catalog, selected)
    else:
        questions = detection_questions(catalog)
        if selected:
            questions = {f"work.{name}": questions[f"work.{name}"] for name in selected}
    print_json(questions)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch a command; provider errors never expose raw request/response bodies."""
    parser = build_parser()
    args, extras = parser.parse_known_args(argv)
    if args.command in {"install", "uninstall"}:
        from .installer import main as install_main

        options = ["--uninstall"] if args.command == "uninstall" else []
        return install_main(options + extras)
    if extras:
        parser.error("unrecognized arguments: " + " ".join(extras))
    if args.command == "hook":
        from .hook import main as hook_main

        return hook_main(args.config)

    from .settings import configure_credentials, read_settings

    try:
        settings = read_settings(args.config)
        if args.command == "configure":
            return configure_credentials(args.config, settings)
        if args.command == "doctor":
            from .diagnostics import inspect_installation

            checks, is_ready = inspect_installation(args.config, settings)
            print_json(checks)
            return 0 if is_ready else 1
        if args.command == "prompts":
            return prompts_command(args, settings)
        if args.command == "session":
            from .session_commands import session_command

            print_json(session_command(args, settings))
            return 0
        return classify_command(args, settings)
    except Exception as error:
        # SDK exceptions may contain credentials or submitted text. Keep the
        # public diagnostic bounded; doctor exposes individual local checks.
        print(
            f"Router failed ({type(error).__name__}). Run doctor to check local setup; "
            "check input, API credentials and connectivity if local checks pass.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130
