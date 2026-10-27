#!/usr/bin/env python3
"""Query lanhu annotations.json with safe, reusable filters."""

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set


def load_annotations(path: Path) -> Dict[str, Any]:
    if path.is_dir():
        path = path / "annotations.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_node_ids(args: argparse.Namespace) -> Set[str]:
    values: List[str] = []
    if args.node_id:
        values.extend(args.node_id)
    if args.node_ids:
        values.extend(args.node_ids)

    result = set()
    for value in values:
        for item in re.split(r"[\s,]+", value):
            item = item.strip()
            if item:
                result.add(item)
    return result


def match_node(node_id: str, node: Dict[str, Any], args: argparse.Namespace, exact_node_ids: Set[str]) -> bool:
    if exact_node_ids and node_id not in exact_node_ids:
        return False

    name = str(node.get("name", ""))
    text_content = str((node.get("text") or {}).get("content", ""))

    if args.search:
        haystack = f"{node_id} {name} {text_content}"
        if not any(term in haystack for term in args.search):
            return False

    if args.name_contains and not any(term in name for term in args.name_contains):
        return False

    if args.text_contains and not any(term in text_content for term in args.text_contains):
        return False

    y = number(node.get("y"))
    if args.y_min is not None and y < args.y_min:
        return False
    if args.y_max is not None and y > args.y_max:
        return False

    x = number(node.get("x"))
    if args.x_min is not None and x < args.x_min:
        return False
    if args.x_max is not None and x > args.x_max:
        return False

    style = node.get("style") or {}
    if args.bg and style.get("backgroundColor") != args.bg:
        return False

    radius = number(style.get("borderRadius"))
    if args.radius_gt is not None and radius <= args.radius_gt:
        return False
    if args.radius_min is not None and radius < args.radius_min:
        return False

    if args.has_slice and "slice" not in node:
        return False
    if args.has_text and "text" not in node:
        return False

    return True


def compact_node(node_id: str, node: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "id": node_id,
        "name": node.get("name"),
        "type": node.get("type"),
        "x": node.get("x"),
        "y": node.get("y"),
        "width": node.get("width"),
        "height": node.get("height"),
    }
    if node.get("text"):
        result["text"] = node["text"]
    if node.get("style"):
        result["style"] = node["style"]
    if node.get("slice"):
        result["slice"] = node["slice"]
    if node.get("children"):
        result["children"] = node["children"]
    return result


def add_child_nodes(payload: Dict[str, Any], node: Dict[str, Any], nodes: Dict[str, Dict[str, Any]],
                    depth: int, seen: set):
    """按 depth 递归展开子节点。depth=1 等价于旧的 --with-children（只展开直接子节点）。

    seen 记录当前分支已展开的 id，防止异常数据成环导致无限递归。
    """
    if depth <= 0:
        return
    child_nodes = []
    for child_id in node.get("children") or []:
        if child_id in seen:
            continue
        child = nodes.get(child_id)
        if not child:
            continue
        entry = compact_node(child_id, child)
        add_child_nodes(entry, child, nodes, depth - 1, seen | {child_id})
        child_nodes.append(entry)
    if child_nodes:
        payload["child_nodes"] = child_nodes


def add_related_nodes(payload: Dict[str, Any], node: Dict[str, Any], nodes: Dict[str, Dict[str, Any]], args: argparse.Namespace):
    # 子节点展开深度: --depth N 优先; 否则 --with-children = 1 层
    depth = args.depth if getattr(args, "depth", 0) and args.depth > 0 else (1 if args.with_children else 0)
    if depth:
        add_child_nodes(payload, node, nodes, depth, {payload["id"]})

    if args.with_parent:
        parent_id = None
        for candidate_id, candidate in nodes.items():
            if payload["id"] in (candidate.get("children") or []):
                parent_id = candidate_id
                break
        if parent_id and parent_id in nodes:
            payload["parent_node"] = compact_node(parent_id, nodes[parent_id])


def print_name_list(nodes: Dict[str, Dict[str, Any]], args: argparse.Namespace) -> int:
    rows = []
    for node_id, node in nodes.items():
        rows.append((
            number(node.get("y")),
            number(node.get("x")),
            str(node.get("name", "")),
            str((node.get("text") or {}).get("content", "")),
            node_id,
            str(node.get("type", "")),
        ))

    if args.sort == "x":
        rows.sort(key=lambda item: (item[1], item[0], item[2]))
    elif args.sort == "name":
        rows.sort(key=lambda item: (item[2], item[0], item[1]))
    else:
        rows.sort(key=lambda item: (item[0], item[1], item[2]))

    print(f"names: {len(rows)}")
    for y, x, name, text, node_id, node_type in rows[: args.limit]:
        label = name
        if text and text != name:
            label = f"{name} | text={text}"
        print(f"{node_id}\t{node_type}\tx={x:g}\ty={y:g}\t{label}")

    if len(rows) > args.limit:
        print(f"... truncated {len(rows) - args.limit} more")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query lanhu annotations nodes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python lanhu_query.py <extract_dir> --list-names --sort y --limit 120
  python lanhu_query.py <extract_dir> --search "写日记" --search "标题" --sort y --limit 80
  python lanhu_query.py <extract_dir> --text "确定" --sort y --limit 20
  python lanhu_query.py <extract_dir> --bg "#FFFFFF" --radius-gt 10 --y-min 300 --y-max 760 --sort y --limit 40
  python lanhu_query.py <extract_dir> --node-id "1493F378"
  python lanhu_query.py <extract_dir> --node-ids "id1,id2,id3" --with-children --compact-output
  python lanhu_query.py <extract_dir> --node-ids "id1,id2,id3" --depth 2 --compact-output
""",
    )
    parser.add_argument("path", help="extract directory or annotations.json path")
    parser.add_argument("--node-id", action="append", help="exact node id to include")
    parser.add_argument("--node-ids", nargs="+", help="exact node ids; comma or whitespace separated")
    parser.add_argument("--search", "--searchr", "--sear", action="append", dest="search",
                        help="match node id, name, or text.content substring")
    parser.add_argument("--name-contains", "--name", action="append", dest="name_contains",
                        help="match node name substring")
    parser.add_argument("--text-contains", "--text", action="append", dest="text_contains",
                        help="match text.content substring")
    parser.add_argument("--x-min", type=float)
    parser.add_argument("--x-max", type=float)
    parser.add_argument("--y-min", type=float)
    parser.add_argument("--y-max", type=float)
    parser.add_argument("--bg", help="match style.backgroundColor exactly")
    parser.add_argument("--radius-gt", type=float, help="match borderRadius greater than value")
    parser.add_argument("--radius-min", type=float, help="match borderRadius greater/equal value")
    parser.add_argument("--has-slice", action="store_true")
    parser.add_argument("--has-text", action="store_true")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--sort", choices=("none", "x", "y", "name"), default="y")
    parser.add_argument("--list-names", "--names", action="store_true",
                        help="list all node names with id/type/x/y")
    parser.add_argument("--full", action="store_true", help="print full node JSON")
    parser.add_argument("--with-children", action="store_true", help="include immediate child node details")
    parser.add_argument("--depth", type=int, default=0,
                        help="递归展开子节点到第 N 层(1 层等价于 --with-children; 深层节点如角标组/Tab 图标组用 2~3)")
    parser.add_argument("--with-parent", action="store_true", help="include immediate parent node details")
    parser.add_argument("--compact-output", action="store_true", help="print one compact JSON object")
    args = parser.parse_args()

    data = load_annotations(Path(args.path).expanduser())
    nodes = data.get("nodes") or {}
    exact_node_ids = parse_node_ids(args)

    if args.list_names:
        return print_name_list(nodes, args)

    matches = []
    for node_id, node in nodes.items():
        if match_node(node_id, node, args, exact_node_ids):
            matches.append((node_id, node))

    if args.sort == "x":
        matches.sort(key=lambda item: (number(item[1].get("x")), number(item[1].get("y"))))
    elif args.sort == "y":
        matches.sort(key=lambda item: (number(item[1].get("y")), number(item[1].get("x"))))
    elif args.sort == "name":
        matches.sort(key=lambda item: str(item[1].get("name", "")))

    output_nodes = []
    for node_id, node in matches[: args.limit]:
        payload = node if args.full else compact_node(node_id, node)
        add_related_nodes(payload, node, nodes, args)
        output_nodes.append(payload)

    if args.compact_output:
        print(json.dumps({
            "matches": len(matches),
            "shown": len(output_nodes),
            "nodes": output_nodes,
        }, ensure_ascii=False, separators=(",", ":")))
        if len(matches) > args.limit:
            print(f"... truncated {len(matches) - args.limit} more")
        return 0

    print(f"matches: {len(matches)}")
    for payload in output_nodes:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    if len(matches) > args.limit:
        print(f"... truncated {len(matches) - args.limit} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
