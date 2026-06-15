# loader.py
# Parses circuit.yaml into an EpistemicModel and a list of Scenarios.
#
# Usage:
#   from loader import load_circuit
#   model, scenarios = load_circuit("circuit.yaml")

from __future__ import annotations
import re
import yaml
from classes import (
    Node, Relationship, PossibleDependency, Agent, EpistemicModel,
    Axiom, Announcement, Scenario,
)


# ─────────────────────────────────────────────────────────────────────────────
# Agent name resolution
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_agent_name(tools_in_hand: list[str], agents: list[Agent]) -> str:
    has_multimeter = "multimeter" in [t.lower() for t in tools_in_hand]
    for agent in agents:
        if has_multimeter and "multimeter" in agent.name and "no_multimeter" not in agent.name:
            return agent.name
    for agent in agents:
        if not has_multimeter and "no_multimeter" in agent.name:
            return agent.name
    return agents[0].name if agents else "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Announcement key normalisation
# ─────────────────────────────────────────────────────────────────────────────

def _parse_announcement_key(key: str) -> int | None:
    key_lower = key.lower().strip()
    match = re.search(r'\d+', key_lower)
    if match and re.match(r'^(ann\w*|step)', key_lower):
        return int(match.group())
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Section parsers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_nodes(raw_nodes: list[dict]) -> list[Node]:
    """Build Node objects from the 'nodes:' block."""
    nodes = []
    for entry in raw_nodes:
        node = Node(name=entry["name"], kind=entry["kind"])
        nodes.append(node)
    return nodes


def _parse_relationships(
    raw_rels: list[dict],
    node_map: dict[str, Node],
) -> list[Relationship]:
    """Build Relationship (deterministic, □) objects from the 'relationships:' block."""
    relationships = []
    for entry in raw_rels:
        child_name = entry["child"]
        if child_name not in node_map:
            raise ValueError(f"Relationship references unknown child node: '{child_name}'")
        child = node_map[child_name]
        parents = []
        for p_name in entry.get("parents", []):
            if p_name not in node_map:
                raise ValueError(
                    f"Relationship for '{child_name}' references unknown parent: '{p_name}'"
                )
            parents.append(node_map[p_name])
        rel = Relationship(
            child=child,
            parents=parents,
            type=entry.get("type", "deterministic"),
            formula=entry.get("formula", ""),
        )
        relationships.append(rel)
    return relationships


def _parse_possible_dependencies(
    raw_deps: list[dict],
    node_map: dict[str, Node],
) -> list[PossibleDependency]:
    """
    Build PossibleDependency (modal possibility, ◇) objects from the
    'possible_dependencies:' block.

    Expected YAML format per entry:
      - condition_node:  F_PSU_short
        condition_value: true          # true = fault active
        dependent_node:  F_battery
        possible_value:  true          # true = fault active
        note: "A PSU short can drain the battery."
    """
    deps = []
    for entry in raw_deps:
        cnode_name = entry.get("condition_node")
        dnode_name = entry.get("dependent_node")

        if not cnode_name or not dnode_name:
            raise ValueError(
                "Each possible_dependency entry must have "
                "'condition_node' and 'dependent_node'."
            )
        if cnode_name not in node_map:
            raise ValueError(
                f"possible_dependency references unknown condition_node: '{cnode_name}'"
            )
        if dnode_name not in node_map:
            raise ValueError(
                f"possible_dependency references unknown dependent_node: '{dnode_name}'"
            )

        dep = PossibleDependency(
            condition_node=node_map[cnode_name],
            condition_value=bool(entry.get("condition_value", True)),
            dependent_node=node_map[dnode_name],
            possible_value=bool(entry.get("possible_value", True)),
            note=entry.get("note", ""),
        )
        deps.append(dep)
    return deps


def _parse_agents(
    raw_agents: list[dict],
    node_map: dict[str, Node],
) -> list[Agent]:
    """Build Agent objects from the 'agents:' block."""
    agents = []
    for entry in raw_agents:
        agent = Agent(name=entry["name"])
        for obs_name in entry.get("observes", []):
            if obs_name not in node_map:
                raise ValueError(
                    f"Agent '{agent.name}' observes unknown node: '{obs_name}'"
                )
            agent.observe(node_map[obs_name])
        agents.append(agent)
    return agents


def _parse_announcements_list(ann_list: list[dict]) -> list[Announcement]:
    """Parse list-style announcements block (current circuit.yaml format)."""
    announcements = []
    for entry in ann_list:
        step = int(entry["step"])
        axioms = [Axiom.from_string(s) for s in entry.get("observations", [])]
        announcements.append(Announcement(step=step, observations=axioms))
    announcements.sort(key=lambda a: a.step)
    return announcements


def _parse_announcements_dict(ann_dict: dict) -> list[Announcement]:
    """Parse dict-style announcements block (legacy format)."""
    announcements = []
    for key, obs_list in ann_dict.items():
        step = _parse_announcement_key(str(key))
        if step is None:
            continue
        axioms = [Axiom.from_string(s) for s in (obs_list or [])]
        announcements.append(Announcement(step=step, observations=axioms))
    announcements.sort(key=lambda a: a.step)
    return announcements


def _parse_scenarios(
    raw_scenarios: list[dict],
    agents: list[Agent],
) -> list[Scenario]:
    """Build Scenario objects from the 'scenarios:' block."""
    scenarios = []
    for entry in raw_scenarios:
        sid = int(entry["id"])
        description = entry.get("description", f"Scenario {sid}")
        tools = entry.get("tools_in_hand", [])
        agent_name = _resolve_agent_name(tools, agents)

        raw_ann = entry.get("announcements", {})
        if isinstance(raw_ann, list):
            announcements = _parse_announcements_list(raw_ann)
        elif isinstance(raw_ann, dict):
            announcements = _parse_announcements_dict(raw_ann)
        else:
            announcements = []

        scenarios.append(Scenario(
            id=sid,
            description=description,
            tools_in_hand=tools,
            agent_name=agent_name,
            announcements=announcements,
        ))

    scenarios.sort(key=lambda s: s.id)
    return scenarios


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_circuit(path: str) -> tuple[EpistemicModel, list[Scenario]]:
    """
    Parse a circuit YAML file and return:
      - EpistemicModel  : nodes, relationships, possible_dependencies, agents
      - list[Scenario]  : scenarios with announcements and axioms

    Parameters
    ----------
    path : str
        Path to the circuit YAML file (e.g. "circuit.yaml").

    Returns
    -------
    model     : EpistemicModel
    scenarios : list[Scenario]

    Raises
    ------
    FileNotFoundError  : if the path does not exist
    ValueError         : if required sections are missing or references are invalid
    """
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"'{path}' is empty or not valid YAML.")

    # ── Nodes ──────────────────────────────────────────────────────────────
    raw_nodes = raw.get("nodes")
    if not raw_nodes:
        raise ValueError(f"'{path}' is missing a 'nodes:' section.")
    nodes = _parse_nodes(raw_nodes)
    node_map: dict[str, Node] = {n.name: n for n in nodes}

    # ── Relationships (deterministic, □) ───────────────────────────────────
    raw_rels = raw.get("relationships", [])
    relationships = _parse_relationships(raw_rels, node_map)

    # ── Possible dependencies (modal possibility, ◇) ───────────────────────
    raw_possible = raw.get("possible_dependencies", [])
    possible_dependencies = _parse_possible_dependencies(raw_possible, node_map)

    # ── Agents ─────────────────────────────────────────────────────────────
    raw_agents = raw.get("agents", [])
    agents = _parse_agents(raw_agents, node_map)

    # ── Assemble EpistemicModel ────────────────────────────────────────────
    model = EpistemicModel()
    for node in nodes:
        model.add_node(node)
    for rel in relationships:
        model.add_relationship(rel)
    for dep in possible_dependencies:
        model.add_possible_dependency(dep)
    for agent in agents:
        model.add_agent(agent)

    # ── Scenarios ──────────────────────────────────────────────────────────
    raw_scenarios = raw.get("scenarios", [])
    scenarios = _parse_scenarios(raw_scenarios, agents)

    return model, scenarios
