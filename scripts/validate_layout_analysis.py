#!/usr/bin/env python3
"""Validate lanhu layout_analysis.json before implementation stages."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# 必填字段与 schemas/layout-analysis-schema.md 保持同步，修改 schema 后必须同步更新本列表。
REQUIRED_TOP_LEVEL_FULL = [
    "schema_version",
    "design_id",
    "source",
    "confidence",
    "layout_summary",
    "screen_type",
    "screenshot_review",
    "user_intent",
    "android_layout_assumptions",
    "confirmation_items",
    "root_layout_recommendation",
    "sections",
    "fixed_regions",
    "scroll_strategy",
    "element_classification",
    "background_layers",
    "component_groups",
    "constraint_hints",
    "implementation_hints",
    "risk_flags",
]

# 降级模式下只检查的核心字段；缺失的其他字段降级为 WARNING 而非 ERROR。
REQUIRED_TOP_LEVEL_DEGRADED = [
    "schema_version",
    "design_id",
    "source",
    "confidence",
    "layout_summary",
    "screenshot_review",
]

# 旁路文件匹配模式：排除 layout_analysis.json 自身，匹配所有以 layout_analysis 开头的衍生文件。
FORBIDDEN_SIBLING_PATTERNS = [
    "layout_analysis.json.*",
    "layout_analysis.*.json",
    "layout_analysis.review",
    "layout_analysis.partial.json",
    "layout0analysis",
    "layout0analysis.*",
]


def load_layout(path: Path) -> Tuple[Path, Optional[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    layout_path = path / "layout_analysis.json" if path.is_dir() else path
    if not layout_path.exists():
        return layout_path, None, [f"missing layout_analysis.json: {layout_path}"]
    try:
        payload = json.loads(layout_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return layout_path, None, [f"invalid JSON: {exc}"]
    if not isinstance(payload, dict):
        errors.append("layout_analysis root must be a JSON object")
        return layout_path, None, errors
    return layout_path, payload, errors


def list_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def is_skeleton(payload: Dict[str, Any]) -> bool:
    """识别 parser 生成的未加工骨架，而非有硬伤的产物。

    骨架的特征是「尚未分析」而不是「分析错了」：没有通过截图视觉分析，且没有任何结构内容。
    对骨架套用阻塞判定，会把纯 extract 任务误报成不合格产物（历史语料中 67/216 属此类），
    导致门禁结论没有下游会消费。因此骨架单独归为待补状态。
    """
    review = payload.get("screenshot_review")
    viewed = review.get("viewed") if isinstance(review, dict) else None
    if viewed is True:
        return False
    structural = ("sections", "element_classification", "component_groups")
    return all(list_len(payload.get(field)) == 0 for field in structural)


def has_risk(payload: Dict[str, Any], code: str) -> bool:
    risks = payload.get("risk_flags")
    if not isinstance(risks, list):
        return False
    return any(isinstance(item, dict) and item.get("code") == code for item in risks)


def text_contains_background_hint(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    keywords = ("背景", "底图", "装饰", "托底", "渐变", "遮罩", "大尺寸切图")
    for item in value:
        if isinstance(item, str) and any(keyword in item for keyword in keywords):
            return True
    return False


def validate_background_layers(payload: Dict[str, Any], confidence: Any, degraded: bool) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    layers = payload.get("background_layers")
    if not isinstance(layers, list):
        if degraded and "background_layers" not in payload:
            warnings.append("degraded mode: background_layers absent")
        else:
            errors.append("background_layers must be a list")
        layers = []

    allowed_sources = {"slice", "shape", "color"}

    for index, layer in enumerate(layers):
        prefix = f"background_layers[{index}]"
        if not isinstance(layer, dict):
            errors.append(f"{prefix} must be an object")
            continue
        source = layer.get("source")
        # source 驱动下游落地方式（slice→切图 / shape→drawable / color→背景色），保持强校验。
        # role / scope 仅描述性，历史语料中大量自定义取值且不驱动任何下游动作，故不校验。
        if source not in allowed_sources:
            errors.append(f"{prefix}.source must be one of: slice, shape, color")
        if "must_implement" in layer and not isinstance(layer.get("must_implement"), bool):
            warnings.append(f"{prefix}.must_implement should be a boolean")

    review = payload.get("screenshot_review")
    evidence = review.get("evidence") if isinstance(review, dict) else []
    has_background_evidence = text_contains_background_hint(evidence)
    has_background_category = False
    elements = payload.get("element_classification")
    if isinstance(elements, list):
        has_background_category = any(
            isinstance(item, dict) and item.get("category") == "backgrounds"
            for item in elements
        )

    if has_background_evidence and not layers and not has_background_category:
        message = (
            "screenshot_review mentions visible background/decoration, "
            "but background_layers is empty and no element_classification.category=backgrounds exists"
        )
        if confidence == "high":
            errors.append(message)
        else:
            warnings.append(message)

    if has_background_category and not layers:
        message = (
            "element_classification contains backgrounds, but background_layers is empty"
        )
        if confidence == "high":
            errors.append(message)
        else:
            warnings.append(message)

    return errors, warnings


def validate(layout_path: Path, payload: Dict[str, Any], degraded: bool = False) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    required = REQUIRED_TOP_LEVEL_DEGRADED if degraded else REQUIRED_TOP_LEVEL_FULL
    missing = [key for key in required if key not in payload]
    if missing:
        errors.append("missing required top-level fields: " + ", ".join(missing))

    # 降级模式下，非核心字段的缺失降级为 WARNING 而非 ERROR。
    if degraded:
        non_core_missing = [key for key in REQUIRED_TOP_LEVEL_FULL if key not in payload and key not in REQUIRED_TOP_LEVEL_DEGRADED]
        if non_core_missing:
            warnings.append("degraded mode: non-core fields absent (expected for minimal skeleton): " + ", ".join(non_core_missing))

    dirname = layout_path.parent
    for entry in dirname.iterdir():
        if entry.name == "layout_analysis.json":
            continue
        for pattern in FORBIDDEN_SIBLING_PATTERNS:
            if fnmatch.fnmatch(entry.name, pattern):
                errors.append(f"forbidden sidecar output exists: {entry}")
                break

    review = payload.get("screenshot_review")
    if not isinstance(review, dict):
        errors.append("screenshot_review must be an object")
        review = {}

    if review.get("viewed") is not True:
        errors.append("screenshot_review.viewed must be true")

    confidence = payload.get("confidence")
    if confidence not in {"high", "medium", "low"}:
        errors.append("confidence must be one of: high, medium, low")

    evidence_count = list_len(review.get("evidence"))
    coverage_count = list_len(review.get("coverage"))
    # screenshot_review 门禁：所有 confidence 级别都需基本证据
    if evidence_count < 3:
        errors.append("screenshot_review.evidence must contain at least 3 observations")
    if coverage_count < 1:
        errors.append("screenshot_review.coverage must not be empty")

    # confidence=high 额外冲突检查：仅检查与 risk_flags 的矛盾（证据/覆盖不足已在上面独立报错，此处不重复）
    if confidence == "high" and has_risk(payload, "missing_visual_review"):
        errors.append(
            "confidence=high conflicts with risk_flags.missing_visual_review"
        )

    summary = str(payload.get("layout_summary", "")).strip()
    if not summary or "占位" in summary or "基础布局分析" in summary:
        warnings.append("layout_summary still looks like a placeholder")

    screen_type = payload.get("screen_type")
    if screen_type == "unknown":
        warnings.append("screen_type is unknown; continue only for degraded/basic analysis")

    structural_counts = [
        list_len(payload.get("sections")),
        list_len(payload.get("element_classification")),
        list_len(payload.get("component_groups")),
        list_len(payload.get("constraint_hints")),
    ]
    if max(structural_counts) == 0:
        warnings.append("all structural fields are empty (sections, element_classification, component_groups, constraint_hints); verify this is intentional for simple screens")

    background_errors, background_warnings = validate_background_layers(payload, confidence, degraded)
    errors.extend(background_errors)
    warnings.extend(background_warnings)

    unresolved = []
    confirmations = payload.get("confirmation_items")
    if isinstance(confirmations, list):
        for item in confirmations:
            if isinstance(item, dict) and item.get("resolved") is False:
                severity = item.get("severity", "medium")
                if severity in {"high", "blocker"}:
                    unresolved.append(str(item.get("id", "unknown")))
    if unresolved:
        errors.append("unresolved high-severity confirmation_items: " + ", ".join(unresolved))

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate lanhu layout_analysis.json")
    parser.add_argument("path", help="extract directory or layout_analysis.json path")
    parser.add_argument("--degraded", action="store_true", help="degraded mode: only core fields are required; non-core missing fields become WARNING instead of ERROR")
    args = parser.parse_args()

    layout_path, payload, load_errors = load_layout(Path(args.path))
    errors = list(load_errors)
    warnings: List[str] = []
    skeleton = False
    if payload is not None:
        validate_errors, validate_warnings = validate(layout_path, payload, degraded=args.degraded)
        errors.extend(validate_errors)
        warnings.extend(validate_warnings)
        skeleton = not load_errors and is_skeleton(payload)

    # 三值状态：ready 可进入实现；needs_enrichment 是「尚未分析」的待办而非失败；
    # blocked 才是会产生错误布局的硬伤。门禁结论必须能被下游动作消费。
    if load_errors:
        status = "blocked"
        next_action = "产物不可读，先修复 JSON 结构或补回 layout_analysis.json 再重试"
    elif skeleton:
        status = "needs_enrichment"
        next_action = "当前仅为 extract 骨架，先补截图视觉分析（screenshot_review）与结构字段，再进入实现阶段"
    elif errors:
        status = "blocked"
        next_action = "下列 errors 会直接导致生成的布局与设计稿不符，修复后重试"
    else:
        status = "ready"
        next_action = "可进入实现阶段"

    result = {
        "status": status,
        "next_action": next_action,
        "layout_analysis": str(layout_path),
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # needs_enrichment 是合法中间状态，不应让调用方按失败处理。
    return 0 if status in {"ready", "needs_enrichment"} else 1


if __name__ == "__main__":
    sys.exit(main())
