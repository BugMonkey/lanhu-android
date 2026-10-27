# 蓝湖设计稿处理工具

## 版本记录

| 贡献者 | 贡献内容 | 贡献时间 | 版本 |
|--------|---------|---------|------|
| Edison | 从 `nanjing-android-plugin` 独立提取为 `lanhu-android` 单 Skill 仓库，补齐 SkillHub manifest（slug/displayName/version/summary/license），移除插件命名前缀依赖 | 2026-10-27 | 1.0.11 |
| Edison | 截图结构分析、视觉对比、切图语义确认改为派发子 agent 读图，skill 不再主动调用 `nanjing-vision` 视觉脚本：SKILL.md 去掉 vision 脚本 allowed-tools、改写阶段职责与执行流程；`commands/extract.md`、`commands/restore-check.md`、`rules/core-rules.md`（§1/§10）、`rules/extract-rules.md` §13、`schemas/layout-analysis-schema.md`（`viewer` 枚举改 `subagent`）、`lanhu_parser.py` 占位文案同步。识图 hook 保留自动触发，供不能读图的模型兜底 | 2026-10-19 | 1.0.10 |
| Edison | `--json-color-summary` 修复（检测 r/g/b 数值三元组 + alpha 简写 + 放宽探索限制 + encoding_detected 输出字段）；补 allowed-tools(cp/svn/sh gradlew)；change_impact_report 加决策摘要 + 聊天同源输出；新增报告读者矩阵；create_page_report 去重只引 xml_report；restore-check 只列不一致项；差异清单大改分组排版；xml_report 合并为资源落地表；core-rules 加报告防覆盖规则 | 2026-09-17 | 1.0.8 |
| Edison | 按用户实测反馈修复 8 类问题。**视觉脚本定位去内联 glob**（zsh `nomatch` 会让整条命令首跑即失败），统一走 `../nanjing-vision/scripts/vision_path.py`，allowed-tools 补 `git`。**新增 `lanhu_inspect.py --compare-assets`**：按内容 md5 比对切图与项目资源，逐条回显并报「同名图层组混淆风险」；`slices.json` 补 `node_id`/`node_x`/`node_y`/`ancestor_path`；resource-rules 新增 §7.6 资源同一性比对、§7.7 切图↔节点映射只认 `node_id`/`slice.drawable`；`resource_impact` 增 `reuse_asset`。**SKILL.md 读取规则重写为四段**（按任务类型 / 按是否触碰资源布局 / 资源自检表 / 视觉脚本），restyle 明确必须读 resource-rules + layout-rules。**core-rules 新增 §9 编译验证**（命令取宿主 CLAUDE.md/AGENTS.md、flavor 变体定位、报错文件归属判定、kapt/DataBinding 缓存损坏处置、打桩须 md5 逐字节还原）**与 §10 视觉脚本能力边界**（定性通道非数值通道，小图标取色不可作精确值；新增 `--format asset` 图形语义确认通道）。**change-impact-schema 新增 `baseline`/`concurrency_warnings`/`host_scope_findings`**：restyle-page 增 Phase 3.0 工作树基线与并发检查、Phase 6.0 改前重读与 md5 复核（防并行会话改动失效）。`lanhu_query.py` 新增 `--depth N` 递归展开子节点；意图确认提问容量放宽为每轮 4 个并给出必问清单；layout-analysis-schema 明确字段归属（视觉结论字段 vs 主流程字段） | 2026-09-22 | 1.0.9 |
| Edison | 校验脚本改为三值状态（ready/needs_enrichment/blocked）并给出 next_action，识别 extract 骨架不再误报为阻塞；放宽不驱动下游动作的枚举与数组形式约束；明确双报告分工 | 2026-09-16 | 1.0.7 |
| Edison | 截图视觉分析由自定义 subagent 改为 nanjing-vision 视觉脚本（vision_infer.py --format lanhu-layout/compare），模型 ID 由脚本参数指定 | 2026-08-13 | 1.0.6 |
| Edison | 新增 layout_analysis 校验脚本与降级门禁，强化截图分析职责边界；补齐旧页面改造的差异分类、资源影响和背景切图保护规则 | 2026-06-12 | 1.0.5 |
| Edison | 增加截图验收checklist，强化 agent 对看图遵循性；识图agent模型使用qwen3.7plus | 2026-06-10 | 1.0.4 |
| Edison | extract 固化保存 raw.json，并新增原始 JSON 颜色安全查询入口，禁止猜临时路径 | 2026-05-27 | 1.0.3 |
| Edison | lanhu-skill 提示词助手收敛为生成页面、修改已有页面、还原度检查三个功能 | 2026-05-22 | 1.0.2 |
| Edison | 优化 Claude Code Skill 路由提示词，避免被其他蓝湖 Skill 抢占 | 2026-05-22 | 1.0.1 |
| Edison | 从蓝湖设计稿还原ui | 2026-05-22 | 1.0.0 |

## 作者

Edison

## 用途

蓝湖设计稿到 Android 一站式处理工具，支持：
- 从蓝湖 JSON 提取标注、切图资源和布局分析结果
- 生成 Android 页面
- 修改已有页面布局
- 检查设计稿和实现截图的还原度

## 目录结构

```text
lanhu-android/
├── .claude-plugin/plugin.json
├── README.md
├── SKILL.md
├── LICENSE
├── commands/
├── rules/
├── schemas/
├── scripts/
└── 蓝湖辅助脚本.user.js
```

说明：
- `commands/`：子命令说明，包含 `extract`、`xml`、`create-page`、`restyle-page`、`restore-check`
- `rules/`：全局约束和旧页面改造防护规则
- `schemas/`：结构化报告与分析结果的字段约束
- 截图结构分析与视觉对比：由主流程派发子 agent 读图完成，不依赖外部视觉脚本
- `scripts/`：蓝湖提取、摘要、节点查询和 layout_analysis 校验脚本

## 入参

| 参数 | 类型 | 说明 |
|------|------|------|
| json_url | string | 蓝湖 JSON URL（extract 必填） |
| screenshot | string | 设计稿截图 URL 或本地路径 |
| android-project | string | Android 项目根目录路径 |
| output | string | 输出目录（默认 ./lanhu） |
| page | string | 页面名称 |
| target | string | 还原度检查目标 |
| actual-screenshot | string | 实现截图路径（还原度检查推荐） |
| no-download | flag | 跳过切图下载 |
| force-refresh | flag | 忽略同一设计稿的本地提取缓存，强制重新下载 |

## 出参

| 产物 | 说明 |
|------|------|
| annotations.json | 组件树结构 |
| slices.json | 切图清单 |
| raw.json | extract 固化保存的原始设计 JSON |
| source_meta.json | 原始 JSON 来源和落盘信息 |
| layout_analysis.json | 截图结构分析结果（核心产物） |
| assets/ | 切图资源目录 |
| res/layout/*.xml | Android 布局文件 |
| res/drawable/*.xml | Shape/drawable 文件 |
| res/drawable-xxhdpi/*.png | 切图资源文件 |
| xml_report.md | 布局决策报告 |
| restore_check_report.md | 还原度检查报告 |
| restyle_report.md | 改造报告（执行前计划与约束 + 执行结果与证据） |

## 使用示例

### 缓存复用

第二次使用同一 `sketchjson` 时默认会复用本地完整提取产物，不重复下载 JSON 和切图。只有缓存缺少关键产物，或显式增加 `--force-refresh` 时才会重新提取。`extract_dir` 的完整规则以 `core-rules.md` 和 `commands/extract.md` 为准。

### 修改已有页面

```text
/lanhu-android 截图地址:https://alipic.lanhuapp.com/SketchCovere728aedc81af51e6fe17458224f61a49c51096f0513e6f86a67e940b58b71692 sketchjson:https://alipic.lanhuapp.com/SketchJSONURL1113f3832c598f8659c34a0077f8d81e9be4281b1f7363fd5ed8d093a96ce59a 页面:<现有页面名> 任务:修改已有页面
```

### 生成页面

```text
/lanhu-android 截图地址:https://alipic.lanhuapp.com/SketchCovere728aedc81af51e6fe17458224f61a49c51096f0513e6f86a67e940b58b71692 sketchjson:https://alipic.lanhuapp.com/SketchJSONURL1113f3832c598f8659c34a0077f8d81e9be4281b1f7363fd5ed8d093a96ce59a 页面:ReviewDeliveryHistoryFragment 任务:生成页面 需求:自定义需求
```

### 还原度检查

```text
/lanhu-android 截图地址:https://alipic.lanhuapp.com/SketchCovere728aedc81af51e6fe17458224f61a49c51096f0513e6f86a67e940b58b71692 sketchjson:https://alipic.lanhuapp.com/SketchJSONURL1113f3832c598f8659c34a0077f8d81e9be4281b1f7363fd5ed8d093a96ce59a 页面:ReviewDeliveryHistoryFragment 任务:还原度检查 检查目标:卡片的样式 需求:自定义需求
```

### 修改已有页面命令

```text
/lanhu-android restyle-page <extract_dir> --page <页面名>
```

## 路由说明

- 仅在用户显式输入 `技能:lanhu-android`、`/lanhu-android`、`请使用 Skill lanhu-android` 时独占路由到本 Skill
- 蓝湖辅助脚本生成的标准前缀推荐使用：`技能:lanhu-android /lanhu-android ...`
- 本 Skill 从 `nanjing-android-plugin` 中独立提取，可单独安装使用，不依赖原插件

## 子命令

- `extract` — 解析蓝湖 JSON、下载截图和切图，生成结构化产物
- `xml` — 根据提取产物生成 XML、shape 和切图资源
- `create-page` — 在 `xml` 基础上补安全可推断的页面代码骨架
- `restyle-page` — 根据新设计稿改造旧页面并输出影响分析
- `restore-check` — 对比设计稿和实现产物，输出还原度检查报告
