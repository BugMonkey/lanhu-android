# lanhu-android

把蓝湖设计稿落成 Android 代码的 Skill。它先提取蓝湖 JSON、截图、切图和标注，再生成页面、改造已有页面或做还原度检查。

当前重点优化 Sketch 来源的设计稿；Figma 来源暂未做专项优化。

## 1. 它怎么工作

核心就一句：**先提取，再处理**。

```text
蓝湖选中画板
  → 油猴面板填写页面名/任务/检查目标
  → 复制标准提示词
  → 粘贴到 Claude Code 或其他 Agent 宿主
      → extract：解析 sketchjson，下载截图和切图，生成标注
      → 生成页面 / 修改已有页面 / 还原度检查
```

这样 AI 的判断来自蓝湖标注和真实切图，而不是只靠自然语言描述或截图猜测。

## 2. 使用前准备

1. **安装油猴（Tampermonkey）**：浏览器扩展商店搜索「篡改猴」，或访问 [tampermonkey.net](https://www.tampermonkey.net/index.php?browser=chrome)。
2. **安装提示词脚本**：把仓库里的 [蓝湖辅助脚本.user.js](蓝湖辅助脚本.user.js) 安装到油猴，装完刷新或重启浏览器。
3. **在项目根目录启动 Agent**：Agent 需要在目标 Android 项目根目录运行，extract 产物才会落到项目的 `lanhu/` 下。
4. **本机依赖**：需要 `python3`；还原度检查建议安装 `adb`，否则只能用静态核对。
5. **避免冲突**：执行时暂时禁用其他 Lanhu/蓝湖相关的 Skill 或 MCP，只保留本 Skill。
6. **显式触发**：本 Skill 配置了 `disable-model-invocation`，不会自动路由。必须通过油猴生成提示词，或手动输入 `/lanhu-android ...`。

## 3. 5 分钟上手

### 3.1 在蓝湖打开提示词面板

打开蓝湖设计稿页面，右下角会出现「lanhu-skill提示词助手」面板（页面加载即注入）。选中画板后，脚本会自动填入截图地址和 sketchjson；如果为空，刷新页面再试。

### 3.2 选择任务并填写字段

面板有三个入口：

| 任务 | 需要填写 |
|------|---------|
| 生成页面 | 页面名、自定义需求（可选） |
| 修改已有页面 | 现有页面名或页面文件、自定义需求（可选） |
| 还原度检查 | 页面名、检查目标；实现截图路径或附件（可选，缺省走 ADB） |

### 3.3 复制提示词并执行

点击复制，把提示词原样粘贴到 Claude Code 或其他支持 Skill 的 Agent 宿主。生成的提示词形如：

```text
/lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:<任务类型>
```

还原度检查会额外带上 `检查目标:<检查目标>`，以及可选的 `实现截图:<路径或URL>`。

几个实际注意点：

- 提示词前缀由 [蓝湖辅助脚本.user.js](蓝湖辅助脚本.user.js) 第 13 行的 `COMMAND_PREFIX` 决定，当前是 `/lanhu-android`。如果你改了 Skill 名称，这里也要同步改。
- 脚本默认会在提示词末尾追加「请先与我讨论需求，确认后再开始编码」。想直接开跑，删掉脚本第 124 行即可。
- 脚本里的任务文案是「生成页面 / 修改已有页面 / 还原度检查」；Skill 也识别「生成新页面 / 修改现有页面」这两种说法。
- 面板里粘贴的截图只是占位符（`实现截图:粘贴的截图附件`）。复制提示词后，必须在 Claude Code 同一条消息里再次附上该截图，否则按未提供处理，走 ADB 或静态核对。

### 3.4 先检查 extract 产物

首次使用建议先拿一个结构简单的页面验证。执行后项目根目录会出现：

```text
lanhu/
└── SketchJSONURL.../
    ├── annotations.json      # 组件树与标注（dp/sp）
    ├── slices.json           # 切图清单与尺寸
    ├── raw.json              # 原始设计 JSON
    ├── source_meta.json      # 来源与落盘信息
    ├── screenshot.png        # 设计稿截图
    ├── layout_analysis.json  # 截图结构分析，核心中间产物
    ├── issues.json           # extract 阻塞记录
    ├── extract_report.md     # extract 自检报告
    ├── assets/               # 下载的切图
    │   ├── backgrounds/
    │   ├── buttons/
    │   ├── icons/
    │   └── images/
    ├── xml_report.md         # 生成/改造布局时
    ├── create_page_report.md # 生成页面时
    ├── restyle_report.md     # 修改已有页面时
    ├── restore_check_report.md # 还原度检查时
    └── actual_screenshot.png # 还原度检查可选
```

报告按任务生成，不是每次全部出现。

如果 extract 阶段的文件没有出现，不要继续生成布局。`extract_report.md` 缺失视为 extract 未完成，先按 `issues.json` 修复后重跑。

## 4. 三种任务怎么用

### 4.1 生成页面

**适用**：从 0 创建 Fragment、Activity、Dialog、列表 item 或普通布局页面。

**必填**：截图地址、`sketchjson`、页面名、任务=生成页面。

**可选**：`页面文件` 指向已有页面时，以它为入口做结构比对。

**执行后**：生成布局 XML、shape/切图资源，以及当前页面能安全推断的 Fragment/Activity/Adapter 骨架。

**边界**：不生成网络、仓储、复杂状态或假数据逻辑；骨架只补安全可推断的部分。

### 4.2 修改已有页面

**适用**：已有页面按新设计稿改版。

**必填**：截图地址、`sketchjson`、现有页面名或页面文件、任务=修改已有页面。

**执行后**：先做结构比对、引用扫描和影响分析，再受控改造；输出 `restyle_report.md`，包含执行前计划和执行后证据。

**边界**：必须保留原有 ID、绑定、点击、埋点和业务逻辑；高风险改动先出计划等确认。

### 4.3 还原度检查

**适用**：页面完成后的自检，检查圆角、字体、颜色、间距、切图、点击区域是否与设计稿一致。

**必填**：截图地址、`sketchjson`、页面名、任务=还原度检查、检查目标。

**执行后**：输出 `restore_check_report.md`，只给差异和修复建议，不直接改文件。

**实现截图**：可以手动提供路径或附件；不提供时，Skill 会检测设备并引导 ADB 截图。拿不到截图时降级为静态标注核对，结果标 `warning`。注意：面板粘贴附件只生成占位符，执行时必须在同一条消息里再次附上截图。

## 5. 提示词字段从哪来

| 字段 | 来源 | 说明 |
|------|------|------|
| `截图地址` | 油猴自动读取 | 当前画板的蓝湖截图 URL |
| `sketchjson` | 油猴自动读取 | 当前画板的 Sketch/Figma JSON URL |
| `页面` | 面板填写 | 如 `HomeFragment`、`item_coupon` |
| `任务` | 面板选择 | 生成页面 / 修改已有页面 / 还原度检查 |
| `检查目标` | 面板填写 | 整页、卡片、标题栏、列表 item 等 |
| `实现截图` | 面板填写或附件 | 面板附件只生成占位，需在同条消息再次附图；缺省时走 ADB 引导 |
| `页面文件` | 面板填写（可选） | 已有页面绝对路径，作为改造入口 |
| `需求` | 面板填写（可选） | 范围取舍和特殊要求 |

## 6. 产物怎么看

| 产物 | 用途 |
|------|------|
| `annotations.json` | 核对尺寸、坐标、字号、颜色 |
| `slices.json` | 核对切图是否齐全、命名是否语义化 |
| `layout_analysis.json` | 看页面分区、层级、背景和待确认项 |
| `xml_report.md` | 看布局和资源落地决策（生成/改造时） |
| `create_page_report.md` | 看生成页面的骨架和安全推断（生成页面时） |
| `restyle_report.md` | 看改造计划、差异分类和执行证据（修改页面时） |
| `restore_check_report.md` | 看还原度差异和修复建议（检查时） |
| `extract_report.md` | 看 extract 自检结果 |
| `static_check.md` | 还原度检查无法获取实现截图时的静态核对结果 |
| `actual_screenshot.png` | 还原度检查获取到的实现截图 |
| `issues.json` | 看 extract 阶段的阻塞项 |

报告按任务生成，不是每次全部出现。`extract_report.md` 缺失视为 extract 未完成，先按 [commands/extract.md](commands/extract.md) 和 `issues.json` 修复后重跑。

`validate_layout_analysis.py` 返回的 `status` 只有三种含义：

- `ready`：产物已具备实现条件，可以继续。
- `needs_enrichment`：还是 extract 骨架，需要读图子 agent 补全视觉字段。
- `blocked`：按 `errors` 修完再继续，禁止跳过。

各报告自身的 `status` 另有一套取值：`success | warning | blocked`，不要和校验状态混用。

## 7. 为什么不用 Lanhu MCP

| 维度 | Lanhu MCP | 本 Skill |
|------|-----------|----------|
| 输入 | 需要开发人员描述大量页面细节 | 固定为截图 URL、`json`、页面名、任务，油猴生成 |
| 样式还原 | 复杂页面圆角、字体、颜色、间距容易跑偏 | 优先读蓝湖 JSON 标注 |
| 切图 | 下载失败时容易降级成 vector/shape 自绘 | 先下载 `slices.json` 和 `assets/`，有 slice 就用切图 |
| 复杂层级 | 反复解析同一批标注，耗时长、占上下文 | 先落盘结构化产物，后续用脚本查询 |
| 旧页面改造 | 容易只关注视觉，忽略绑定和业务 | 有独立的改造防护规则 |
| 验收复查 | 问题定位依赖人工回忆 | 每阶段输出报告 |

## 8. 使用建议

- 先从低风险、结构简单的页面开始，例如「我的」页面、小弹窗、简单列表 item。
- 首版生成后，两三轮内就进入手动修改，不要一直让 AI 反复重跑。
- 可以多开几个 Agent 窗口，并行试不同页面或局部模块，挑质量好的结果。
- 建议使用带视觉能力的模型，截图结构分析和还原度对比都依赖读图；并先从简单页面验证。
- 复杂页面拆成局部模块验证，不要一开始就整页交给 AI。
- AI 生成界面不是每次都稳定。把它当「帮忙」的工具：先完成布局、资源整理和基础样式，再结合标注和运行截图细调。

## 9. 常见问题

| 现象 | 处理 |
|------|------|
| 粘贴提示词后没有触发 Skill | 确认前缀是 `/lanhu-android`，或直接在提示词里写 `技能:lanhu-android` |
| 提示词前缀不对 | 改 [蓝湖辅助脚本.user.js](蓝湖辅助脚本.user.js) 的 `COMMAND_PREFIX` |
| 执行被其他蓝湖 Skill 抢走 | 暂时禁用其他 Lanhu/蓝湖 Skill 和 MCP |
| 切图缺失 | 检查 `slices.json` 和 `assets/`；未经用户确认禁止用 vector/shape 自绘替代，按 [rules/resource-rules.md](rules/resource-rules.md) §7.5 三选一处置 |
| 没有 `annotations.json` | 不要脑补尺寸、坐标、字号，先重新 extract |
| validate 返回 `needs_enrichment` | 正常，继续让读图子 agent 补全视觉字段 |
| validate 返回 `blocked` | 按 `errors` 逐项修复后重跑，不要跳过 |
| ADB 连不上或截图失败 | 手动提供实现截图；无法提供时降级静态核对并标 `warning` |
| 生成结果跑偏 | 缩小到局部模块，或两三轮后转手动修改 |

## 10. 安装

```bash
skillhub install lanhu-android --namespace user_140863df
# 或指定宿主 skills 目录
skillhub install lanhu-android --namespace user_140863df --dir <宿主 skills 目录>
```

`skillhub install` 默认装到当前目录的 `./skills`。建议用 `--dir` 指向宿主的 skills 目录，否则 Agent 可能发现不到。提示词脚本在 `蓝湖辅助脚本.user.js`。

## 11. 目录结构

```text
lanhu-android/
├── .claude-plugin/plugin.json    # Skill manifest
├── LICENSE.md
├── README.md
├── SKILL.md                      # 路由、流程与约束
├── 蓝湖辅助脚本.user.js          # 蓝湖网页提示词生成脚本
├── commands/                     # extract / xml / create-page / restyle-page / restore-check
├── rules/                        # core / resource / layout / extract / global / restyle-guardrails
├── schemas/                      # layout_analysis 与 change_impact 结构
└── scripts/                      # parser / inspect / query / validate_layout_analysis
```

## 12. 版本记录

| 版本 | 日期 | 内容 |
|------|------|------|
| 1.0.13 | 2026-10-27 | README 按使用流程重写；补齐前置条件、附件截图、状态语义和安装位置；统一任务词汇与报告路径 |
| 1.0.12 | 2026-10-27 | 发布就绪：`LICENSE` 改为 `LICENSE.md`，`.gitignore` 迁至 `.git/info/exclude`，仓库可直接发布 |
| 1.0.11 | 2026-10-27 | 从 `nanjing-android-plugin` 独立提取为 `lanhu-android` 单 Skill 仓库 |
| 1.0.10 | 2026-10-19 | 截图结构分析、视觉对比和切图语义确认改为派发子 agent 读图 |
| 1.0.0–1.0.9 | 2026-05-22–2026-09-22 | 建立三任务路由；extract 固化 `raw.json`；三值校验状态；切图 md5 比对；编译验证；旧页面改造防护 |

`.git/info/exclude` 只在本机生效。发布前确认 `lanhu/`、`__pycache__/` 等产物没有被一起打包。

## 13. 参考

- 完整流程与约束：[SKILL.md](SKILL.md)
- 任务说明：[commands/](commands/)
- 核心规则：[rules/core-rules.md](rules/core-rules.md)
- 结构约束：[schemas/layout-analysis-schema.md](schemas/layout-analysis-schema.md)、[schemas/change-impact-schema.md](schemas/change-impact-schema.md)
- 许可：[LICENSE.md](LICENSE.md)

作者：Edison
