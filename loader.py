# loader.py
# loads circuit.yaml into an EpistemicModel and a list of Scenarios.

from __future__ import annotations
import re
import yaml
from classes import (
    Node, Relationship, PossibleDependency, Agent, EpistemicModel,
    Axiom, Announcement, Scenario,
)

def _resolve_agent_name(tools_in_hand: list[str], agents: list[Agent]) -> str:
    has_multimeter = "multimeter" in [t.lower() for t in tools_in_hand]
    for agent in agents:
        if has_multimeter and "multimeter" in agent.name and "no_multimeter" not in agent.name:
            return agent.name
    for agent in agents:
        if not has_multimeter and "no_multimeter" in agent.name:
            return agent.name
    return agents[0].name if agents else "unknown"

def _parse_announcement_key(key: str) -> int | None:
    key_lower = key.lower().strip()
    match = re.search(r'\d+', key_lower)
    if match and re.match(r'^(ann\w*|step)', key_lower):
        return int(match.group())
    return None

def _parse_nodes(raw_nodes: list[dict]) -> list[Node]:
    return [Node(name=entry["name"], kind=entry["kind"]) for entry in raw_nodes]

def _parse_relationships(
    raw_rels: list[dict],
    node_map: dict[str, Node],
) -> tuple[list[Relationship], list[PossibleDependency]]:
    """
    Parse the 'relationships:' block, routing each entry by its 'type' field:

      type: deterministic  →  Relationship  (□, necessary causal link)
      type: possible       →  PossibleDependency  (◇, modal possibility)

    For 'possible' entries the YAML fields map as:
      child           → dependent_node
      parents[0]      → condition_node  (exactly one parent expected)
      condition_value → condition_value (default: true)
      possible_value  → possible_value  (default: true)
      note            → note            (optional)
    """
    relationships: list[Relationship] = []
    possible_deps: list[PossibleDependency] = []

    for entry in raw_rels:
        rel_type = entry.get("type", "deterministic").lower().strip()
        child_name = entry.get("child")

        if child_name not in node_map:
            raise ValueError(f"Relationship references unknown node: '{child_name}'")

        if rel_type == "possible":
            # possibililty relationship (◇)
            parents_raw = entry.get("parents", [])
            if len(parents_raw) != 1:
                raise ValueError(
                    f"'possible' relationship for '{child_name}' must have "
                    f"exactly one parent (the condition node), "
                    f"got {len(parents_raw)}: {parents_raw}"
                )
            condition_name = parents_raw[0]
            if condition_name not in node_map:
                raise ValueError(
                    f"'possible' relationship for '{child_name}' references "
                    f"unknown condition node: '{condition_name}'"
                )
            possible_deps.append(PossibleDependency(
                condition_node=node_map[condition_name],
                condition_value=bool(entry.get("condition_value", True)),
                dependent_node=node_map[child_name],
                possible_value=bool(entry.get("possible_value", True)),
                note=entry.get("note", ""),
            ))

        else:
            # deterministic/necessity relationship (□)
            parents = []
            for p_name in entry.get("parents", []):
                if p_name not in node_map:
                    raise ValueError(
                        f"Relationship for '{child_name}' references "
                        f"unknown parent: '{p_name}'"
                    )
                parents.append(node_map[p_name])
            relationships.append(Relationship(
                child=node_map[child_name],
                parents=parents,
                type=rel_type,
                formula=entry.get("formula", ""),
            ))

    return relationships, possible_deps

def _parse_agents(raw_agents: list[dict], node_map: dict[str, Node]) -> list[Agent]:
    agents = []
    for entry in raw_agents:
        agent = Agent(name=entry["name"])
        for obs_name in entry.get("observes", []):
            if obs_name not in node_map:
                raise ValueError(f"Agent '{agent.name}' observes unknown node: '{obs_name}'")
            agent.observe(node_map[obs_name])
        agents.append(agent)
    return agents

def _parse_announcements_list(ann_list: list[dict]) -> list[Announcement]:
    announcements = []
    for entry in ann_list:
        step = int(entry["step"])
        axioms = [Axiom.from_string(s) for s in entry.get("observations", [])]
        announcements.append(Announcement(step=step, observations=axioms))
    announcements.sort(key=lambda a: a.step)
    return announcements

def _parse_announcements_dict(ann_dict: dict) -> list[Announcement]:
    announcements = []
    for key, obs_list in ann_dict.items():
        step = _parse_announcement_key(str(key))
        if step is None:
            continue
        axioms = [Axiom.from_string(s) for s in (obs_list or [])]
        announcements.append(Announcement(step=step, observations=axioms))
    announcements.sort(key=lambda a: a.step)
    return announcements

def _parse_scenarios(raw_scenarios: list[dict], agents: list[Agent]) -> list[Scenario]:
    scenarios = []
    for entry in raw_scenarios:
        sid = int(entry["id"])
        description = entry.get("description", f"Scenario {sid}")
        tools = entry.get("tools_in_hand", [])
        agent_name = _resolve_agent_name(tools, agents)
        max_faults = int(entry.get("max_faults", 1))
        if max_faults < 1:
            raise ValueError(f"Scenario {sid}: max_faults must be >= 1, got {max_faults}.")

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
            max_faults=max_faults,
        ))

    scenarios.sort(key=lambda s: s.id)
    return scenarios

def load_circuit(path: str) -> tuple[EpistemicModel, list[Scenario]]:
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    if raw is None:
        raise ValueError(f"'{path}' is empty or not valid YAML.")

    raw_nodes = raw.get("nodes")
    if not raw_nodes:
        raise ValueError(f"'{path}' is missing a 'nodes:' section.")
    nodes = _parse_nodes(raw_nodes)
    node_map: dict[str, Node] = {n.name: n for n in nodes}

    # parse relationships
    raw_rels = raw.get("relationships", [])
    relationships, possible_deps_from_rels = _parse_relationships(raw_rels, node_map)

    # Merge both sources — duplicates are the user's responsibility
    all_possible_deps = possible_deps_from_rels 

    raw_agents = raw.get("agents", [])
    agents = _parse_agents(raw_agents, node_map) 

    model = EpistemicModel()
    for node in nodes:
        model.add_node(node)
    for rel in relationships:
        model.add_relationship(rel)
    for dep in all_possible_deps:
        model.add_possible_dependency(dep)
    for agent in agents:
        model.add_agent(agent)

    raw_scenarios = raw.get("scenarios", [])
    scenarios = _parse_scenarios(raw_scenarios, agents)

    return model, scenarios
