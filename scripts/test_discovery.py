"""
Quick smoke test for the service discovery agent.
Runs a sample care request through the full graph and prints results.

Usage:
  python scripts/test_discovery.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def run_test():
    console.rule("[bold blue]Kaigo Navigator — Service Discovery Test[/bold blue]")

    # Sample care request
    request = {
        "needs_description": (
            "80歳の女性。脳卒中後の在宅療養中。"
            "週3回の訪問介護（身体介護・生活援助）と"
            "月2回の訪問看護が必要。要介護2。"
            "世田谷区在住。認知症なし、歩行困難あり。\n\n"
            "80-year-old female recovering at home after stroke. "
            "Needs home visit care 3x/week and nursing visits 2x/month. "
            "Care level 2. Mobility impaired. No dementia."
        ),
        "ward": "世田谷区",
        "patient_age": 80,
        "patient_name": "患者A",
        "care_level": 2,
    }

    console.print("\n[bold]Care Request:[/bold]")
    rprint(request)

    console.print("\n[dim]Running agent graph...[/dim]")

    from agents.orchestrator import run_care_request
    result = run_care_request(**request)

    console.print(f"\n[bold]Status:[/bold] {result.get('status')}")
    console.print(f"[bold]Service codes identified:[/bold] {result.get('required_service_codes')}")

    ranked = result.get("ranked_services", [])
    if ranked:
        table = Table(title="Ranked Services", show_lines=True)
        table.add_column("Rank", width=5)
        table.add_column("Facility", width=25)
        table.add_column("Ward", width=10)
        table.add_column("Service", width=22)
        table.add_column("Score", width=7)
        table.add_column("Reason (EN)", width=40)

        for svc in ranked[:5]:
            table.add_row(
                str(svc.get("rank", "")),
                svc.get("name", ""),
                svc.get("ward", ""),
                svc.get("service_name", ""),
                str(svc.get("match_score", "")),
                svc.get("reason_en", ""),
            )
        console.print(table)
    else:
        console.print("[yellow]No ranked services returned.[/yellow]")

    console.print("\n[bold]Agent messages:[/bold]")
    for msg in result.get("messages", []):
        console.print(f"  [{msg.get('agent')}] {msg.get('content')}")


if __name__ == "__main__":
    run_test()
