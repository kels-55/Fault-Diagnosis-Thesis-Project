# announcer.py
# Implements Public Announcement Logic (PAL) world pruning.
#
# For each announcement step in a scenario, the AnnouncementProcessor:
#   1. Validates that all axioms are observable by the scenario's agent.
#   2. Marks worlds that violate any axiom as dead (world.alive = False).
#   3. Updates the accessibility relation for the agent.
#   4. Returns a structured StepResult for display / logging.
#
# Usage:
#   from announcer import AnnouncementProcessor
#   processor = AnnouncementProcessor(kripke, engine, scenario)
#   results = processor.run()

from __future__ import annotations
from dataclasses import dataclass, field
from classes import (
    KripkeModel, World,
    Axiom, Announcement, Scenario,
)
from translator import AxiomEngine


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    """
    The outcome of processing one announcement step.

    Attributes
    ----------
    step                : 1-based step number
    axioms              : the axioms announced at this step
    worlds_before       : alive worlds BEFORE this announcement
    worlds_after        : alive worlds AFTER this announcement (surviving)
    pruned_worlds       : worlds eliminated by this announcement
    surviving_faults    : fault_node values of surviving worlds
                          (None entries = all-ok world, if included)
    is_resolved         : True when exactly one world survives
    is_contradiction    : True when zero worlds survive
    """
    step: int
    axioms: list[Axiom]
    worlds_before: list[World]
    worlds_after: list[World]
    pruned_worlds: list[World]
    surviving_faults: list[str | None]
    is_resolved: bool
    is_contradiction: bool

    def summary(self) -> str:
        """Return a compact human-readable summary of this step."""
        lines = [f"Step {self.step}:"]
        lines.append("  Observations:")
        for ax in self.axioms:
            val = "on/True" if ax.expected_value else "off/False"
            lines.append(f"    {ax.observable} = {val}")
        lines.append(
            f"  Worlds: {len(self.worlds_before)} → {len(self.worlds_after)} "
            f"({len(self.pruned_worlds)} pruned)"
        )
        if self.is_contradiction:
            lines.append("CONTRADICTION: no worlds survive.")
        elif self.is_resolved:
            lines.append(f"Suspected faulty component(s) = {self.surviving_faults[0]}")
        else:
            faults = [f or "all-ok" for f in self.surviving_faults]
            lines.append(f"  ?  Remaining candidates: {faults}")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# AnnouncementProcessor
# ─────────────────────────────────────────────────────────────────────────────

class AnnouncementProcessor:
    """
    Processes the announcements of a Scenario against a KripkeModel,
    implementing Public Announcement Logic (PAL) world pruning.

    The PAL update rule:
      After announcing phi, the model M becomes M|phi where
        W' = { w in W | M, w |= phi }
      i.e. all worlds where phi is false are eliminated.

    Since our circuit is fully deterministic, phi is a conjunction of
    ground observations (NODE = value), so a world either satisfies all
    of them or it does not.

    Parameters
    ----------
    kripke   : KripkeModel  — the initial epistemic state (all worlds alive)
    engine   : AxiomEngine  — checks worlds against axioms
    scenario : Scenario     — the scenario to run (provides agent + announcements)
    validate : bool         — if True, raise ValueError for unobservable axioms
                              (default True; set False to skip validation)
    """

    def __init__(
        self,
        kripke: KripkeModel,
        engine: AxiomEngine,
        scenario: Scenario,
        validate: bool = True,
    ):
        self.kripke = kripke
        self.engine = engine
        self.scenario = scenario
        self.agent = scenario.agent_name
        self.validate = validate
        self._results: list[StepResult] = []

    # ── Public API ────────────────────────────────────────────────────────

    def run(self) -> list[StepResult]:
        """
        Process all announcement steps in the scenario in order.
        Stops early if a contradiction is reached (no worlds survive).

        Returns
        -------
        list[StepResult] — one entry per processed step.
        """
        self._results = []

        for announcement in self.scenario.announcements:
            result = self._process_step(announcement)
            self._results.append(result)

            # Early exit on contradiction — further announcements are vacuous
            if result.is_contradiction:
                break

        return self._results

    @property
    def results(self) -> list[StepResult]:
        """The step results from the last run() call."""
        return self._results

    def final_result(self) -> StepResult | None:
        """The last StepResult produced, or None if run() has not been called."""
        return self._results[-1] if self._results else None

    # ── Core step processing ──────────────────────────────────────────────

    def _process_step(self, announcement: Announcement) -> StepResult:
        """
        Apply one announcement to the Kripke model:
          1. Optionally validate axioms against the agent's observable set.
          2. Record worlds alive before the update.
          3. For each alive world, check all axioms; mark violating worlds dead.
          4. Update the agent's accessibility relation.
          5. Return a StepResult.
        """
        axioms = announcement.observations

        # 1. Validate observability
        if self.validate:
            self.engine.validate_announcement_for_agent(axioms, self.agent)

        # 2. Snapshot of alive worlds before pruning
        worlds_before = [w for w in self.kripke.worlds if w.alive]

        # 3. Prune worlds that violate any axiom
        pruned: list[World] = []
        for world in worlds_before:
            if not all(self.engine.world_satisfies_axiom(world, ax) for ax in axioms):
                world.alive = False
                pruned.append(world)

        # 4. Update accessibility relation for the agent
        surviving_names = {w.name for w in self.kripke.worlds if w.alive}
        if self.agent in self.kripke.accessibility:
            self.kripke.accessibility[self.agent] = surviving_names

        # 5. Collect surviving worlds and build result
        worlds_after = [w for w in self.kripke.worlds if w.alive]
        surviving_faults = [w.fault_node for w in worlds_after]

        return StepResult(
            step=announcement.step,
            axioms=axioms,
            worlds_before=worlds_before,
            worlds_after=worlds_after,
            pruned_worlds=pruned,
            surviving_faults=surviving_faults,
            is_resolved=len(worlds_after) == 1,
            is_contradiction=len(worlds_after) == 0,
        )
