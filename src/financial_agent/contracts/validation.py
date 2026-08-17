from collections import defaultdict, deque
from collections.abc import Collection, Iterable


def require_unique_ids(ids: Iterable[str], *, label: str) -> None:
    values = list(ids)
    if len(values) != len(set(values)):
        raise ValueError(f"{label} contains duplicate IDs")


def require_known_ids(
    referenced: Iterable[str],
    available: Collection[str],
    *,
    label: str,
) -> None:
    unknown = sorted(set(referenced) - set(available))
    if unknown:
        raise ValueError(f"{label} contains unknown IDs: {unknown}")


def require_acyclic_edges(
    node_ids: Collection[str],
    edges: Iterable[tuple[str, str]],
) -> None:
    nodes = set(node_ids)
    edge_list = list(edges)
    require_unique_ids(
        (f"{left}->{right}" for left, right in edge_list),
        label="edges",
    )

    adjacency: dict[str, set[str]] = defaultdict(set)
    indegree = {node: 0 for node in nodes}
    for left, right in edge_list:
        require_known_ids((left, right), nodes, label="edge")
        if left == right:
            raise ValueError("self dependency is not allowed")
        adjacency[left].add(right)
        indegree[right] += 1

    ready = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    processed = 0
    while ready:
        node = ready.popleft()
        processed += 1
        for target in sorted(adjacency[node]):
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    if processed != len(nodes):
        raise ValueError("dependency graph contains a cycle")
