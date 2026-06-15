# main.py
# Entry point for the DEL-based fault diagnosis system.
#
# Usage:
#   python main.py                        # interactive scenario menu
#   python main.py --scenario 7           # run scenario 7 directly
#   python main.py --yaml path/to/file    # use a different circuit file
#   python main.py --all                  # run all scenarios in sequence
#   python main.py --no-validate          # skip agent observability checks

import argparse
import sys
from loader import load_circuit
from translator import build_kripke_model, AxiomEngine
from announcer import AnnouncementProcessor, StepResult
from classes import Scenario, KripkeModel


# ─────────────────────────────────────────────────────────────────────────────
# Display helpers
# ─────────────────────────────────────────────────────────────────────────────

DIVIDER      = "=" * 60
THIN_DIVIDER = "-" * 60


def _fmt_value(expected: bool) -> str:
    return "on / 12V / high" if expected else "off / 0V / low"


def _print_header(scenario: Scenario, kripke: KripkeModel) -> None:
    print(DIVIDER)
    print(f"  Scenario {scenario.id}: {scenario.description}")
    print(f"  Agent   : {scenario.agent_name}")
    tools = scenario.tools_in_hand or ["(none)"]
    print(f"  Tools   : {', '.join(tools)}")
    print(THIN_DIVIDER)
    fault_names = [w.fault_node for w in kripke.worlds if w.fault_node]
    print(f"  Initial worlds ({len(kripke.worlds)}): one per fault node")
    # Print in rows of 4 for readability
    for i in range(0, len(fault_names), 4):
        print("    " + "  ".join(fault_names[i:i + 4]))
    print(DIVIDER)


def _print_step(result: StepResult) -> None:
    print(f"\n── Announcement {result.step} ──────────────────────────────")
    print("  Observations announced:")
    for ax in result.axioms:
        print(f"    {ax.observable:25s} = {_fmt_value(ax.expected_value)}")

    print(f"\n  Worlds before : {len(result.worlds_before)}")
    if result.pruned_worlds:
        pruned_names = [w.fault_node or "all-ok" for w in result.pruned_worlds]
        # Print in rows of 4
        print(f"  Pruned ({len(result.pruned_worlds):2d})   :", end="")
        for i, name in enumerate(pruned_names):
            if i % 4 == 0:
                print(f"\n    ", end="")
            print(f"{name:20s}", end="")
        print()
    else:
        print("  Pruned (0)    : (none)")

    print(f"  Worlds after  : {len(result.worlds_after)}")

    if result.is_contradiction:
        print("\n  ⚠  CONTRADICTION — no worlds survive.")
        print("     This may indicate an error in the scenario observations")
        print("     or an inconsistency in the circuit model.")
    elif result.is_resolved:
        fault = result.surviving_faults[0] or "all-ok"
        print(f"\n  ✓  RESOLVED — only one world remains.")
        print(f"     Fault identified: {fault}")
    else:
        survivors = [f or "all-ok" for f in result.surviving_faults]
        print(f"\n  ?  Ambiguous — {len(survivors)} fault candidates remain:")
        for i in range(0, len(survivors), 4):
            print("    " + "  ".join(f"{s:20s}" for s in survivors[i:i + 4]))


def _print_final_diagnosis(results: list[StepResult], scenario: Scenario) -> None:
    print(f"\n{DIVIDER}")
    print(f"  FINAL DIAGNOSIS  (Scenario {scenario.id})")
    print(THIN_DIVIDER)

    if not results:
        print("  No steps were processed.")
        print(DIVIDER)
        return

    final = results[-1]

    if final.is_contradiction:
        print("  Result : CONTRADICTION")
        print("  No consistent fault hypothesis survived all announcements.")
        print("  Check the scenario observations for inconsistencies.")

    elif final.is_resolved:
        fault = final.surviving_faults[0] or "all-ok"
        print(f"  Result : UNIQUE DIAGNOSIS")
        print(f"  Fault  : {fault}")
        steps_needed = len(results)
        print(f"  Resolved after {steps_needed} announcement(s) "
              f"out of {len(scenario.announcements)} total.")

    else:
        survivors = [f or "all-ok" for f in final.surviving_faults]
        print(f"  Result : AMBIGUOUS  ({len(survivors)} candidates remain)")
        print("  Remaining fault candidates:")
        for i in range(0, len(survivors), 4):
            print("    " + "  ".join(f"{s:20s}" for s in survivors[i:i + 4]))
        print()
        print("  The available observations were insufficient to uniquely")
        print("  identify the fault. More observations or tools may be needed.")

    print(DIVIDER)


# ─────────────────────────────────────────────────────────────────────────────
# Core runner
# ─────────────────────────────────────────────────────────────────────────────

def run_scenario(
    scenario: Scenario,
    yaml_path: str,
    validate: bool = True,
) -> list[StepResult]:
    """
    Load the circuit, build the Kripke model, and run all announcements
    for the given scenario. Prints step-by-step output and a final diagnosis.

    Returns the list of StepResults for programmatic use.
    """
    # Load model fresh for each scenario so worlds are not shared between runs
    model, _ = load_circuit(yaml_path)
    kripke = build_kripke_model(model, include_all_ok=False)
    engine = AxiomEngine(model)
    processor = AnnouncementProcessor(kripke, engine, scenario, validate=validate)

    _print_header(scenario, kripke)

    results = processor.run()

    for result in results:
        _print_step(result)

    _print_final_diagnosis(results, scenario)

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Interactive scenario menu
# ─────────────────────────────────────────────────────────────────────────────

def _scenario_menu(scenarios: list[Scenario]) -> Scenario:
    """Prompt the user to pick a scenario and return it."""
    print(DIVIDER)
    print("  DEL Fault Diagnosis System")
    print(THIN_DIVIDER)
    print("  Available scenarios:\n")
    print(f"  {'ID':>4}  {'Steps':>5}  {'Agent':<30}  Description")
    print(f"  {'--':>4}  {'-----':>5}  {'-----':<30}  -----------")
    for s in scenarios:
        print(
            f"  {s.id:>4}  {len(s.announcements):>5}  "
            f"{s.agent_name:<30}  {s.description}"
        )
    print(DIVIDER)

    while True:
        try:
            raw = input("  Enter scenario ID (or 'q' to quit): ").strip()
            if raw.lower() in ("q", "quit", "exit"):
                print("  Exiting.")
                sys.exit(0)
            sid = int(raw)
            match = next((s for s in scenarios if s.id == sid), None)
            if match is None:
                valid_ids = [str(s.id) for s in scenarios]
                print(f"  Invalid ID. Choose from: {', '.join(valid_ids)}")
                continue
            return match
        except ValueError:
            print("  Please enter a valid integer ID.")
        except (EOFError, KeyboardInterrupt):
            print("\n  Interrupted. Exiting.")
            sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────
# CLI argument parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="DEL-based fault diagnosis for electrical circuits.",
    )
    parser.add_argument(
        "--yaml",
        default="circuit.yaml",
        metavar="FILE",
        help="Path to the circuit YAML file (default: circuit.yaml).",
    )
    parser.add_argument(
        "--scenario",
        type=int,
        default=None,
        metavar="ID",
        help="Run a specific scenario by ID without the interactive menu.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all scenarios in sequence.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip agent observability validation for announcements.",
    )
    return parser.parse_args()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()
    validate = not args.no_validate

    # Load scenarios (model is reloaded per run_scenario call)
    try:
        _, scenarios = load_circuit(args.yaml)
    except FileNotFoundError:
        print(f"Error: circuit file '{args.yaml}' not found.")
        sys.exit(1)
    except ValueError as e:
        print(f"Error loading circuit: {e}")
        sys.exit(1)

    if not scenarios:
        print("No scenarios found in the circuit file.")
        sys.exit(1)

    # ── Run all scenarios ─────────────────────────────────────────────────
    if args.all:
        print(f"Running all {len(scenarios)} scenario(s)...\n")
        for scenario in scenarios:
            run_scenario(scenario, args.yaml, validate=validate)
            print()
        return

    # ── Run a specific scenario by ID ─────────────────────────────────────
    if args.scenario is not None:
        scenario = next((s for s in scenarios if s.id == args.scenario), None)
        if scenario is None:
            valid_ids = [str(s.id) for s in scenarios]
            print(
                f"Error: scenario ID {args.scenario} not found. "
                f"Available: {', '.join(valid_ids)}"
            )
            sys.exit(1)
        run_scenario(scenario, args.yaml, validate=validate)
        return

    # ── Interactive menu ──────────────────────────────────────────────────
    while True:
        scenario = _scenario_menu(scenarios)
        run_scenario(scenario, args.yaml, validate=validate)
        print()
        try:
            again = input("  Run another scenario? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Exiting.")
            break
        if again not in ("y", "yes"):
            break


if __name__ == "__main__":
    main()
