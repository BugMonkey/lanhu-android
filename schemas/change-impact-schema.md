---
name: lanhu-change-impact-schema
description: restyle_report.md 标准结构，用于老页面改造的计划、约束、执行结果与证据。
---

# Restyle Report Schema

老页面改造只输出一份 `restyle_report.md`，包含「执行前计划」与「执行结果证据」两部分。
可以使用 Markdown 报告，也可以同时生成 JSON；两者字段语义必须一致。

## 顶层结构

```json
{
  "schema_version": "2.0",
  "page": "HomeFragment",
  "design_id": "home_new",
  "rule_loads": [],
  "risk_level": "low | medium | high | blocked",
  "baseline": {},
  "concurrency_warnings": [],
  "referenced_ids": [],
  "protected_views": [],
  "planned_changes": [],
  "manual_confirmations": [],
  "execution": {},
  "annotation_table": [],
  "protection_verification": [],
  "compile": {}
}
```

## 字段说明

### `rule_loads`

规则加载表，见 [core-rules.md §0 第 0 步](../rules/core-rules.md#0-执行清单优先全局唯一权威版本)：

```json
{
  "file": "rules/resource-rules.md",
  "loaded": true,
  "trigger": "新增 shape 与切图"
}
```

### `risk_level`

| 值 | 定义 | 行为 |
|----|------|------|
| `low` | 主要是静态样式、尺寸、间距调整 | 可执行，报告风险 |
| `medium` | 涉及局部结构、资源、少量代码引用 | 输出计划后执行 |
| `high` | 涉及 Adapter、复杂绑定、关键 ID 删除或多文件联动 | 必须等待用户确认 |
| `blocked` | 无法定位页面、无法保护逻辑或缺关键输入 | 停止 |

### `baseline`

改造前必须采集的工作树基线，在 Phase 3 一开始记录。它是后续三件事的唯一依据：

1. 编译失败时判定报错文件**归属**（是否在本次改动集内）；
2. 编译被无关改动阻塞、需要临时打桩时，证明打桩前后**逐字节还原**；
3. 目标资源被并发修改时，能发现并提示，而不是静默覆盖。

```json
{
  "vcs": "git | svn",
  "captured_at": "2026-09-22 10:24",
  "worktree_dirty": true,
  "dirty_files": ["app/src/main/java/.../HomeFragment.kt", "app/src/main/res/layout/fragment_category.xml"],
  "target_hashes": [
    { "path": "app/src/main/res/layout/fragment_service.xml", "md5": "26f6c653c3359f3fed8a9b892ea7e9f6", "mtime": "2026-09-22 09:10" }
  ],
  "asset_hashes": [
    { "path": "app/src/main/res/drawable-xxhdpi/ic_tab_service_sel.png", "md5": "...", "mtime": "2026-09-22 10:24" }
  ]
}
```

- `dirty_files`：`git status --short` / `svn status` 的全部未提交项（含他人 WIP）。
- `target_hashes`：本次计划 `modify` 的文件（布局/代码）。
- `asset_hashes`：被这些布局引用的 drawable（切图与 shape）。

采集命令（macOS 用 `md5`，Linux 用 `md5sum`）：

```bash
git status --short          # 或 svn status
md5 <file>                  # 逐个目标文件与引用资源
```

### `concurrency_warnings`

目标文件/资源在本次会话之前被改过，或执行期间 md5 发生变化。**命中任一条必须提示用户，禁止静默覆盖。**

```json
{
  "path": "app/src/main/res/drawable-xxhdpi/ic_tab_service_sel.png",
  "detected_by": "mtime | md5",
  "detail": "该切图 mtime 为 2026-09-22 10:24，晚于本次会话开始（09:10）",
  "action": "已提示用户确认后再覆盖，未静默覆盖"
}
```

### `referenced_ids`

旧布局 ID 引用情况：

```json
{
  "id": "tv_price",
  "declared_in": "app/src/main/res/layout/item_shop.xml",
  "references": [
    {
      "path": "app/src/main/java/.../ShopAdapter.kt",
      "line": 42,
      "usage": "binding.tvPrice.text = item.price"
    }
  ],
  "decision": "keep | migrate | delete | needs_confirm",
  "replacement_id": "tv_subtitle",
  "notes": "设计稿取消价格展示，但代码仍写入价格"
}
```

### `protected_views`

必须保留或兼容的控件：

```json
{
  "id": "btn_submit",
  "reason": "承载点击提交逻辑和埋点",
  "allowed_changes": ["size", "margin", "background", "textColor"],
  "forbidden_changes": ["remove", "rename", "change_click_target"]
}
```

### `planned_changes`

计划修改项：

```json
{
  "file": "app/src/main/res/layout/fragment_home.xml",
  "change": "调整标题栏高度、按钮背景和列表顶部间距",
  "diff_type": "style_update | new_element | removed_element | structural_change | role_change",
  "design_source": "layout_analysis.sections.section_header",
  "old_element_id": "旧页面中被影响的元素 ID，删除/修改时填写；新增时为 null",
  "resource_impact": "none | reuse_asset | replace_asset | add_asset | delete_asset | keep_asset",
  "risk": "low"
}
```

`diff_type` 与 `restyle-guardrails.md` 的差异分类矩阵一一对应，每项改动必须标注差异类型：

- `style_update`：旧有新有，视觉属性变了
- `new_element`：旧无新有
- `removed_element`：旧有新无
- `structural_change`：旧有新有，包裹关系变了
- `role_change`：旧有新有，交互性变了

`resource_impact` 描述切图/shape/drawable 资源的连带影响：

- `none`：不涉及资源文件变更
- `reuse_asset`：复用项目已有资源，不新增也不替换文件（内容与设计稿切图一致，结论必须来自 [resource-rules.md §7.6](../rules/resource-rules.md) 的 `--compare-assets` 比对）
- `replace_asset`：保留旧资源名，只替换文件内容（适用于背景切图图案变了等场景）
- `add_asset`：新增切图或 shape 资源文件
- `delete_asset`：删除切图或 shape 资源文件（必须先确认无全局引用）
- `keep_asset`：不改变资源文件，但不再在 layout 中引用（如设 visibility=gone）

`planned_changes` 只收本次改动集内的项。设计稿画了但不属于本次页面的宿主级区域（底部 Tab、全局导航、
状态栏/导航栏沉浸区），以及本次不动的业务逻辑（ViewModel、网络层、埋点、Adapter 数据流），
均**禁止并入 `planned_changes`**，改为在报告「不改动项」一节列出并写明原因。

### `manual_confirmations`

需要用户确认的问题：

```json
{
  "question": "设计稿删除价格字段，是否同步移除价格展示逻辑？",
  "default_action": "保留隐藏控件或保留数据绑定但设置 gone",
  "required": true
}
```

design 画了但要求宿主区变化（`impact=needs_host_change`）时**不得**自行修改，必须列入 `manual_confirmations` 交用户决定后续任务如何拆分。

### `execution`

执行结果对照，以 `planned_changes` 为基准逐项标注：

```json
{
  "planned": "调整按钮背景为黑色圆角",
  "result": "done | deviated | skipped",
  "detail": "偏离或未做时写明原因"
}
```

### `annotation_table`

标注对照表，每个已改区域一行：

```json
{
  "area": "底部按钮",
  "property": "圆角",
  "design_value": "23dp",
  "impl_value": "23dp",
  "status": "match | deviated"
}
```

### `protection_verification`

对 `referenced_ids`、`protected_views` 逐项给出验证结果：

```json
{
  "id": "tv_save",
  "verified": true,
  "note": "ID 保留，点击逻辑未变"
}
```

### `compile`

```json
{
  "command": "./gradlew :app:assembleAutomatic_testDebug",
  "result": "success | failed | not_run",
  "verified_scope": "验证到哪一层；未跑或失败时写明原因与阻塞者"
}
```

## Markdown 报告模板

```md
# Change Impact Report

status: success | warning | blocked
risk_level: low | medium | high | blocked

## 规则加载表

| 规则文件 | 读取 | 命中原因 |
|---------|:---:|---------|

## 决策摘要

从 `planned_changes`、`manual_confirmations`、`compile` 机械派生，禁止改写语义。

- **影响范围**: {planned_changes 去重后的文件数} 个文件（布局/资源/代码）
- **工作树基线**: {vcs}，{dirty_files 数量} 个未提交改动；本次目标文件 {target_hashes 数量} 个、引用资源 {asset_hashes 数量} 个已记 md5
- **计划改动**: {planned_changes 总数} 项
  - 样式更新: {style_update 计数} / 新增元素: {new_element 计数} / 删除元素: {removed_element 计数} / 结构重组: {structural_change 计数} / 角色变更: {role_change 计数}
- **并发改动警告**: {concurrency_warnings 总数} 项
- **需要确认**: {manual_confirmations 总数} 项（其中 {required=true 数量} 项必填）
- **编译风险**: {有/无}
- **风险等级**: {risk_level}

## Baseline

| 项 | 值 |
|----|-----|
| VCS / 采集时间 | {vcs} / {captured_at} |
| 工作树 | {clean / dirty（N 个未提交改动）} |

未提交改动清单（含他人 WIP）与目标/资源 md5 表：见 `change_impact.json` 的 `baseline`
（文件多时不必在 md 里铺开，但 `worktree_dirty` 与数量必须写）。

## Concurrency Warnings

| Path | Detected By | Detail | Action |
|------|-------------|--------|--------|

## Referenced IDs

| ID | Declared In | References | Decision | Notes |
|----|-------------|------------|----------|-------|

## Protected Views

| ID | Reason | Allowed Changes | Forbidden Changes |
|----|--------|-----------------|-------------------|

## Planned Changes

| File | Change | Diff Type | Old Element ID | Resource Impact | Risk |
|------|--------|-----------|----------------|-----------------|------|

## 不改动项

本次不动的宿主级区域与业务逻辑，写明原因。与本表内容禁止并入 Planned Changes。

| 项 | 类型 | 原因 |
|----|------|------|

## Manual Confirmations

| ID | Question | Default Action | Required |
|----|----------|----------------|----------|

## 执行结果对照

以 Planned Changes 为基准逐项标注。

| Planned | Result | Detail |
|---------|--------|--------|

## 标注对照表

| 区域 | 属性 | 设计稿值 | 实现值 | 状态 |
|------|------|---------|--------|------|

## 保护项验证

对 Referenced IDs、Protected Views 逐项给出结果。

| ID | 结果 | 备注 |
|----|------|------|

## 编译验证

| 项 | 值 |
|----|-----|
| 命令 | {实际执行的命令} |
| 结果 | success / failed / not_run |
| verified_scope | {验证到哪一层；未跑或失败时写明原因与阻塞者} |

## warnings / blocked / next

```
