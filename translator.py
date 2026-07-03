# translates an EpistemicModel into a KripkeModel and provides an AxiomEngine.

from __future__ import annotations
from graphlib import TopologicalSorter
from itertools import chain, combinations
from classes import (
    EpistemicModel, Relationship,
    World, KripkeModel,
    Axiom,
)

# formula evaluator

def _split_args(inner: str) -> list[str]:
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

# Powerset helper

def _powerset(iterable, max_size: int):
    """
    Yield all subsets of iterable with size 0 .. max_size (inclusive).
    e.g. _powerset([A, B, C], 2) → (), (A,), (B,), (C,), (A,B), (A,C), (B,C)
    """
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(max_size + 1))

# compute worlds

def _compute_world(
    active_faults: frozenset[str],  
    fault_names: list[str],
    topo_order: list,
    rel_map: dict[str, Relationship],
) -> World:
    """
    Build one World for the hypothesis that exactly the faults in
    active_faults are simultaneously active (empty set = all-ok).

    The fault_assignment sets every fault in active_faults to True,
    all others to False.  Derived nodes are then evaluated in
    topological order using the circuit formulas.
    """
    fault_assignment: dict[str, bool] = {
        f: (f in active_faults) for f in fault_names
    }

    values: dict[str, bool] = dict(fault_assignment)
    derived: dict[str, bool] = {}

    for node in topo_order:
        if node.name not in rel_map:
            raise ValueError(
                f"Node '{node.name}' (kind='{node.kind}') has no relationship "
                f"defined in the circuit model. Add a 'relationships:' entry "
                f"with a formula for this node, or remove it from the node list."
            )
        rel = rel_map[node.name]
        result = _evaluate_formula(rel.formula, values)
        derived[node.name] = result
        values[node.name] = result

    # Name: "w_all_ok", "w_F_battery", or "w_F_PSU_short+F_battery"
    if not active_faults:
        world_name = "w_all_ok"
    else:
        world_name = "w_" + "+".join(sorted(active_faults))

    return World(
        name=world_name,
        fault_nodes=active_faults,
        fault_assignment=fault_assignment,
        derived=derived,
        alive=True,
        possible_worlds=set(),
    )

# Possible-world wiring (◇ accessibility)

def _wire_possible_worlds(worlds: list[World], model: EpistemicModel) -> None:
    for dep in model.possible_dependencies:
        for world in worlds:
            if not dep.is_triggered(world):
                continue
            for other in worlds:
                if other.value_of(dep.dependent_node.name) == dep.possible_value:
                    world.possible_worlds.add(other.name)

# Topological sort helper (unchanged)

def _topo_order(model: EpistemicModel) -> list:
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

# Public: build_kripke_model

def build_kripke_model(
    model: EpistemicModel,
    include_all_ok: bool = False,
    max_faults: int = 1,
) -> KripkeModel:
    """
    Translate an EpistemicModel into an initial KripkeModel.

    Parameters
    ----------
    model          : EpistemicModel populated by loader.py
    include_all_ok : if True, include the zero-fault world
    max_faults     : maximum number of simultaneous active faults per world.
                     1 = original single-fault behaviour (default).
                     2 = also generate all pairs of faults, etc.

    World count grows as sum(C(n,k) for k in 1..max_faults).
    For n=20 faults: max_faults=1 → 20 worlds, =2 → 210, =3 → 1,350.
    """
    fault_names = [n.name for n in model.fault_nodes()]
    topo = _topo_order(model)
    rel_map: dict[str, Relationship] = {
        rel.child.name: rel for rel in model.relationships
    }

    worlds: list[World] = []

    # generate all fault subsets 
    for subset in _powerset(fault_names, max_faults):
        if len(subset) == 0:
            if include_all_ok:
                worlds.append(_compute_world(frozenset(), fault_names, topo, rel_map))
        else:
            worlds.append(_compute_world(frozenset(subset), fault_names, topo, rel_map))

    _wire_possible_worlds(worlds, model)

    all_world_names = {w.name for w in worlds}
    accessibility: dict[str, set[str]] = {
        agent.name: set(all_world_names) for agent in model.agents
    }

    return KripkeModel(worlds=worlds, accessibility=accessibility)

# Public: AxiomEngine 

class AxiomEngine:
    def __init__(self, model: EpistemicModel):
        self.model = model
        self._agent_observables: dict[str, set[str]] = {
            agent.name: {n.name for n in agent.observed_nodes}
            for agent in model.agents
        }

    def world_satisfies_axiom(self, world: World, axiom: Axiom) -> bool:
        actual = world.value_of(axiom.observable)
        return actual == axiom.expected_value

    def validate_axiom_for_agent(self, axiom: Axiom, agent_name: str) -> None:
        observables = self._agent_observables.get(agent_name, set())
        if axiom.observable not in observables:
            raise ValueError(
                f"Agent '{agent_name}' cannot observe '{axiom.observable}'. "
                f"Observable nodes: {sorted(observables)}"
            )

    def validate_announcement_for_agent(self, axioms: list[Axiom], agent_name: str) -> None:
        for axiom in axioms:
            self.validate_axiom_for_agent(axiom, agent_name)

    def filter_worlds(self, worlds: list[World], axioms: list[Axiom]) -> list[World]:
        return [
            w for w in worlds
            if all(self.world_satisfies_axiom(w, ax) for ax in axioms)
        ]
