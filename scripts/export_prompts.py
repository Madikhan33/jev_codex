"""Render reviewable documentation from the exact executable TOML catalog."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from jev_router.catalog import load_catalog


def main() -> None:
    catalog = load_catalog()
    prompts = catalog["routing"]
    text = [
        "# Jev classification catalog\n",
        "Generated from `jev_router/prompts/*.toml` and the builders in `questions.py`. "
        "These are authored classification criteria, not measured Jev results.\n",
        "## Work-product scope\n",
        prompts["scope"] + "\n",
    ]
    for key, row in catalog["categories"].items():
        text.extend(
            [
                f"## {key} — {row['title']}\n",
                f"Domain: `{row['domain']}`. Ownership group: `{row['owner']}`.\n",
                "**Question**\n\n" + row["question"] + "\n",
                "**True**\n\n" + row["yes"] + "\n",
                "**False**\n\n" + row["no"] + "\n",
                "**Positive examples**\n\n"
                + "\n".join("- " + x for x in row["positive_examples"])
                + "\n",
                "**Negative examples**\n\n"
                + "\n".join("- " + x for x in row["negative_examples"])
                + "\n",
                "**Profile calibration**\n\n" + row["profile_notes"] + "\n",
            ]
        )
    text.append(
        "## Model-profile criteria\n\nOnly accepted work types receive these Choice questions. The definitions are a configurable policy, not model benchmarking.\n"
    )
    for key, row in catalog["profiles"].items():
        text.append(
            f"### {key}\n\nModel: `{row['model']}`. Effort: `{row['effort']}`. Merge rank: `{row['rank']}`.\n\n{row['criterion']}\n"
        )
    text.append("### needs_context\n\n" + prompts["profile"]["needs_context"] + "\n")
    text.append(
        "### Profile decision\n\n"
        + prompts["profile"]["question"]
        + "\n\n"
        + prompts["profile"]["decision_basis"]
        + "\n"
    )
    for name, title in (("intent", "Request intent"), ("coordination", "Execution structure")):
        text.append(f"## {title}\n\n{prompts[name]['question']}\n")
        text.extend(f"**{key}**: {value}\n" for key, value in prompts[name]["criteria"].items())
    uncovered = prompts["uncovered"]
    text.append(
        f"## Uncovered work\n\n{uncovered['question']}\n\n**True**: {uncovered['yes']}\n\n**False**: {uncovered['no']}\n"
    )
    (ROOT / "docs" / "PROMPTS.md").write_text("\n".join(text), encoding="utf-8")


if __name__ == "__main__":
    main()
