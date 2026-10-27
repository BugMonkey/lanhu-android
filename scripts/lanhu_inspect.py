#!/usr/bin/env python3
"""Summarize lanhu extract outputs without ad-hoc python -c commands."""

import argparse
import hashlib
import json
import struct
import sys
import unicodedata
from pathlib import Path


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_json_path(path: Path) -> Path:
    """If path is a directory, look for raw.json inside it."""
    if path.is_dir():
        candidate = path / "raw.json"
        if candidate.exists():
            print(f"# 提示: 传入的是目录，自动使用 {candidate}", file=sys.stderr)
            return candidate
        else:
            print(f"# 错误: 传入的是目录且未找到 raw.json: {candidate}", file=sys.stderr)
            return candidate  # return non-existent path for clean "not found" error
    return path


def count(value):
    return len(value) if isinstance(value, (list, dict)) else 0


def png_dimensions(path: Path):
    if not path.exists():
        return None
    try:
        with open(path, "rb") as f:
            header = f.read(24)
        if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
            return struct.unpack(">II", header[16:24])
    except OSError:
        return None
    return None


def summarize_json_file(path: Path, max_keys: int = 30):
    path = resolve_json_path(path)
    data = load_json(path)
    if data is None:
        print(json.dumps({"error": f"not found: {path}"}, ensure_ascii=False, indent=2))
        return 1

    image_like = []
    queue = [("$", data)]
    while queue and len(image_like) < 40:
        current_path, value = queue.pop(0)
        if isinstance(value, dict):
            for key, child in list(value.items())[:80]:
                child_path = f"{current_path}.{key}"
                key_lower = str(key).lower()
                if isinstance(child, str):
                    child_lower = child.lower()
                    has_image_key = any(token in key_lower for token in ("image", "cover", "thumbnail", "screenshot", "url"))
                    has_image_url = child_lower.startswith("http") and any(
                        token in child_lower
                        for token in (".png", ".jpg", ".jpeg", ".webp", "figmacover", "sketchcover")
                    )
                    if has_image_key or has_image_url:
                        image_like.append({
                            "path": child_path,
                            "value": child[:180],
                            "length": len(child),
                        })
                elif isinstance(child, (dict, list)):
                    queue.append((child_path, child))
        elif isinstance(value, list):
            for index, child in enumerate(value[:30]):
                if isinstance(child, (dict, list)):
                    queue.append((f"{current_path}[{index}]", child))

    top_level = {}
    if isinstance(data, dict):
        for key, value in list(data.items())[:max_keys]:
            if isinstance(value, dict):
                top_level[key] = {"type": "dict", "keys": list(value.keys())[:10], "size": len(value)}
            elif isinstance(value, list):
                top_level[key] = {"type": "list", "size": len(value)}
            elif isinstance(value, str):
                top_level[key] = {"type": "str", "length": len(value), "preview": value[:120]}
            else:
                top_level[key] = {"type": type(value).__name__, "value": value}
    else:
        top_level = {"$": {"type": type(data).__name__, "size": count(data)}}

    payload = {
        "json_file": str(path),
        "root_type": type(data).__name__,
        "top_level": top_level,
        "image_like_fields": image_like,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _try_extract_color_triplet(value: dict, path: str) -> dict | None:
    """Detect r/g/b or red/green/blue numeric color triplet (Sketch/Fig JSON format).

    Sketch/Fig stores colors as numeric components inside a color dict, e.g.:
    {"r": 0.9647, "g": 0.9647, "b": 0.9647, "a": 1}
    Returns a dict with reconstructed hex value when detected, None otherwise.
    """
    def _to_255(v):
        if isinstance(v, float) and 0 <= v <= 1:
            return round(v * 255)
        if isinstance(v, (int, float)) and v >= 0:
            return int(v)
        return None

    # Check for RGB triplet (r/g/b or red/green/blue)
    r_val = value.get("r") or value.get("red") or value.get("Red")
    g_val = value.get("g") or value.get("green") or value.get("Green")
    b_val = value.get("b") or value.get("blue") or value.get("Blue")

    if r_val is not None and g_val is not None and b_val is not None:
        if all(isinstance(v, (int, float)) for v in (r_val, g_val, b_val)):
            r, g, b = _to_255(r_val), _to_255(g_val), _to_255(b_val)
            if all(v is not None for v in (r, g, b)):
                return {
                    "path": path,
                    "key": "color_triplet",
                    "encoding": "rgb_triplet",
                    "hex": f"#{r:02X}{g:02X}{b:02X}",
                    "value": f"r={r_val}, g={g_val}, b={b_val}",
                }
    return None


def summarize_json_colors(path: Path, max_items: int = 80):
    path = resolve_json_path(path)
    data = load_json(path)
    if data is None:
        print(json.dumps({"error": f"not found: {path}"}, ensure_ascii=False, indent=2))
        return 1

    results = []
    queue = [("$", data)]
    while queue and len(results) < max_items:
        current_path, value = queue.pop(0)
        if isinstance(value, dict):
            # Pre-check: detect color triplet (r/g/b or red/green/blue) before iterating keys
            triplet = _try_extract_color_triplet(value, current_path)
            if triplet:
                results.append(triplet)

            for key, child in list(value.items())[:200]:
                child_path = f"{current_path}.{key}"
                key_lower = str(key).lower()
                if isinstance(child, str):
                    child_upper = child.upper()
                    if "color" in key_lower or child_upper.startswith("#"):
                        results.append({
                            "path": child_path,
                            "key": key,
                            "value": child[:120],
                        })
                elif isinstance(child, (int, float)):
                    # Catch shorthand "a"/"opacity" (not just full "alpha")
                    if key_lower in ("alpha", "a", "opacity"):
                        results.append({
                            "path": child_path,
                            "key": key,
                            "value": child,
                        })
                elif isinstance(child, (dict, list)):
                    if any(token in key_lower for token in ("style", "fill", "border", "shadow", "color", "background")):
                        queue.append((child_path, child))
                    elif len(results) < max_items:
                        queue.append((child_path, child))
        elif isinstance(value, list):
            for index, child in enumerate(value[:80]):
                if isinstance(child, (dict, list)):
                    queue.append((f"{current_path}[{index}]", child))

    # Detect what color encoding was found in the results
    has_hex = any(
        r.get("value") and isinstance(r["value"], str) and r["value"].startswith("#")
        for r in results
    )
    has_triplet = any(r.get("encoding") == "rgb_triplet" for r in results)
    if has_hex and has_triplet:
        encoding_detected = "mixed"
    elif has_triplet:
        encoding_detected = "rgb_triplet"
    elif has_hex:
        encoding_detected = "hex_string"
    else:
        encoding_detected = "none"

    payload = {
        "json_file": str(path),
        "matches": len(results),
        "encoding_detected": encoding_detected,
        "color_like_fields": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


# 参与内容比对的资源扩展名
ASSET_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg", ".gif")
# 遍历资源目录时跳过的目录（构建产物会重复每一个资源，造成假命中）
SKIP_DIR_NAMES = {"build", ".git", ".svn", ".gradle", "intermediates"}


def file_md5(path: Path) -> str:
    """文件内容 md5（分块读取，避免大图占内存）。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 256), b""):
            h.update(chunk)
    return h.hexdigest()


def drawable_stem(file_name: str) -> str:
    """取 drawable 资源名。九宫格 foo.9.png → foo（Android 以 @drawable/foo 引用）。"""
    lower = file_name.lower()
    if lower.endswith(".9.png"):
        return lower[: -len(".9.png")]
    for suffix in ASSET_SUFFIXES:
        if lower.endswith(suffix):
            return lower[: -len(suffix)]
    return lower


def is_nine_patch(file_name: str) -> bool:
    return file_name.lower().endswith(".9.png")


def build_asset_index(res_dir: Path) -> tuple:
    """遍历项目资源目录，建立 md5 → 文件列表 的内容索引。

    Returns:
        (index, name_index, scanned)
        index:      {md5: [相对路径, ...]}
        name_index: {drawable 资源名: [相对路径, ...]}
        scanned:    扫描到的资源文件总数
    """
    index = {}
    name_index = {}
    scanned = 0
    for path in sorted(res_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES for part in path.parts):
            continue
        if not path.name.lower().endswith(ASSET_SUFFIXES):
            continue
        scanned += 1
        rel = str(path.relative_to(res_dir))
        try:
            index.setdefault(file_md5(path), []).append(rel)
        except OSError:
            continue
        name_index.setdefault(drawable_stem(path.name), []).append(rel)
    return index, name_index, scanned


def _display_width(text: str) -> int:
    """按终端显示宽度计算长度（CJK 全角字符占 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    """按显示宽度左对齐补空格，使中文列头与数据列对齐。"""
    return text + " " * max(0, width - _display_width(text))


def _project_hit(project_file: Path, rel: str, md5: str) -> dict:
    """构造一条项目侧命中记录（路径 / md5 / 像素尺寸 / 资源名）。"""
    dims = png_dimensions(project_file)
    return {
        "rel": rel,
        "md5": md5,
        "size": f"{dims[0]}x{dims[1]}" if dims else "?",
        "stem": drawable_stem(Path(rel).name),
        "nine_patch": is_nine_patch(Path(rel).name),
    }


def compare_assets(root: Path, slices, res_dir: Path) -> int:
    """把设计稿切图与项目现有资源做内容同一性比对。

    判定以**内容 md5** 为准，不以文件名为准：文件名与内容可以不一致
    （设计稿同名图层会得到 _2 去重后缀，项目侧命名又可能与设计稿完全不同）。
    **内容一致只说明"这张图的字节已存在于项目中"，不等于可以直接引用到当前节点**——
    项目侧资源名与设计稿不同时，必须确认其用途与本节点一致。
    逐条回显每张切图的 md5，禁止只输出聚合结论。
    """
    if not res_dir.is_dir():
        print(f"ERROR: --compare-assets 需要一个存在的资源目录: {res_dir}")
        return 1

    items = (slices or {}).get("slices", [])
    if isinstance(items, dict):
        # 兼容 {"slices": {"items": [...]}} 形式；只认列表，其余一律明确报错
        items = items.get("items") or items.get("list") or []
    if not items:
        print(f"ERROR: {root / 'slices.json'} 中没有切图条目，无法比对")
        return 1
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        print(f"ERROR: {root / 'slices.json'} 的 slices 结构无法识别"
              f"（期望对象数组），请重新执行 extract 生成")
        return 1

    index, name_index, scanned = build_asset_index(res_dir)

    print(f"# 资源同一性比对")
    print(f"extract_dir: {root}")
    print(f"res_dir:     {res_dir}（扫描 {scanned} 个资源文件，{len(index)} 个不同内容）")
    print()
    header = (
        f"{_pad('设计切图', 40)} {_pad('设计md5', 12)} {_pad('尺寸', 12)} "
        f"{_pad('项目文件', 58)} {_pad('项目md5', 12)} {_pad('尺寸', 12)} 判定"
    )
    print(header)
    print("-" * len(header))

    counters = {"reusable": 0, "new": 0, "same_name_diff": 0, "slice_missing": 0}
    rows = []

    for item in items:
        drawable = item.get("drawable_name") or item.get("name") or ""
        local_path = item.get("local_path", "")
        design_file = root / local_path if local_path else None
        row = {
            "drawable": drawable,
            "node_id": item.get("node_id", ""),
            "node_x": item.get("node_x"),
            "node_y": item.get("node_y"),
            "source_layer": item.get("source_layer", ""),
            "design_md5": "",
            "design_size": item.get("actual_size") or item.get("size") or "",
            "hits": [],
            "verdict": "",
        }

        if not design_file or not design_file.exists():
            counters["slice_missing"] += 1
            row["verdict"] = "slice_missing"
            rows.append(row)
            continue

        design_md5 = file_md5(design_file)
        row["design_md5"] = design_md5
        content_hits = index.get(design_md5, [])
        same_name_hits = name_index.get(drawable, [])

        if content_hits:
            counters["reusable"] += 1
            row["verdict"] = "content_match"
            for rel in content_hits:
                row["hits"].append(_project_hit(res_dir / rel, rel, design_md5))
        elif same_name_hits:
            counters["same_name_diff"] += 1
            row["verdict"] = "same_name_diff"
            for rel in same_name_hits:
                project_file = res_dir / rel
                try:
                    project_md5 = file_md5(project_file)
                except OSError:
                    project_md5 = ""
                row["hits"].append(_project_hit(project_file, rel, project_md5))
        else:
            counters["new"] += 1
            row["verdict"] = "new"
        rows.append(row)

    # 逐条回显：N 张切图至少 N 行，禁止聚合式结论
    for row in rows:
        name_cell = f"{row['drawable']}.png"
        short = row["design_md5"][:8] if row["design_md5"] else "(文件缺失)"
        if not row["hits"]:
            note = "切图文件缺失" if row["verdict"] == "slice_missing" else "项目内无同内容资源，需新增"
            print(
                f"{name_cell:<40} {_pad(short, 12)} {row['design_size']:<12} "
                f"{_pad('(无)', 58)} {'-':<12} {'-':<12} {note}"
            )
            continue
        for hit in row["hits"]:
            project_short = hit["md5"][:8] if hit["md5"] else "-"
            if row["verdict"] == "content_match":
                if hit["stem"] == row["drawable"]:
                    note = "内容一致（项目内同名）"
                else:
                    note = (
                        f"内容一致（项目侧名为 {hit['stem']}）"
                        "→ 引用前必须确认该资源在项目中的用途与本节点一致"
                    )
            elif hit["nine_patch"]:
                note = "同名不同内容（.9.png 含 1px 边框，字节必然不同，需视觉确认）"
            else:
                note = "同名不同内容（禁止按名字直接复用）"
            print(
                f"{name_cell:<40} {short:<12} {row['design_size']:<12} "
                f"{hit['rel']:<58} {project_short:<12} {hit['size']:<12} {note}"
            )

    total = len(items)
    print()
    print(
        f"汇总: {total} 张设计切图 → 内容已在项目中 {counters['reusable']} / "
        f"需新增 {counters['new']} / 同名不同内容 {counters['same_name_diff']} / "
        f"切图文件缺失 {counters['slice_missing']}"
    )

    # 同名图层组混淆风险：source_layer 相同但内容不同 → 归属只能靠 node_id / 坐标
    groups = {}
    for row in rows:
        if row["verdict"] == "slice_missing":
            continue
        if not row["source_layer"]:
            # 无图层名无法构成"同名"混淆，跳过以免产生假阳性分组
            continue
        groups.setdefault(row["source_layer"], []).append(row)
    risky = {
        layer: members
        for layer, members in groups.items()
        if len(members) >= 2 and len({m["design_md5"] for m in members}) > 1
    }
    if risky:
        print()
        print("## 同名图层组混淆风险")
        print("以下图层名在本次设计稿中出现多次且内容互不相同，归属只能按 node_id / 坐标判定：")
        for layer, members in risky.items():
            print(f"- 图层名 {layer}：{len(members)} 张")
            for m in members:
                stem = m["hits"][0]["stem"] if m["hits"] else "(项目内无同内容资源)"
                print(
                    f"    drawable={m['drawable']}  node_id={m['node_id']}  "
                    f"x={m['node_x']}  y={m['node_y']}  项目内同内容资源={stem}"
                )
        print("  禁止按图层名相似度、切图顺序或文件名后缀(_2/_3)猜测归属。")

    print()
    print("判定口径：")
    print("  - 「内容一致」= 项目里已存在字节完全相同的文件，可避免重复导入；")
    print("    项目侧资源名与设计稿不同时，引用前必须确认该资源在项目中的用途与当前节点一致。")
    print("  - 「同名不同内容」= 名字相同但内容不同，禁止按名字复用；需按 §7.7 用 node_id 定位。")
    print("  - 本表是资源来源的唯一依据；禁止用布尔聚合、手写循环或目测替代本表结论。")
    return 0


def compact_for_xml(root: Path, annotations, layout, slices, issues, max_slices: int, max_issues: int):
    nodes = annotations.get("nodes") or {}
    screenshot_path = root / "screenshot.png"
    raw_json_path = root / "raw.json"
    dimensions = png_dimensions(screenshot_path)

    text_count = 0
    slice_count = 0
    shape_count = 0
    for node in nodes.values():
        if node.get("text"):
            text_count += 1
        if node.get("slice"):
            slice_count += 1
        node_type = node.get("type")
        if node_type in ("Rectangle", "Oval") and not node.get("slice"):
            shape_count += 1

    slice_items = slices.get("slices", []) if slices else []
    missing = []
    compact_slices = []
    for item in slice_items:
        local_path = item.get("local_path", "")
        if local_path and not (root / local_path).exists():
            missing.append(local_path)
        if len(compact_slices) < max_slices:
            compact_slices.append({
                "drawable": item.get("drawable_name"),
                "path": local_path,
                "size": item.get("size"),
                "layer": item.get("source_layer"),
                "status": item.get("status"),
            })

    issue_items = issues.get("issues", []) if issues else []
    compact_issues = [
        {
            "type": item.get("type"),
            "layer": item.get("layer"),
            "description": item.get("description"),
        }
        for item in issue_items[:max_issues]
    ]

    payload = {
        "extract_dir": str(root),
        "artboard": annotations.get("artboard"),
        "scale": annotations.get("scale"),
        "screenshot": {
            "exists": screenshot_path.exists(),
            "path": str(screenshot_path) if screenshot_path.exists() else "",
            "width": dimensions[0] if dimensions else None,
            "height": dimensions[1] if dimensions else None,
        },
        "source_json": {
            "exists": raw_json_path.exists(),
            "path": str(raw_json_path) if raw_json_path.exists() else "",
        },
        "layout": {
            "screen_type": layout.get("screen_type"),
            "confidence": layout.get("confidence"),
            "summary": layout.get("layout_summary"),
            "root": (layout.get("root_layout_recommendation") or {}).get("type"),
            "sections": count(layout.get("sections")),
            "component_groups": count(layout.get("component_groups")),
            "constraint_hints": count(layout.get("constraint_hints")),
            "risk_flags": count(layout.get("risk_flags")),
        },
        "nodes": {
            "total": len(nodes),
            "text": text_count,
            "slice": slice_count,
            "shape_without_slice": shape_count,
        },
        "slices": {
            "total": len(slice_items),
            "shown": compact_slices,
            "missing_files": missing[:max_slices],
            "missing_total": len(missing),
        },
        "issues": {
            "total": len(issue_items),
            "shown": compact_issues,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查蓝湖提取产物摘要（提取产物目录 / compact 交接 / 原始 JSON 概览）",
    )
    parser.add_argument("extract_output_dir", nargs="?", help="提取产物目录（含 annotations.json、slices.json 等）")
    parser.add_argument(
        "--json-file-summary",
        nargs="?",
        const="",
        default=None,
        help="分析原始 Figma/Sketch JSON 的顶层结构和图片字段；传目录时自动查找 raw.json",
    )
    parser.add_argument(
        "--json-color-summary",
        nargs="?",
        const="",
        default=None,
        help="分析原始 JSON 中的颜色字段；传目录时自动查找 raw.json",
    )
    parser.add_argument(
        "--compact-for-xml",
        action="store_true",
        help="输出精简 JSON 摘要供 xml/create/restyle 使用，不 dump 完整 annotations",
    )
    parser.add_argument(
        "--compare-assets",
        metavar="RES_DIR",
        help="把 slices.json 的切图与项目资源目录（如 app/src/main/res）做内容 md5 同一性比对，输出「复用/新增」清单",
    )
    parser.add_argument("--max-slices", type=int, default=30, help="--json-file-summary 模式最多显示的顶层 key 数量（默认 30）")
    parser.add_argument("--max-issues", type=int, default=10, help="compact 模式最多显示的 issues 数量（默认 10）")
    args = parser.parse_args()

    if args.json_file_summary is not None:
        if not args.json_file_summary:
            print("ERROR: --json-file-summary requires a file path argument as value")
            return 1
        return summarize_json_file(Path(args.json_file_summary).expanduser(), max_keys=args.max_slices)

    if args.json_color_summary is not None:
        if not args.json_color_summary:
            print("ERROR: --json-color-summary requires a file path argument as value")
            return 1
        return summarize_json_colors(Path(args.json_color_summary).expanduser(), max_items=args.max_slices)

    if not args.extract_output_dir:
        print("ERROR: extract_output_dir is required unless --json-file-summary or --json-color-summary is used")
        return 1

    root = Path(args.extract_output_dir).expanduser()
    if not root.exists():
        print(f"ERROR: not found: {root}")
        return 1

    if root.is_file():
        # 默认模式下传入了文件路径 → 尝试父目录
        parent = root.parent
        if (parent / "annotations.json").exists():
            print(f"# 提示: 传入的是文件，自动使用父目录: {parent}", file=sys.stderr)
            root = parent
        else:
            print(
                f"ERROR: 传入的是文件路径({root})，但预计是提取产物目录。\n"
                f"如需分析原始 JSON 内容，请使用标志指定:\n"
                f"  --json-file-summary \"{root}\"    分析 JSON 顶层结构和图片字段\n"
                f"  --json-color-summary \"{root}\"   分析 JSON 中的颜色字段",
                file=sys.stderr,
            )
            return 1

    if not root.is_dir():
        print(f"ERROR: not a directory: {root}")
        return 1

    annotations = load_json(root / "annotations.json") or {}
    layout = load_json(root / "layout_analysis.json") or {}
    slices = load_json(root / "slices.json") or {}
    issues = load_json(root / "issues.json") or {}

    if args.compare_assets:
        return compare_assets(root, slices, Path(args.compare_assets).expanduser())

    if args.compact_for_xml:
        compact_for_xml(root, annotations, layout, slices, issues, args.max_slices, args.max_issues)
        return 0

    print(f"dir: {root}")

    if annotations:
        print("\nannotations.json")
        print(f"- artboard: {annotations.get('artboard')}")
        print(f"- scale: {annotations.get('scale')}")
        print(f"- index nodes: {count(annotations.get('index'))}")
        print(f"- detail nodes: {count(annotations.get('nodes'))}")
        legacy = annotations.get("layoutAnalysis") or {}
        print(f"- layoutAnalysis: { {k: count(v) for k, v in legacy.items()} }")

    if layout:
        print("\nlayout_analysis.json")
        print(f"- screen_type: {layout.get('screen_type')}")
        print(f"- confidence: {layout.get('confidence')}")
        print(f"- summary: {layout.get('layout_summary')}")
        for key in (
            "sections",
            "fixed_regions",
            "element_classification",
            "component_groups",
            "constraint_hints",
            "implementation_hints",
            "risk_flags",
        ):
            print(f"- {key}: {count(layout.get(key))}")

    if slices:
        items = slices.get("slices", [])
        missing = []
        statuses = {}
        for item in items:
            status = item.get("status", "")
            statuses[status] = statuses.get(status, 0) + 1
            local_path = item.get("local_path", "")
            if local_path and not (root / local_path).exists():
                missing.append(local_path)
        print("\nslices.json")
        print(f"- total: {len(items)}")
        print(f"- statuses: {statuses}")
        print(f"- missing files: {missing}")

    if issues:
        issue_items = issues.get("issues", [])
        print("\nissues.json")
        print(f"- total: {len(issue_items)}")
        for item in issue_items[:10]:
            print(f"- [{item.get('type')}] {item.get('layer')}: {item.get('description')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
