# translator.py
# Translates an EpistemicModel into a KripkeModel and provides an AxiomEngine
# for checking worlds against announcement axioms.
#
# Usage:
#   from translator import build_kripke_model, AxiomEngine
#   kripke = build_kripke_model(model)
#   engine = AxiomEngine(model)

from __future__ import annotations
from graphlib import TopologicalSorter
from classes import (
    EpistemicModel, Relationship,
    World, KripkeModel,
    Axiom,
)


# ─────────────────────────────────────────────────────────────────────────────
# Formula evaluator
# ─────────────────────────────────────────────────────────────────────────────

def _split_args(inner: str) -> list[str]:
    """
    Split a comma-separated argument string while respecting nested parentheses.
    e.g. "NOT(F_a), V_0, NOT(F_b)" -> ["NOT(F_a)", "V_0", "NOT(F_b)"]
    """
    args = []
    depth = 0
    current: list[str] = []
    for ch in inner:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args


def _evaluate_formula(formula: str, values: dict[str, bool]) -> bool:
    """
    Recursively evaluate a formula string against a dict of node -> bool values.

    Supported operators (case-insensitive):
      AND(a, b, ...)   - true iff all arguments are true
      OR(a, b, ...)    - true iff at least one argument is true
      NOT(a)           - negation
      bare node name   - looked up directly in values
    """
    formula = formula.strip()
    upper = formula.upper()

    if upper.startswith("AND(") and formula.endswith(")"):
        return all(_evaluate_formula(a, values) for a in _split_args(formula[4:-1]))

    if upper.startswith("OR(") and formula.endswith(")"):
        return any(_evaluate_formula(a, values) for a in _split_args(formula[3:-1]))

    if upper.startswith("NOT(") and formula.endswith(")"):
        return not _evaluate_formula(formula[4:-1], values)

    if formula in values:
        return values[formula]

    raise ValueError(
        f"Cannot evaluate formula fragment '{formula}'. "
        f"Known nodes: {list(values.keys())}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# World computation
# ─────────────────────────────────────────────────────────────────────────────

def _compute_world(
    fault_node_name: str | None,
    fault_names: list[str],
    topo_order: list,
    rel_map: dict[str, Relationship],
) -> World:
    """
    Build one World for the hypothesis that fault_node_name is the active fault
    (or None for the all-ok world).

    Steps:
      1. Set fault_assignment: exactly one fault True (or all False for all-ok).
      2. Walk non-fault nodes in topological order, evaluating each formula.
      3. Return the completed World (possible_worlds populated separately).
    """
    # 1. Fault assignment
    fault_assignment: dict[str, bool] = {
        f: (f == fault_node_name) for f in fault_names
    }

    # 2. Evaluate derived nodes in topological order
    values: dict[str, bool] = dict(fault_assignment)
    derived: dict[str, bool] = {}

    for node in topo_order:
        if node.name not in rel_map:
            derived[node.name] = False
            values[node.name] = False
            continue
        rel = rel_map[node.name]
        result = _evaluate_formula(rel.formula, values)
        derived[node.name] = result
        values[node.name] = result

    world_name = f"w_{fault_node_name}" if fault_node_name else "w_all_ok"
    return World(
        name=world_name,
        fault_node=fault_node_name,
        fault_assignment=fault_assignment,
        derived=derived,
        alive=True,
        possible_worlds=set(),   # populated by _wire_possible_worlds()
    )


# ─────────────────────────────────────────────────────────────────────────────
# Possible-world wiring (◇ accessibility)
# ─────────────────────────────────────────────────────────────────────────────

def _wire_possible_worlds(
    worlds: list[World],
    model: EpistemicModel,
) -> None:
    """
    Populate World.possible_worlds for every world based on the
    PossibleDependency entries in the model.

    For each PossibleDependency D and each world W:
      If D.condition holds in W (i.e. D.condition_node = D.condition_value),
      then every world W' where D.dependent_node = D.possible_value is
      ◇-reachable from W.

    This encodes:
      "In world W, it is physically possible that D.dependent_node is
       D.possible_value" — i.e. W can 'see' all such W' via ◇.

    Example with F_PSU_short → ◇ F_battery:
      In w_F_PSU_short (where F_PSU_short = True), the world w_F_battery
      (where F_battery = True) is ◇-accessible because a PSU short makes
      battery exhaustion possible.
    """
    world_map: dict[str, World] = {w.name: w for w in worlds}

    for dep in model.possible_dependencies:
        for world in worlds:
            # Check if the condition holds in this world
            if not dep.is_triggered(world):
                continue
            # Add all worlds where the dependent node has the possible value
            for other in worlds:
                if other.value_of(dep.dependent_node.name) == dep.possible_value:
                    world.possible_worlds.add(other.name)


# ─────────────────────────────────────────────────────────────────────────────
# Topological sort helper
# ─────────────────────────────────────────────────────────────────────────────

def _topo_order(model: EpistemicModel) -> list:
    """Return all non-fault nodes in topological (parents-before-children) order."""
    node_map = {n.name: n for n in model.nodes}
    deps: dict[str, set[str]] = {n.name: set() for n in model.nodes}
    for rel in model.relationships:
        for parent in rel.parents:
            deps[rel.child.name].add(parent.name)

    ts = TopologicalSorter(deps)
    return [
        node_map[name]
        for name in ts.static_order()
        if node_map[name].kind != "fault"
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Public: build_kripke_model
# ─────────────────────────────────────────────────────────────────────────────

def build_kripke_model(
    model: EpistemicModel,
    include_all_ok: bool = False,
) -> KripkeModel:
    """
    Translate an EpistemicModel into an initial KripkeModel.

    One world is created per fault node (the "exactly one fault" assumption).
    Optionally an all-ok world (no fault active) can be included.

    Two relations are established:
      □ (epistemic accessibility): initially all worlds accessible to every
        agent — total ignorance (S5). Shrinks after each announcement.
      ◇ (possible dependency):     World.possible_worlds, fixed at construction.
        Encodes physical possibility from PossibleDependency entries, e.g.
        w_F_PSU_short can ◇-reach w_F_battery because a short can drain
        the battery.

    Parameters
    ----------
    model          : EpistemicModel populated by loader.py
    include_all_ok : if True, add a world where no fault is active
    """
    fault_names = [n.name for n in model.fault_nodes()]
    topo = _topo_order(model)
    rel_map: dict[str, Relationship] = {
        rel.child.name: rel for rel in model.relationships
    }

    worlds: list[World] = []

    for fault_name in fault_names:
        worlds.append(_compute_world(fault_name, fault_names, topo, rel_map))

    if include_all_ok:
        worlds.append(_compute_world(None, fault_names, topo, rel_map))

    # Wire ◇ accessibility from PossibleDependency entries
    _wire_possible_worlds(worlds, model)

    # Initial □ accessibility: all worlds accessible to every agent
    all_world_names = {w.name for w in worlds}
    accessibility: dict[str, set[str]] = {
        agent.name: set(all_world_names) for agent in model.agents
    }

    return KripkeModel(worlds=worlds, accessibility=accessibility)


# ─────────────────────────────────────────────────────────────────────────────
# Public: AxiomEngine
# ─────────────────────────────────────────────────────────────────────────────

class AxiomEngine:
    """
    Checks whether a World satisfies an Axiom, and validates that axioms
    only reference nodes the agent can actually observe.
    """

    def __init__(self, model: EpistemicModel):
        self.model = model
        self._agent_observables: dict[str, set[str]] = {
            agent.name: {n.name for n in agent.observed_nodes}
            for agent in model.agents
        }

    def world_satisfies_axiom(self, world: World, axiom: Axiom) -> bool:
        """Return True iff world's value for axiom.observable == axiom.expected_value."""
        actual = world.value_of(axiom.observable)
        return actual == axiom.expected_value

    def validate_axiom_for_agent(self, axiom: Axiom, agent_name: str) -> None:
        """Raise ValueError if the agent cannot observe the axiom's node."""
        observables = self._agent_observables.get(agent_name, set())
        if axiom.observable not in observables:
            raise ValueError(
                f"Agent '{agent_name}' cannot observe '{axiom.observable}'. "
                f"Observable nodes for this agent: {sorted(observables)}"
            )

    def validate_announcement_for_agent(
        self,
        axioms: list[Axiom],
        agent_name: str,
    ) -> None:
        """Validate all axioms in an announcement for the given agent."""
        for axiom in axioms:
            self.validate_axiom_for_agent(axiom, agent_name)

    def filter_worlds(
        self,
        worlds: list[World],
        axioms: list[Axiom],
    ) -> list[World]:
        """
        Return only those worlds satisfying ALL axioms.
        Does not mutate world.alive — that is the announcer's responsibility.
        """
        return [
            w for w in worlds
            if all(self.world_satisfies_axiom(w, ax) for ax in axioms)
        ]
