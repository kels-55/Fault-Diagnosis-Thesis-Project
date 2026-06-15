# classes.py
# Core model classes for DEL-based fault diagnosis.
#
# Hierarchy:
#   EpistemicModel      – the circuit structure (nodes, relationships, agents)
#   PossibleDependency  – a modal (◇) relationship between two fault nodes
#   KripkeModel         – the technician's epistemic state (worlds + accessibility)
#   Scenario            – a sequence of Announcements loaded from circuit.yaml
#   Announcement        – one step: a list of Axioms observed at that step
#   Axiom               – a single "NODE = value" constraint
#   World               – one possible world (one fault active, all derived values computed)

from __future__ import annotations
from dataclasses import dataclass, field
from graphlib import TopologicalSorter


# ─────────────────────────────────────────────────────────────────────────────
# Circuit structure classes  (populated by loader.py from circuit.yaml)
# ─────────────────────────────────────────────────────────────────────────────

class Node:
    """A single node in the circuit DAG."""

    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind    # 'fault' | 'voltage' | 'observable' | 'measurement'
        self.id: int | None = None
        self.domain: list | None = None

    def __repr__(self):
        return f"Node(name={self.name}, kind={self.kind})"


class Relationship:
    """
    Deterministic (necessary, □) causal relationship between nodes in the DAG.
    If the parent condition holds, the child value necessarily follows.
    """

    def __init__(self, child: Node, parents: list[Node], type: str, formula: str):
        self.child = child
        self.parents = parents
        self.type = type            # 'deterministic'
        self.formula = formula      # e.g. "AND(NOT(F_battery), NOT(F_PSU_short))"

    def __repr__(self):
        return f"Relationship(child={self.child.name}, formula={self.formula})"


class PossibleDependency:
    """
    A modal possibility (◇) relationship between two fault nodes.

    Expresses: if `condition_node` is in `condition_value`, then it is
    POSSIBLE (◇) — but not necessary (□) — that `dependent_node` is
    in `possible_value`.

    In modal logic terms:
      Relationship        →  □ (child follows necessarily from parents)
      PossibleDependency  →  ◇ (dependent is possible given condition)

    Example:
      F_PSU_short = True  →  ◇ F_battery = True
      "A PSU short makes battery exhaustion possible, but not certain."
    """

    def __init__(
        self,
        condition_node: Node,
        condition_value: bool,
        dependent_node: Node,
        possible_value: bool,
        note: str = "",
    ):
        self.condition_node = condition_node
        self.condition_value = condition_value
        self.dependent_node = dependent_node
        self.possible_value = possible_value
        self.note = note

    def is_triggered(self, world: "World") -> bool:
        """Return True if the condition holds in the given world."""
        return world.value_of(self.condition_node.name) == self.condition_value

    def is_possible_in(self, world: "World") -> bool:
        """
        Return True if the dependent node's possible_value is consistent
        with the condition holding in this world.
        """
        return (
            self.is_triggered(world)
            and world.value_of(self.dependent_node.name) == self.possible_value
        )

    def __repr__(self):
        cval = "True" if self.condition_value else "False"
        pval = "True" if self.possible_value else "False"
        return (
            f"PossibleDependency("
            f"{self.condition_node.name}={cval} → "
            f"◇ {self.dependent_node.name}={pval})"
        )


class Agent:
    """A technician agent and the set of nodes they can observe."""

    def __init__(self, name: str):
        self.name = name
        self.observed_nodes: list[Node] = []

    def observe(self, node: Node):
        self.observed_nodes.append(node)

    def __repr__(self):
        obs = [n.name for n in self.observed_nodes]
        return f"Agent(name={self.name}, observes={obs})"


class EpistemicModel:
    """
    Container for the full circuit structure:
    nodes, deterministic relationships, possible dependencies, and agents.
    Populated by loader.py; consumed by translator.py.
    """

    def __init__(self):
        self.nodes: list[Node] = []
        self.relationships: list[Relationship] = []
        self.possible_dependencies: list[PossibleDependency] = []
        self.agents: list[Agent] = []

    def add_node(self, node: Node) -> Node:
        self.nodes.append(node)
        return node

    def add_relationship(self, relationship: Relationship) -> Relationship:
        self.relationships.append(relationship)
        return relationship

    def add_possible_dependency(self, dep: PossibleDependency) -> PossibleDependency:
        self.possible_dependencies.append(dep)
        return dep

    def add_agent(self, agent: Agent) -> Agent:
        self.agents.append(agent)
        return agent

    def get_node(self, name: str) -> Node | None:
        for n in self.nodes:
            if n.name == name:
                return n
        return None

    def fault_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.kind == "fault"]

    def voltage_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.kind == "voltage"]

    def observable_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.kind == "observable"]

    def measurement_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.kind == "measurement"]

    def get_agent(self, name: str) -> Agent | None:
        for a in self.agents:
            if a.name == name:
                return a
        return None

    def topological_order(self) -> list[Node]:
        node_map = {n.name: n for n in self.nodes}
        deps: dict[str, set[str]] = {n.name: set() for n in self.nodes}
        for rel in self.relationships:
            for parent in rel.parents:
                deps[rel.child.name].add(parent.name)
        ts = TopologicalSorter(deps)
        return [node_map[name] for name in ts.static_order()
                if node_map[name].kind != "fault"]


# ─────────────────────────────────────────────────────────────────────────────
# DEL / Kripke model classes  (built by translator.py)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class World:
    """
    One possible world in the Kripke model.

    Represents the hypothesis that exactly one fault node is active
    (or the all-ok world if fault_node is None).
    """
    name: str
    fault_node: str | None
    fault_assignment: dict[str, bool]
    derived: dict[str, bool] = field(default_factory=dict)
    alive: bool = True
    possible_worlds: set[str] = field(default_factory=set)

    def value_of(self, node_name: str) -> bool:
        if node_name in self.fault_assignment:
            return self.fault_assignment[node_name]
        if node_name in self.derived:
            return self.derived[node_name]
        raise KeyError(f"Node '{node_name}' not found in world '{self.name}'")

    def __repr__(self):
        active = self.fault_node or "all-ok"
        return f"World(name={self.name}, fault={active}, alive={self.alive})"


@dataclass
class KripkeModel:
    """
    The technician's epistemic state as a Kripke model.

    Two accessibility relations:
      □ / accessibility   : epistemic — shrinks with each public announcement.
      ◇ / possible_worlds : physical possibility — fixed at model construction.
    """
    worlds: list[World] = field(default_factory=list)
    accessibility: dict[str, set[str]] = field(default_factory=dict)

    def alive_worlds(self) -> list[World]:
        return [w for w in self.worlds if w.alive]

    def surviving_faults(self) -> list[str | None]:
        return [w.fault_node for w in self.alive_worlds()]

    def is_resolved(self) -> bool:
        return len(self.alive_worlds()) == 1

    def get_world(self, name: str) -> World | None:
        for w in self.worlds:
            if w.name == name:
                return w
        return None

    def __repr__(self):
        alive = len(self.alive_worlds())
        total = len(self.worlds)
        return f"KripkeModel(worlds={total}, alive={alive})"


# ─────────────────────────────────────────────────────────────────────────────
# Scenario / Announcement / Axiom classes  (populated by loader.py)
# ─────────────────────────────────────────────────────────────────────────────

# Observation value → bool mapping.
#
# M_PSU_short semantics (important):
#   "high" → True  = resistance is HIGH = NO short = PSU is working fine
#   "low"  → False = resistance is LOW  = short IS present = PSU is faulty
#
# All other nodes:
#   "on" / "12v" / "high" → True  = active / voltage present / working
#   "off" / "0v" / "low"  → False = inactive / no voltage / faulty
#
# The formula for M_PSU_short is NOT(F_PSU_short), so:
#   F_PSU_short = True  (fault active)  → M_PSU_short = False (low)
#   F_PSU_short = False (no fault)      → M_PSU_short = True  (high)
_VALUE_MAP: dict[str, bool] = {
    "on":   True,
    "off":  False,
    "12v":  True,
    "0v":   False,
    "high": True,   # M_PSU_short = high → resistance high → NO short → PSU ok
    "low":  False,  # M_PSU_short = low  → resistance low  → short present → PSU faulty
}


@dataclass
class Axiom:
    """
    A single observation constraint: NODE = value.

    observable      : name of the observed node (O_*, M_*)
    expected_value  : True (on/12V/high) or False (off/0V/low)
    raw             : the original string from the YAML, e.g. "O_PSU_LED = off"
    """
    observable: str
    expected_value: bool
    raw: str = ""

    @staticmethod
    def from_string(obs_string: str) -> "Axiom":
        obs_string = obs_string.strip()
        if "=" not in obs_string:
            raise ValueError(f"Cannot parse observation: '{obs_string}' (expected 'NODE = value')")
        node_part, value_part = obs_string.split("=", 1)
        node_name = node_part.strip()
        value_str = value_part.strip().lower()
        if value_str not in _VALUE_MAP:
            raise ValueError(
                f"Unknown observation value '{value_str}' in '{obs_string}'. "
                f"Allowed: {list(_VALUE_MAP.keys())}"
            )
        return Axiom(
            observable=node_name,
            expected_value=_VALUE_MAP[value_str],
            raw=obs_string,
        )

    def __repr__(self):
        val = "True" if self.expected_value else "False"
        return f"Axiom({self.observable} = {val})"


@dataclass
class Announcement:
    """One announcement step in a scenario."""
    step: int
    observations: list[Axiom] = field(default_factory=list)

    def __repr__(self):
        return f"Announcement(step={self.step}, observations={len(self.observations)})"


@dataclass
class Scenario:
    """A full diagnostic scenario loaded from circuit.yaml."""
    id: int
    description: str
    tools_in_hand: list[str]
    agent_name: str
    announcements: list[Announcement] = field(default_factory=list)

    def has_tool(self, tool: str) -> bool:
        return tool in self.tools_in_hand

    def __repr__(self):
        return (
            f"Scenario(id={self.id}, agent={self.agent_name}, "
            f"announcements={len(self.announcements)}, desc='{self.description}')"
        )
