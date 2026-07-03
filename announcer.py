# implements world pruning after each announcement

from __future__ import annotations
from dataclasses import dataclass, field
from classes import (
    KripkeModel, World,
    Axiom, Announcement, Scenario,
)
from translator import AxiomEngine

# result dataclass

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
    surviving_faults    : fault_nodes (frozenset) of surviving worlds
                          ← was list[str | None], now list[frozenset[str]]
    is_resolved         : True when exactly one world survives
    is_contradiction    : True when zero worlds survive
    """
    step: int
    axioms: list[Axiom]
    worlds_before: list[World]
    worlds_after: list[World]
    pruned_worlds: list[World]
    surviving_faults: list[frozenset[str]]   # ← changed from list[str | None]
    is_resolved: bool
    is_contradiction: bool

    def summary(self) -> str:
        lines = [f"Step {self.step}:"]
        lines.append("  Observations:")
        for ax in self.axioms:
            val = "off/0V/low (faulty)" if ax.expected_value else "on/12V/high (normal)"
            lines.append(f"    {ax.observable} = {val}")
       
        lines.append(
            f"  Worlds: {len(self.worlds_before)} → {len(self.worlds_after)} "
            f"({len(self.pruned_worlds)} pruned)"
        )
        if self.is_contradiction:
            lines.append("  CONTRADICTION: no worlds survive.")
        elif self.is_resolved:
            label = " + ".join(sorted(self.surviving_faults[0])) or "all-ok"
            lines.append(f"  Suspected faulty component(s) = {label}")
        else:
            labels = [" + ".join(sorted(fs)) or "all-ok" for fs in self.surviving_faults]
            lines.append(f"  Remaining candidates: {labels}")
        return "\n".join(lines)


# AnnouncementProcessor

class AnnouncementProcessor:
    """
    Processes the announcements of a Scenario against a KripkeModel,
    implementing Public Announcement Logic (PAL) world pruning.

    The PAL update rule:
      After announcing phi, the model M becomes M|phi where
        W' = { w in W | M, w |= phi }
      i.e. all worlds where phi is false are eliminated.
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
        self._results = []
        for announcement in self.scenario.announcements:
            result = self._process_step(announcement)
            self._results.append(result)
            if result.is_contradiction:
                break
        return self._results

    @property
    def results(self) -> list[StepResult]:
        return self._results

    def final_result(self) -> StepResult | None:
        return self._results[-1] if self._results else None

    def _process_step(self, announcement: Announcement) -> StepResult:
        axioms = announcement.observations

        # validate observability
        if self.validate:
            self.engine.validate_announcement_for_agent(axioms, self.agent)

        # show alive worlds before pruning
        worlds_before = [w for w in self.kripke.worlds if w.alive]

        # prune worlds that violate any axiom
        pruned: list[World] = []
        for world in worlds_before:
            if not all(self.engine.world_satisfies_axiom(world, ax) for ax in axioms):
                world.alive = False
                pruned.append(world)

        # update accessibility relation for the agent
        surviving_names = {w.name for w in self.kripke.worlds if w.alive}
        if self.agent in self.kripke.accessibility:
            self.kripke.accessibility[self.agent] = surviving_names

        # review surviving worlds and show result
        worlds_after = [w for w in self.kripke.worlds if w.alive]

        surviving_faults = [w.fault_nodes for w in worlds_after]

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
