# classes.py
# Core model classes for DEL-based fault diagnosis.

from __future__ import annotations
from dataclasses import dataclass, field
from graphlib import TopologicalSorter

class Node:
    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind

    def __repr__(self):
        return f"Node(name={self.name}, kind={self.kind})"

class Relationship:
    def __init__(self, child: Node, parents: list[Node], type: str, formula: str):
        self.child = child
        self.parents = parents
        self.type = type
        self.formula = formula

    def __repr__(self):
        return f"Relationship(child={self.child.name}, formula={self.formula})"

class PossibleDependency:
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
        return world.value_of(self.condition_node.name) == self.condition_value

    def __repr__(self):
        cval = "True" if self.condition_value else "False"
        pval = "True" if self.possible_value else "False"
        return (
            f"PossibleDependency("
            f"{self.condition_node.name}={cval} → "
            f"◇ {self.dependent_node.name}={pval})"
        )

class Agent:
    def __init__(self, name: str):
        self.name = name
        self.observed_nodes: list[Node] = []

    def observe(self, node: Node):
        self.observed_nodes.append(node)

    def __repr__(self):
        obs = [n.name for n in self.observed_nodes]
        return f"Agent(name={self.name}, observes={obs})"

class EpistemicModel:
    def __init__(self):
        self.nodes: list[Node] = []
        self.relationships: list[Relationship] = []
        self.possible_dependencies: list[PossibleDependency] = []
        self.agents: list[Agent] = []

    def add_node(self, node: Node) -> Node:
        self.nodes.append(node)
        return node

    def add_relationship(self, rel: Relationship) -> Relationship:
        self.relationships.append(rel)
        return rel

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
# DEL / Kripke model classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class World:
    """
    One possible world in the Kripke model.

    fault_nodes is a frozenset of active fault names (empty = all-ok).
    Replaces the old single fault_node: str | None field.
    """
    name: str
    fault_nodes: frozenset[str]          # ← was: fault_node: str | None
    fault_assignment: dict[str, bool]
    derived: dict[str, bool] = field(default_factory=dict)
    alive: bool = True
    possible_worlds: set[str] = field(default_factory=set)

    # ── Convenience ───────────────────────────────────────────────────────

    @property
    def fault_node(self) -> str | None:
        """
        Back-compat shim: returns the single fault name for single-fault worlds,
        or None for the all-ok world.  Raises for multi-fault worlds so callers
        are forced to handle them explicitly.
        """
        if len(self.fault_nodes) == 0:
            return None
        if len(self.fault_nodes) == 1:
            return next(iter(self.fault_nodes))
        raise AttributeError(
            f"World '{self.name}' has multiple active faults {self.fault_nodes}. "
            f"Use world.fault_nodes instead of world.fault_node."
        )

    def is_multi_fault(self) -> bool:
        return len(self.fault_nodes) > 1

    def label(self) -> str:
        """Human-readable fault label for display."""
        if not self.fault_nodes:
            return "all-ok"
        return " + ".join(sorted(self.fault_nodes))

    def value_of(self, node_name: str) -> bool:
        if node_name in self.fault_assignment:
            return self.fault_assignment[node_name]
        if node_name in self.derived:
            return self.derived[node_name]
        raise KeyError(f"Node '{node_name}' not found in world '{self.name}'")

    def __repr__(self):
        return f"World(name={self.name}, faults={self.label()}, alive={self.alive})"


@dataclass
class KripkeModel:
    worlds: list[World] = field(default_factory=list)
    accessibility: dict[str, set[str]] = field(default_factory=dict)

    def alive_worlds(self) -> list[World]:
        return [w for w in self.worlds if w.alive]

    def surviving_faults(self) -> list[frozenset[str]]:
        return [w.fault_nodes for w in self.alive_worlds()]

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
# Scenario / Announcement / Axiom
# ─────────────────────────────────────────────────────────────────────────────

_VALUE_MAP: dict[str, bool] = {
    "on":   False,
    "off":  True,
    "12v":  False,
    "0v":   True,
    "high": False,
    "low":  True,
}

@dataclass
class Axiom:
    observable: str
    expected_value: bool
    raw: str = ""

    @staticmethod
    def from_string(obs_string: str) -> "Axiom":
        obs_string = obs_string.strip()
        if "=" not in obs_string:
            raise ValueError(f"Cannot parse observation: '{obs_string}'")
        node_part, value_part = obs_string.split("=", 1)
        node_name = node_part.strip()
        value_str = value_part.strip().lower()
        if value_str not in _VALUE_MAP:
            raise ValueError(
                f"Unknown observation value '{value_str}' in '{obs_string}'. "
                f"Allowed: {list(_VALUE_MAP.keys())}"
            )
        return Axiom(observable=node_name, expected_value=_VALUE_MAP[value_str], raw=obs_string)

    def __repr__(self):
        val = "True" if self.expected_value else "False"
        return f"Axiom({self.observable} = {val})"

@dataclass
class Announcement:
    step: int
    observations: list[Axiom] = field(default_factory=list)

    def __repr__(self):
        return f"Announcement(step={self.step}, observations={len(self.observations)})"

@dataclass
class Scenario:
    id: int
    description: str
    tools_in_hand: list[str]
    agent_name: str
    announcements: list[Announcement] = field(default_factory=list)
    max_faults: int = 1          # ← NEW: max simultaneous faults for this scenario

    def has_tool(self, tool: str) -> bool:
        return tool in self.tools_in_hand

    def __repr__(self):
        return (
            f"Scenario(id={self.id}, agent={self.agent_name}, "
            f"max_faults={self.max_faults}, "
            f"announcements={len(self.announcements)}, desc='{self.description}')"
        )
