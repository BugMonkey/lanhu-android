---
name: lanhu-command-extract
description: /lanhu-android extract：解析蓝湖 JSON，下载截图/切图，生成 annotations/slices/issues/layout_analysis/extract_report。
---

# extract

## 命令

```text
/lanhu-android extract <json_url_or_file> [--screenshot <url_or_file>] [--output <dir>] [--no-download] [--force-refresh]
```

## 产物

```text
<output>/<design_id>/
  annotations.json
  slices.json
  issues.json
  screenshot.png
  raw.json
  source_meta.json
  layout_analysis.json
  extract_report.md
  assets/
```

### extract_dir 规则

- `extract` 的后续唯一输入目录是 **本次实际生成的 `<extract_dir>`**。
- `design_id` 对 URL 输入可能经过标准化处理，**不保证等于** `sketchjson` URL 的完整末段。
- 后续命令必须复用 parser 实际输出的 `<extract_dir>`，不要从原始 `sketchjson` URL 重新拼目录。
- 如需追溯来源，读取 `<extract_dir>/source_meta.json`，其中保存 `extract_dir`、`design_id` 和 `original_url`。
- 文档中出现的 `<output>/<design_id>/` 只是产物结构占位写法，不代表允许调用方自行推导目录名。

## 流程

先完成 [core-rules.md §0 6 步执行清单](../rules/core-rules.md#0-执行清单优先全局唯一权威版本)。

extract 特有补充：
- `搭页面` 替换为整理 `implementation_context`，传给后续读图子 agent
- `自我检查`：产出 `extract_report.md`

0. 整理实现意图：

从用户原始描述中提炼一份轻量 `implementation_context`，后续传给读图子 agent。不要把示例词固化为规则，重点识别用户真正要求的 Android 结构。

```json
{
  "user_request_summary": "用户原始需求的简短复述",
  "requested_screen_type": "fragment | activity | dialog | item | unknown",
  "core_requirements": ["用户明确要求的区域、交互、取舍"],
  "android_architecture_hints": ["基于 Android 常识的布局边界判断"],
  "open_questions": ["继续前必须确认的问题；没有则为空数组"]
}
```

如果 `open_questions` 中存在会影响页面归属、宿主导航、动态区域拆分或关键 ID 的问题，先向用户确认；无法确认时输出 `blocked`，不要继续生成布局。低风险假设可以继续，但要写入 `layout_analysis.android_layout_assumptions`。

上下文要求：`implementation_context` 保持短小，只包含后续决策需要的结构化结论；不要把完整用户聊天、长篇推理或完整节点列表传给读图子 agent。

1. 从插件固定提示词字段读取截图 URL 和 Sketch JSON URL；字段缺失时输出 `blocked`。
   - 默认先判断本地是否已有同一 `sketchjson` 对应的完整 `<extract_dir>`。
   - 完整产物包含 `annotations.json`、`slices.json`、`layout_analysis.json`；如果本次提供了截图 URL，还应有 `screenshot.png`。
   - 缓存完整时直接复用并进入 inspect / 后续流程，不重复下载 JSON 和切图。
   - 用户明确要求“重新提取/刷新/最新设计稿/强制刷新”时，运行 parser 增加 `--force-refresh`。
2. 运行解析（不确定参数时先查 `--help`）：

```bash
python3 <skill_dir>/scripts/lanhu_parser.py --help
python3 <skill_dir>/scripts/lanhu_parser.py "<json>" -o "<output>" --screenshot "<screenshot>" -v
```

如需跳过切图下载，加 `--no-download`。
如需强制重新下载同一设计稿，加 `--force-refresh`。

解析完成后，**先记录并复用脚本实际输出的 `<extract_dir>`**，再进入 inspect / query / 读图分析 / xml / restore-check。不要继续使用原始 `sketchjson` URL 反推目录名。

3. 检查产物（不确定参数时先查 `--help`）：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py --help
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>"
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>" --compact-for-xml
```

`--compact-for-xml` 是后续 `xml/create-page/restyle-page/restore-check` 的默认交接摘要，避免直接读取完整 `annotations.json`、`slices.json` 或图片文件。

如果后续发现 `annotations.json` 缺少颜色字段，优先检查 `<extract_dir>/raw.json`：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py --json-color-summary "<extract_dir>/raw.json"
```

禁止自己猜测临时下载路径或用 `python3 -c` 读取原始 JSON。

4. 查询节点只用：

```bash
python3 <skill_dir>/scripts/lanhu_query.py --help
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --list-names --sort y --limit 120
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --search "写日记" --search "标题" --sort y --limit 80
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --bg "#FFFFFF" --radius-gt 10 --y-min 300 --y-max 760 --sort y --limit 40
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-id "1493F378"
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-ids "id1,id2,id3" --with-children --compact-output
# 嵌套结构（角标组/Tab 图标组）用 --depth 2~3 一次取到；--with-children 只有 1 层
python3 <skill_dir>/scripts/lanhu_query.py "<extract_dir>" --node-ids "id1,id2,id3" --depth 2 --compact-output
```

禁止 `python -c`、`grep annotations.json`、`| head`、`2>/dev/null`、直接 `Read screenshot.png`。

5. 有 `screenshot.png` 时，分两步完成截图分析和文件写入：

**5a. 派发子 agent 读取截图做结构分析：**

主 Agent 不直接 Read `<extract_dir>/screenshot.png`（base64 会挤占主上下文），改为用 Agent 工具派发子 agent 读图。prompt 固定包含实现意图与需回答的视觉问题，并要求只回传结构化定性结论：

```text
读取 <extract_dir>/screenshot.png，按 Android 开发视角做截图结构分析。
实现意图：<implementation_context 摘要>
只输出一个 JSON 对象（不要输出任何其他文字，不要用 Markdown 代码块包裹），字段如下：
{
  "confidence": "high|medium|low",
  "layout_summary": "一句话页面总览",
  "screen_type": "fragment|activity|dialog|item|header|footer|unknown",
  "screenshot_review": {"viewed": true, "viewer": "subagent",
    "coverage": ["看过的区域"], "evidence": ["至少3条直接可见的视觉观察"],
    "limitations": ["仅凭截图无法确认的项"]},
  "sections": [{"id": "...", "name": "区域名", "role": "header|content|footer|card|list|form|overlay",
    "bounds": {}, "children": [], "implementation": "建议容器", "notes": "区域内顺序与包裹关系"}],
  "fixed_regions": [{"position": "top|bottom|left|right|overlay", "reason": "为何固定/是否宿主"}],
  "scroll_strategy": {"type": "none|NestedScrollView|RecyclerView|ViewPager2", "reason": "依据"},
  "element_classification": [{"visual": "视觉描述",
    "category": "icons|buttons|images|text|container|divider|input|list", "interactive": true}],
  "background_layers": [{"layer": "背景层描述", "source": "slice|shape|color", "notes": "..."}],
  "component_groups": [{"name": "组名", "role": "card|list_item|toolbar|form_group|action_bar",
    "repeatable": true, "children": ["子元素"]}],
  "constraint_hints": ["只写少量定性布局提示，不写精确dp"],
  "implementation_hints": ["工程建议"],
  "risk_flags": [{"code": "...", "severity": "high|medium|low", "message": "...", "blocked": false}]
}
要求：区域划分覆盖全页从上到下；evidence 至少 3 条直接可见的视觉观察；coverage 非空；
只做截图上的定性判断，禁止编造精确坐标/颜色/字号/圆角/间距；不确定的项写入 risk_flags。
不输出图片内容、base64 或逐像素描述。
若你无法读取这张图片，只输出 {"viewed": false, "reason": "无法读取图片"}，不要输出任何视觉结论。
```

**5b. 主流程合并子 agent 结论并写入文件：**

- 取子 agent 回传的定性结论。子 agent 返回 `{"viewed": false, ...}` 时视为读图失败，直接走下方降级逻辑，不得补写任何视觉结论。
- 先读取 parser 已生成的 `<extract_dir>/layout_analysis.json` 作为骨架，保留其中所有必需顶层字段。
- 合并成功后必须删除 parser 占位的 `risk_flags` 项 `missing_visual_review`，并替换占位的 `layout_summary` / `screen_type`；否则 `confidence=high` 会被校验脚本判为冲突。
- 构造最终 JSON 时，只用子 agent 的结论覆盖视觉分析字段；`schema_version`、`design_id`、`source` 以 parser 产物为准。需要追溯来源时读取 `<extract_dir>/source_meta.json`，其中 `original_url` 优先，其次使用 `json_source_path`：

```json
{
  "schema_version": "1.0",
  "design_id": "<extract_dir 的目录名>",
  "source": {
    "json": "<source_meta.original_url 或 source_meta.json_source_path>",
    "screenshot": "<extract_dir>/screenshot.png"
  },
  "...子 agent 回传的视觉分析字段..."
}
```

- 如果子 agent 输出中意外包含 `schema_version`、`design_id`、`source`，主流程必须忽略这些字段，不能覆盖 parser 产物中的真实元数据。
- 如果子 agent 输出缺少非元数据必需字段，使用 parser 骨架中的默认值补齐，但必须把 `confidence` 降为 `low`，并在 `risk_flags` 追加 `{"code":"missing_visual_field","severity":"medium","message":"子 agent 视觉结论缺少部分视觉分析字段，已使用 parser 骨架默认值补齐。","blocked":false}`，随后运行校验脚本决定是否重派、降级或阻塞。
- 使用 Write 工具写入 `<extract_dir>/layout_analysis.json`

读图子 agent 只回传定性结论，不操作文件；文件写入由主流程负责。

6. 运行校验脚本检查 `layout_analysis.json`：

```bash
python3 <skill_dir>/scripts/validate_layout_analysis.py --help
python3 <skill_dir>/scripts/validate_layout_analysis.py "<extract_dir>"
```

校验脚本返回三值 `status`，必须按状态处理，禁止只看"有没有报错"：

| status | 含义 | 动作 |
|--------|------|------|
| `ready` | 产物已具备实现条件 | 继续后续步骤 |
| `needs_enrichment` | 当前仍是 extract 骨架，视觉分析尚未合并 | 回到步骤 5 补 `screenshot_review` 与结构字段；这不是失败，不要当作校验不通过处理 |
| `blocked` | 存在会产生错误布局的硬伤 | 按 `errors` 修复后重跑。根节点不完整、旁路文件存在、截图证据不合格、`confidence=high` 但证据不足、`element_classification` 有背景元素却缺 `background_layers`，都属此类 |

如果脚本因环境问题无法运行，退化为以下手动 checklist（至少满足全部 4 条才能视为截图理解完成）：

- [ ] `screenshot_review` 存在且 `viewed=true`
- [ ] `screenshot_review.evidence` 至少 3 条视觉观察
- [ ] `screenshot_review.coverage` 非空
- [ ] 根节点是完整 JSON 对象，包含 `schema_version`、`design_id`、`source`、`user_intent`、`screenshot_review`

不满足时：

- 只允许保留基础 extract 产物
- `extract_report.md` 必须标记 `status: warning | blocked`
- `layout_analysis.json.confidence` 必须降为 `low`
- `risk_flags` 必须加入 `missing_visual_review`
- 禁止继续声称可做高还原生成、复杂布局拆分或大范围页面改造

## layout_analysis 验收

- `screen_type` 不应是 `unknown`，除非截图无法判断。
- `user_intent` 应反映用户描述；没有描述时也要显式写 `source: "not_provided"`。
- `screenshot_review` 必须存在且满足全局门禁；否则只能视为“结构化标注分析完成”，不能视为“截图理解完成”。
- `android_layout_assumptions` 应记录低风险默认判断；重大歧义应进入 `confirmation_items` 或 `risk_flags`。
- `layout_summary` 不应是兜底文案。
- `sections`、`element_classification`、`component_groups`、`constraint_hints` 至少一类非空。
- 无法生成有效分析：`confidence=low`，在 `risk_flags` 追加 `{"code":"layout_analysis_not_enriched","severity":"high","message":"未生成有效截图级视觉分析，停止实现。","blocked":true}`，`extract_report.md` 标 `blocked`，停止实现。

## blocked

- JSON 无法读取/解析。
- `annotations.json` 缺失或无有效节点。
- 用户要求高还原度但无截图。

## 报告

`extract_report.md` 必含：输入、输出、scale、切图统计、issues 摘要、`status/warnings/blocked/next`。
