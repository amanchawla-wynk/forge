"""Disposable executable comparison for D-050.

Run without modifying Forge's production dependencies:

    uv run --with langgraph==1.0.8 --with langgraph-checkpoint-sqlite \
      --with llama-index-core==0.14.6 python spikes/graph_framework_comparison.py
"""

from __future__ import annotations

import json
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from typing import TypedDict

from forge.deep_review import RequirementGraph, RequirementGraphEdge, RequirementGraphNode


def langgraph_spike(root: Path) -> dict[str, object]:
    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Command, interrupt

    class State(TypedDict, total=False):
        review_id: str
        question: str
        answer: str
        node_entries: int

    def collect_answer(state: State) -> dict[str, object]:
        # LangGraph resumes by replaying the node, so work before interrupt must
        # be idempotent or moved to a separate node.
        answer = interrupt({"question": state["question"]})
        return {
            "answer": str(answer),
            "node_entries": state.get("node_entries", 0) + 1,
        }

    builder = StateGraph(State)
    builder.add_node("collect_answer", collect_answer)
    builder.add_edge(START, "collect_answer")
    builder.add_edge("collect_answer", END)

    db_path = root / "langgraph-spike.sqlite3"
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        graph = builder.compile(checkpointer=saver)
        config = {"configurable": {"thread_id": "forge-review-spike"}}
        started = graph.invoke(
            {
                "review_id": "forge-review-spike",
                "question": "Which rule wins?",
                "node_entries": 0,
            },
            config,
        )
        resumed = graph.invoke(Command(resume="editorial_source"), config)
        current = graph.get_state(config)
        history = list(graph.get_state_history(config))

    return {
        "version": version("langgraph"),
        "interrupt_exposed": "__interrupt__" in started,
        "resume_answer": resumed.get("answer"),
        "thread_id_maps_to_review_id": current.config["configurable"]["thread_id"]
        == "forge-review-spike",
        "checkpoint_count": len(history),
        "sqlite_created": db_path.exists(),
        "native_operation_digest_guard": False,
        "native_source_rubric_workspace_binding": False,
        "assessment": (
            "Useful checkpoint/interrupt runtime, but Forge must retain its own "
            "review identity, optimistic version, operation digest, ownership, "
            "and legal-transition guards."
        ),
    }


def forge_graph_spike(size: int = 100) -> tuple[dict[str, object], RequirementGraph]:
    started = time.perf_counter()
    nodes = [
        RequirementGraphNode(
            node_id=f"claim:{index}",
            kind="claim",
            label=f"Claim {index}",
            claim_id=f"claim-{index}",
        )
        for index in range(size)
    ]
    edges = [
        RequirementGraphEdge(
            edge_id=f"edge:{index}",
            source_id=f"claim:{index}",
            target_id=f"claim:{index + 1}",
            relation="scheduled_on",
            claim_id=f"claim-{index}",
        )
        for index in range(size - 1)
    ]
    graph = RequirementGraph(nodes=nodes, edges=edges)
    elapsed = time.perf_counter() - started
    return (
        {
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "build_seconds": round(elapsed, 6),
            "external_dependency": False,
        },
        graph,
    )


def llama_index_spike(graph: RequirementGraph) -> dict[str, object]:
    from llama_index.core.graph_stores import (
        EntityNode,
        Relation,
        SimplePropertyGraphStore,
    )

    started = time.perf_counter()
    store = SimplePropertyGraphStore()
    nodes = [
        EntityNode(
            name=node.node_id,
            label=node.kind,
            properties={"claim_id": node.claim_id or "", "label": node.label},
        )
        for node in graph.nodes
    ]
    node_ids = {node.name: node.id for node in nodes}
    relations = [
        Relation(
            label=edge.relation,
            source_id=node_ids[edge.source_id],
            target_id=node_ids[edge.target_id],
            properties={"claim_id": edge.claim_id, "edge_id": edge.edge_id},
        )
        for edge in graph.edges
    ]
    store.upsert_nodes(nodes)
    store.upsert_relations(relations)
    # A second upsert checks whether stable entity identity avoids duplicates.
    store.upsert_nodes(nodes)
    stored_nodes = store.get()
    # `get_triplets()` returns [] unless a filter is supplied, so the unfiltered
    # graph must be read directly to count what was actually stored.
    triplets = store.graph.get_triplets()
    filtered = store.get_triplets(entity_names=[nodes[0].id])
    rel_map = store.get_rel_map([nodes[0]], depth=2)
    elapsed = time.perf_counter() - started
    return {
        "version": version("llama-index-core"),
        "node_count": len(stored_nodes),
        "relation_count": len(triplets),
        "filtered_triplet_count": len(filtered),
        "depth_2_traversal_count": len(rel_map),
        "duplicate_node_count_after_upsert": len(stored_nodes) - len(nodes),
        "build_and_read_seconds": round(elapsed, 6),
        "unfiltered_get_triplets_returns_empty": True,
        "exact_source_identity_requires_custom_properties": True,
        "assessment": (
            "The store can represent Forge's bounded graph, but adds an index "
            "abstraction without improving exact evidence verification or the "
            "current deterministic traversals."
        ),
    }


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="forge-graph-spike-") as directory:
        root = Path(directory)
        forge_result, graph = forge_graph_spike()
        result = {
            "langgraph": langgraph_spike(root),
            "forge_static_graph": forge_result,
            "llama_index_property_graph": llama_index_spike(graph),
            "recommendation": {
                "langgraph": "do_not_adopt_yet",
                "property_graph": "do_not_adopt",
                "reason": (
                    "The current Forge-owned SQLite state machine and static "
                    "graph already enforce domain-specific integrity with less "
                    "surface area. Revisit LangGraph only for concrete durable "
                    "branching or background execution needs."
                ),
            },
        }
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
