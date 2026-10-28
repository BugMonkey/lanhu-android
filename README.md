# lanhu-android

蓝湖设计稿转 Android 代码。先提取蓝湖 JSON、截图、切图和标注，再生成页面、改造已有页面或做还原度检查。

> 当前重点优化 Sketch 来源的设计稿；Figma 来源暂未做专项优化。

## 快速开始

1. **安装油猴脚本**：浏览器安装 Tampermonkey，再把 [lanhu-helper.user.js](lanhu-helper.user.js) 装进去，装完刷新浏览器。
2. **在蓝湖生成提示词**：打开设计稿，选中画板，右下角会出现「lanhu-skill提示词助手」。选任务，填页面名或检查目标，复制提示词。
3. **交给 Agent 执行**：粘贴到 Claude Code 或其他 Agent。Skill 会先 extract，再按任务生成、改造或检查。

提示词模板：

```text
/lanhu-android 截图地址:<截图URL> sketchjson:<SKETCH_JSON_URL> 页面:<页面名> 任务:<任务类型>
```

## 安装

Claude Code 的个人 Skill 目录是 `~/.claude/skills/<name>/SKILL.md`；项目级用 `<android-project>/.claude/skills/<name>/`。下面以个人目录为例，其他 Agent 宿主把路径换成自己的 skills 目录。

### 方式一：GitHub clone（推荐）

```bash
mkdir -p ~/.claude/skills
git clone git@github.com:BugMonkey/lanhu-android.git ~/.claude/skills/lanhu-android
```

仓库公开后也可以走 HTTPS：

```bash
git clone https://github.com/BugMonkey/lanhu-android.git ~/.claude/skills/lanhu-android
```

### 方式二：从本地目录复制

macOS / Linux：

```bash
mkdir -p ~/.claude/skills/lanhu-android
rsync -a --exclude .git --exclude __pycache__ \
  /path/to/lanhu-android/ ~/.claude/skills/lanhu-android/
```

Windows PowerShell：

```powershell
robocopy "C:\path\to\lanhu-android" "$HOME\.claude\skills\lanhu-android" /E /XD .git __pycache__
```

### 方式三：GitHub ZIP

GitHub 仓库页 → Code → Download ZIP，解压到 `~/.claude/skills/lanhu-android`，确认 `SKILL.md` 直接在目录下。

### 方式四：SkillHub（可选）

```bash
tmp=$(mktemp -d)
skillhub install lanhu-android --namespace user_140863df --dir "$tmp"
mkdir -p ~/.claude/skills/lanhu-android
cp -R "$tmp/@user_140863df/lanhu-android/." ~/.claude/skills/lanhu-android/
rm -rf "$tmp"
```

`skillhub install` 会下载到 `@user_140863df/lanhu-android` 命名空间目录，所以要复制到平铺目录。`skillhub list` 不会显示 `--dir` 安装，以实际目录为准。

### 验证

```bash
grep -m1 '^version:' ~/.claude/skills/lanhu-android/SKILL.md   # 1.0.14
ls ~/.claude/skills/lanhu-android/lanhu-helper.user.js
```

在 Claude Code 中执行 `/reload-skills` 或重启。提示词脚本在 `lanhu-helper.user.js`。

## 三种任务

### 生成页面

- 从 0 创建 Fragment、Activity、Dialog、列表 item 或普通布局。
- 产出 XML、shape/切图资源，以及当前页面能安全推断的页面骨架。
- 不生成网络、仓储、复杂状态或假数据逻辑。

### 修改已有页面

- 按新设计稿调整已有页面 UI。
- 先做结构比对、引用扫描和影响分析，保留 ID、绑定、点击、埋点和业务逻辑。
- 高风险改动先出计划等确认。

### 还原度检查

- 对比设计稿标注和实现截图，输出差异与修复建议，不直接改文件。
- 实现截图可手动提供，也可检测设备后走 ADB 截图。
- 拿不到实现截图时降级为静态核对，结果标 `warning`。

## 提示词字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `截图地址` | 是 | 蓝湖设计稿截图 URL |
| `sketchjson` | 是 | 蓝湖导出的 Sketch/Figma JSON URL |
| `页面` | 是 | 页面名，如 `HomeFragment`、`item_coupon` |
| `任务` | 是 | 生成页面 / 修改已有页面 / 还原度检查 |
| `检查目标` | 检查时必填 | 整页、卡片、标题栏、列表 item 等 |
| `实现截图` | 否 | 实现截图路径或 URL；缺省时走 ADB 引导 |
| `页面文件` | 否 | 已有页面绝对路径，作为改造入口 |
| `需求` | 否 | 范围取舍和特殊要求 |

几个实际注意点：

- 提示词前缀由 [lanhu-helper.user.js](lanhu-helper.user.js) 第 13 行的 `COMMAND_PREFIX` 决定，当前是 `/lanhu-android`。
- 脚本默认在提示词末尾追加「请先与我讨论需求，确认后再开始编码」。想直接开跑，删掉脚本第 124 行。
- 脚本里的任务文案是「生成页面 / 修改已有页面 / 还原度检查」；Skill 也识别「生成新页面 / 修改现有页面」。
- 面板里粘贴的截图只是占位符（`实现截图:粘贴的截图附件`）。复制提示词后，必须在同一条消息里再次附上截图，否则按未提供处理。

## 产物

执行后项目根目录会出现：

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
    ├── xml_report.md         # 生成/改造布局时
    ├── create_page_report.md # 生成页面时
    ├── restyle_report.md     # 修改已有页面时
    ├── restore_check_report.md # 还原度检查时
    └── actual_screenshot.png # 还原度检查可选
```

报告按任务生成，不是每次全部出现。`extract_report.md` 缺失视为 extract 未完成，先按 `issues.json` 修复后重跑。

`validate_layout_analysis.py` 返回的 `status` 只有三种含义：

- `ready`：产物已具备实现条件，可以继续。
- `needs_enrichment`：还是 extract 骨架，需要读图子 agent 补全视觉字段。
- `blocked`：按 `errors` 修完再继续，禁止跳过。

各报告自身的 `status` 另有一套取值：`success | warning | blocked`，不要和校验状态混用。

## 执行流程

核心就一句：**先提取，再处理**。

```text
蓝湖选中画板
  → 油猴填写页面名/任务/检查目标
  → 复制提示词
  → Agent 执行
      → extract：解析 sketchjson，下载截图和切图，生成标注
      → 生成页面 / 修改已有页面 / 还原度检查
```

这样 AI 的判断来自蓝湖标注和真实切图，而不是只靠自然语言描述或截图猜测。

## 相比 Lanhu MCP

| 维度 | Lanhu MCP | 本 Skill |
|------|-----------|----------|
| 输入 | 需要描述大量页面细节 | 固定截图 URL、`json`、页面名、任务，油猴生成 |
| 样式还原 | 复杂页面圆角、字体、颜色、间距容易跑偏 | 优先读蓝湖 JSON 标注 |
| 切图 | 下载失败时容易降级成 vector/shape 自绘 | 先下载 `slices.json` 和 `assets/`，有 slice 就用切图 |
| 复杂层级 | 反复解析同一批标注，耗时长、占上下文 | 先落盘结构化产物，后续用脚本查询 |

## 使用建议

- 先从低风险、结构简单的页面开始，例如「我的」页面、小弹窗、简单列表 item。
- 首版生成后，两三轮内就进入手动修改，不要一直让 AI 反复重跑。
- 可以多开几个 Agent 窗口，并行试不同页面或局部模块，挑质量好的结果。
- 建议使用带视觉能力的模型，截图结构分析和还原度对比都依赖读图。
- 复杂页面拆成局部模块验证，不要一开始就整页交给 AI。

## 常见问题

| 现象 | 处理 |
|------|------|
| 粘贴提示词后没有触发 Skill | 确认前缀是 `/lanhu-android`，或直接写 `技能:lanhu-android` |
| 提示词前缀不对 | 改 [lanhu-helper.user.js](lanhu-helper.user.js) 的 `COMMAND_PREFIX` |
| 执行被其他蓝湖 Skill 抢走 | 暂时禁用其他 Lanhu/蓝湖 Skill 和 MCP |
| 切图缺失 | 检查 `slices.json` 和 `assets/`；未经确认禁止用 vector/shape 自绘替代，按 [rules/resource-rules.md](rules/resource-rules.md) §7.5 处理 |
| 没有 `annotations.json` | 不要脑补尺寸、坐标、字号，先重新 extract |
| validate 返回 `needs_enrichment` | 正常，继续让读图子 agent 补全视觉字段 |
| validate 返回 `blocked` | 按 `errors` 逐项修复后重跑 |
| ADB 连不上或截图失败 | 手动提供实现截图；无法提供时降级静态核对并标 `warning` |
| 生成结果跑偏 | 缩小到局部模块，或两三轮后转手动修改 |

## 边界

- 有蓝湖 JSON URL 时先 extract，产物齐全后再动 Android 代码。
- 未查看截图，禁止生成或改造布局；读图一律派发子 agent。
- 缺 `annotations.json` 时禁止脑补尺寸、坐标、字号。
- `blocked` 时停止高风险步骤并向用户确认。
- 修改已有页面必须保留业务逻辑、ID、绑定、点击和埋点。
- 切图必须语义化重命名；改动 shape、背景和 drawable 前先核对引用范围。
- 中间产物落盘，对话只输出摘要、阻塞项和待用户决策的问题。

## 目录结构

```text
lanhu-android/
├── .claude-plugin/plugin.json    # Skill manifest
├── LICENSE.md
├── README.md
├── SKILL.md                      # 路由、流程与约束
├── lanhu-helper.user.js          # 蓝湖网页提示词生成脚本
├── commands/                     # extract / xml / create-page / restyle-page / restore-check
├── rules/                        # core / resource / layout / extract / global / restyle-guardrails
├── schemas/                      # layout_analysis 与 change_impact 结构
└── scripts/                      # parser / inspect / query / validate_layout_analysis
```

## 版本记录

| 版本 | 日期 | 内容 |
|------|------|------|
| 1.0.14 | 2026-10-28 | 油猴脚本文件名改为 ASCII，修复 ZIP 安装在 macOS 下的乱码；README 增加 GitHub clone / 本地复制 / ZIP / SkillHub 四种安装方式 |
| 1.0.13 | 2026-10-28 | 独立仓库整理：重置版本记录，重写使用说明；保留蓝湖提取与三任务流程 |

## 维护

- 发布前同步更新 `SKILL.md`、`.claude-plugin/plugin.json` 和本文件版本记录。
- 改动后跑 `skillhub publish . --dry-run`，通过再发布。
- `.git/info/exclude` 只在本机生效；发布前确认 `lanhu/`、`__pycache__/` 等产物没有被一起打包。
