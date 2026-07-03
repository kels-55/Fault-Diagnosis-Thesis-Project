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

DIVIDER      = "=" * 60
THIN_DIVIDER = "-" * 60

def _fmt_value(expected: bool) -> str:
    # Under new semantics: True = faulty/abnormal state
    return "off / 0V / low" if expected else "on / 12V / high"

def _fmt_fault_set(fault_nodes: frozenset[str]) -> str:
    """Format a fault set for display."""
    if not fault_nodes:
        return "all-ok"
    return " + ".join(sorted(fault_nodes))

def _print_header(scenario: Scenario, kripke: KripkeModel) -> None:
    print(DIVIDER)
    print(f"  Scenario {scenario.id}: {scenario.description}")
    print(f"  Agent   : {scenario.agent_name}")
    tools = scenario.tools_in_hand or ["(none)"]
    print(f"  Tools   : {', '.join(tools)}")
    # show max_faults 
    print(f"  Max simultaneous faults: {scenario.max_faults}")
    print(THIN_DIVIDER)
    print(f"  Initial worlds ({len(kripke.worlds)}):")
    labels = [w.label() for w in kripke.worlds]
    for i in range(0, len(labels), 3):
        print("    " + "  ".join(f"{l:30s}" for l in labels[i:i + 3]))
    print(DIVIDER)

def _print_step(result: StepResult) -> None:
    print(f"\n── Announcement {result.step} ──────────────────────────────")
    print("  Observations announced:")
    for ax in result.axioms:
        print(f"    {ax.observable:25s} = {_fmt_value(ax.expected_value)}")

    print(f"\n  Worlds before : {len(result.worlds_before)}")
    if result.pruned_worlds:
        print(f"  Pruned ({len(result.pruned_worlds):2d})   :", end="")
        for i, w in enumerate(result.pruned_worlds):
            if i % 2 == 0:
                print(f"\n    ", end="")
            print(f"{w.label():35s}", end="")
        print()
    else:
        print("  Pruned (0)    : (none)")

    print(f"  Worlds after  : {len(result.worlds_after)}")

    if result.is_contradiction:
        print("\n  ⚠  CONTRADICTION — no worlds survive.")
        print("     This may indicate an error in the scenario observations")
        print("     or an inconsistency in the circuit model.")
    elif result.is_resolved:
        label = _fmt_fault_set(result.surviving_faults[0])
        print(f"\n  ✓  RESOLVED — only one world remains.")
        print(f"     Fault(s) identified: {label}")
    else:
        print(f"\n  ?  Ambiguous — {len(result.surviving_faults)} fault candidates remain:")
        for i in range(0, len(result.surviving_faults), 2):
            row = result.surviving_faults[i:i + 2]
            print("    " + "  ".join(f"{_fmt_fault_set(fs):35s}" for fs in row))

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
        label = _fmt_fault_set(final.surviving_faults[0])
        print(f"  Result : UNIQUE DIAGNOSIS")
        print(f"  Fault  : {label}")
        print(f"  Resolved after {len(results)} announcement(s) "
              f"out of {len(scenario.announcements)} total.")

    else:
        print(f"  Result : AMBIGUOUS  ({len(final.surviving_faults)} candidates remain)")
        print("  Remaining fault candidates:")
        for fs in final.surviving_faults:
            print(f"    {_fmt_fault_set(fs)}")
        print()
        print("  The available observations were insufficient to uniquely")
        print("  identify the fault. More observations or tools may be needed.")

    print(DIVIDER)

# core runner functions

def run_scenario(
    scenario: Scenario,
    yaml_path: str,
    validate: bool = True,
) -> list[StepResult]:
    model, _ = load_circuit(yaml_path)
    # ── NEW: pass scenario.max_faults to build_kripke_model ──────────────
    kripke = build_kripke_model(model, include_all_ok=True, max_faults=scenario.max_faults)
    engine = AxiomEngine(model)
    processor = AnnouncementProcessor(kripke, engine, scenario, validate=validate)

    _print_header(scenario, kripke)
    results = processor.run()
    for result in results:
        _print_step(result)
    _print_final_diagnosis(results, scenario)
    return results

# interactive menu

def _scenario_menu(scenarios: list[Scenario]) -> Scenario:
    print(DIVIDER)
    print("  DEL Fault Diagnosis System")
    print(THIN_DIVIDER)
    print("  Available scenarios:\n")
    print(f"  {'ID':>4}  {'Steps':>5}  {'MaxF':>4}  {'Agent':<30}  Description")
    print(f"  {'--':>4}  {'-----':>5}  {'----':>4}  {'-----':<30}  -----------")
    for s in scenarios:
        print(
            f"  {s.id:>4}  {len(s.announcements):>5}  {s.max_faults:>4}  "
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

# CLI

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="DEL-based fault diagnosis for electrical circuits.",
    )
    parser.add_argument("--yaml", default="circuit.yaml", metavar="FILE")
    parser.add_argument("--scenario", type=int, default=None, metavar="ID")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    return parser.parse_args()

def main() -> None:
    args = _parse_args()
    validate = not args.no_validate

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

    if args.all:
        print(f"Running all {len(scenarios)} scenario(s)...\n")
        for scenario in scenarios:
            run_scenario(scenario, args.yaml, validate=validate)
            print()
        return

    if args.scenario is not None:
        scenario = next((s for s in scenarios if s.id == args.scenario), None)
        if scenario is None:
            valid_ids = [str(s.id) for s in scenarios]
            print(f"Error: scenario ID {args.scenario} not found. Available: {', '.join(valid_ids)}")
            sys.exit(1)
        run_scenario(scenario, args.yaml, validate=validate)
        return

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
