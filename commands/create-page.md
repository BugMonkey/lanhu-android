---
name: lanhu-command-create-page
description: 从蓝湖设计稿创建 Android 新页面，覆盖 XML/资源和必要 Fragment、Activity、Adapter 代码骨架。
---

# create-page 命令

`create-page` 面向“根据设计稿生成 Android 页面、代码”。它以 `xml` 生成布局和资源为基础，只补当前页面能安全推断的代码骨架，不生成业务网络、仓储、复杂状态管理或假数据逻辑。

## 命令格式

```text
/lanhu-android create-page <extract_dir> --page <页面名> [--android-project <path>]
```

## 输入

必需输入：

- `extract_dir`：`extract` 实际生成的提取产物目录。
- `--page`：页面名，如 `DiaryFragment`、`HomeActivity`、`item_coupon`。

`extract_dir` 的完整规则只引用 [../rules/core-rules.md](../rules/core-rules.md) 和 [extract.md](extract.md)。

必需产物：

```text
annotations.json
slices.json
screenshot.png
layout_analysis.json
```

## 输出

至少输出：

```text
<extract_dir>/xml_report.md
<extract_dir>/create_page_report.md
```

落地 Android 项目时，可按项目模式创建：

```text
app/src/main/res/layout/*.xml
app/src/main/res/drawable/*.xml
app/src/main/res/drawable-xxhdpi/*.png
app/src/main/java/**/*.kt
app/src/main/java/**/*.java
```

## 执行阶段

先完成 [core-rules.md §0 6 步执行清单](../rules/core-rules.md#0-执行清单优先全局唯一权威版本)。若 `看截图` 未完成，只允许生成低保真骨架或直接 `blocked`。

create-page 特有补充：
- `搭页面`：需判定页面边界（Fragment/Activity/Item/Dialog）、动态区域承载方式
- `自我检查`：产出 `create_page_report.md` + `xml_report.md`

### Phase 1: 读取设计稿产物

先执行轻量摘要：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>" --compact-for-xml
```

需要局部节点时只用 `lanhu_query.py`。禁止直接读取完整大 JSON 或截图 base64。

### Phase 2: 判定页面边界

结合用户页面名、`layout_analysis.user_intent` 和截图结构确认：

- `Fragment`：默认不包含宿主底部 Tab、全局导航和宿主悬浮入口。
- `Activity`：可包含完整屏幕固定区域。
- `Item`：只生成 item 自身，不包含页面标题、Tab 或父列表。
- `Dialog`：确认遮罩、圆角面板和底部安全区是否属于当前布局。

影响文件拆分或动态承载的歧义，先问用户；低风险假设写入 `create_page_report.md`。

### Phase 3: 生成布局和资源

调用 [xml.md](xml.md) 的规则生成 XML、shape、切图资源和 `xml_report.md`。

动态区域默认策略：

- 重复卡片拆 `item_*.xml`，父页面使用 `RecyclerView`,并使用`tools:listitem=item_*`实现预览。
- 横滑卡片使用 `ViewPager2` 或横向 `RecyclerView`。
- 底部固定按钮放在滚动容器外。
- 保留后续业务承接所需 ID。

### Phase 4: 补代码骨架

只有满足以下条件时才创建或修改 Kotlin/Java 代码：

- 用户要求“页面、代码、Fragment/Activity”或页面名明确是 `Fragment` / `Activity`。
- 能定位 Android 项目路径，或用户提供 `--android-project`。
- 能从现有项目中找到同类页面模式，例如 BaseFragment、ViewBinding/DataBinding、路由注解、Adapter 写法。

代码骨架原则：

- 优先复制项目同类页面结构，只替换类名、布局名和最小初始化。
- Fragment/Activity 只负责 inflate/binding、基础 view 初始化和空的 TODO 承接点。
- 列表页面可生成 Adapter 骨架，但不要发明真实数据结构；用项目已有 adapter 基类时保持同风格。
- 不新增 ViewModel、Repository、网络请求、埋点事件名，除非项目同类页面创建必须依赖，且用户明确要求。
- 不删除或改动无关文件。

### Phase 5: 标注对照

每个卡片/区域生成后，**必须查标注验证关键属性，禁止凭记忆或"看起来差不多"落地**：

1. 用 `lanhu_query.py --node-ids` 回查每个容器节点的：
   - `borderRadius` — 若 `style` 缺失则查 raw JSON 的 `points[].cornerRadius`
   - `backgroundColor` / `borderColor`
   - 父容器内全部子节点 — 确认有无分割线、装饰层（未被读图分析标出的元素）
2. Shape drawable 验证：
   - `rg "@drawable/<name>"` 检查引用范围
   - 多页面共享 → 不一致时新建 shape，不改旧文件
   - 仅当前页面 → 可覆盖
   - 规则详情见 [resource-rules.md](../rules/resource-rules.md) §7.4

### Phase 6: 编译验证

命令来源、flavor 变体处理、失败归属**一律见 [core-rules.md §9 编译验证](../rules/core-rules.md)**，不要照抄固定命令：

1. 先看宿主项目根 `CLAUDE.md` / `AGENTS.md` 声明的构建命令（含 flavor 变体、模块名）。
2. 没有声明时用 `./gradlew :app:assembleDebug`；报 `Task not found` 或项目有 `productFlavors` 时，
   用 `./gradlew tasks --all` 查出真实变体 task，取与当前调试包一致的那个。
3. 报告中记录**实际执行的命令**与选择原因。

无法判断模块或命令确实不可用时记录 `warning`，**不得声称编译通过**。

## create_page_report.md

报告应包含**决策摘要**在先，布局/资源细节只引用 `xml_report.md`，不重复罗列。结构如下：

```text
# 创建页面报告

## 决策摘要
- 页面类型: {Fragment/Activity/Item/Dialog}
- 生成文件: N 个（布局 N、drawable N、代码 N）
- 编译验证: {通过/未通过/未验证（原因）}
- 风险: {有/无}（详见下文）

## 代码骨架边界
- 已生成: {Fragment/Activity/Adapter 骨架 + 布局名 + ID}
- 未生成: {ViewModel/Repository/网络层等，原因}

## 项目代码模式来源
- 参考页面: {项目同类页，如 BaseFragment}
- 绑定方式: {ViewBinding/DataBinding/findViewById}
- Adapter 基类: {有/无}

## 低风险假设
- {假设项; 不影响架构但未逐项确认的视觉细节}

## 缺少项
- {本次未完成的内容，如状态/交互态/空态}

布局/资源/背景还原/切图等明细见 `xml_report.md`。

status: success | warning | blocked
outputs:
  - <create_page_report.md>
  - <xml_report.md>
  - <生成的布局/代码文件路径>
warnings:
  - <warning>
blocked:
  - <blocker>
next:
  - <下一步建议>
```

## 阻塞条件

- 缺 `annotations.json` 或截图。
- 页面类型无法判断且会影响文件名或代码类型。
- 用户要求落地代码，但无法定位 Android 项目路径。
- 找不到任何可参考的项目页面模式，且用户又要求生成非纯 XML 页面代码。

## 禁止行为

> 全局禁止行为见 [core-rules.md](../rules/core-rules.md)，以下仅列出 create-page 特有项。

- 禁止凭空创造业务数据流、网络层、埋点事件或路由参数。
- 禁止把设计稿所有可见区域机械塞进 Fragment。
- 禁止伪造编译或截图验证结果。
