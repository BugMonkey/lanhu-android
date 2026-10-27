---
name: lanhu-resource-rules
description: 蓝湖 skill 切图与资源规则，包含切图命名、尺寸、Shape Drawable 验证和缺失切图处置。生成新页面或改造已有页面时必须加载。
---

# 切图与资源规则

这些规则在本次任务**会新增或修改** `android:` 属性、`@drawable` 引用、`<shape>` / `<vector>`、切图文件、`colors` / `styles` 时加载。restore-check 只在涉及切图核对时按需参考 §7.4。

> 切图优先原则声明在 [core-rules.md](core-rules.md) §7。

## 切图命名

### 7.1 切图语义化命名

任何场景使用蓝湖切图时，**禁止直接使用，必须先重命名** 。

格式：`{ic|bg|img}_{功能}_{含义}.png`（`ic` 图标 / `bg` 背景 / `img` 插画）

示例：`btn_btn_mask` → `bg_btn_search.png`、`img_402b79` → `ic_scan_qr.png`

## 切图尺寸

### 7.2 切图尺寸规则

- **优先使用 `slices.json` 的 `width_dp/height_dp` 字段**（脚本已自动计算 dp 尺寸）。
- 若 `width_dp/height_dp` 缺失，则从 `actual_size`（如 "120x80"）计算：像素 ÷ density (xxhdpi=3) = dp。
- 有 slice 的节点，必须从 `slices.json` 或切图文件实际尺寸计算 ImageView 的 `layout_width` 和 `layout_height`。
- 禁止直接使用 `annotations.json` 中的 `ddsOriginFrame` 作为 ImageView 尺寸（除非无切图）。

## Shape Drawable 验证

### 7.4 Shape Drawable / 背景资源验证

**所有 `@drawable/shape_*`、`@drawable/bg_*` 及 `android:background` 引用必须对照新设计稿的 `borderRadius` 重新验证，禁止假设旧值与新设计稿一致。**

验证流程（生成/改造页面均适用）：

1. 通过 `lanhu_query.py --node-ids` 查询该容器节点
2. 若节点 `style.borderRadius` 不存在，则查原始 JSON 的 `points[].cornerRadius`
3. 对照当前引用的 shape drawable 的 `<corners>` 值

处置策略：

| 情况 | 操作 |
|------|------|
| 新旧值一致 | 直接复用，不改任何文件 |
| 新旧值不一致 + 仅当前页面引用 | 覆盖旧 shape 文件 |
| 新旧值不一致 + 被多个布局引用 | 新建 shape，保留旧文件 |
| 新增 shape 时 | 遵循项目现有命名惯例（`shape_round_white_N`、`shape_rect_white`），放 `lib_common/src/main/res/drawable/` |

禁止：不查标注就复用旧 shape（即使"看起来差不多"）；修改被多页面引用的 shared drawable（会破坏其他页面）。

## 缺失切图处置

### 7.5 缺失切图处置

设计稿中存在视觉上应为图片/图标/Logo 等位图资源（`slices.json` 匹配到、或 `element_classification.has_slice=true`、或 `layout_analysis.background_layers.source=slice`），但切片下载失败或 `slices.json` 对应条目缺失时：

**一律阻断，禁止自动脑补。禁止生成 `<vector>` 替代。禁止生成 `<shape>` 替代。禁止写定任意 `android:src`。禁止用任意颜色填充后假装有图。**

阻断后必须向用户说明：

```text
blocked: 缺少 [切图名称/位置] 切图
原因: slices.json 中未匹配到 / 切图下载失败
用户需选择:
  1. 提供切图文件路径或重新下载
  2. 使用纯色 shape 占位（需用户确认颜色和形状）
  3. 先不写 android:src / android:background，标注 TODO 待补充切图
```

用户回复后，按选择执行：选 2 时用 `<shape>`（非 `<vector>`），只写用户确认的颜色和矩形圆角；选 3 时 ImageView 不写 `src`，在 `xml_report.md` 标注缺失项。**未回复前不得继续操作该资源。**

## 资源同一性比对

### 7.6 资源同一性比对（避免重复导入、漏用现有资源）

生成或改造页面前，必须对 `slices.json` 的每张切图做一次**内容同一性比对**，判断项目里是否已存在字节完全相同的资源：

```bash
python3 <skill_dir>/scripts/lanhu_inspect.py "<extract_dir>" --compare-assets "<项目 res 目录>"
```

例如 `--compare-assets app/src/main/res`。

规则：

- **结论只能来自该脚本的输出**。禁止用手写 md5 循环、布尔聚合（如"全部一致 ✓"）或目测替代。
  聚合式结论一旦算错不会自曝；必须逐条回显 md5（N 张切图 → N 行），结论才可被核对。
- **判定以内容 md5 为准，不以文件名为准**。设计稿同名图层会得到 `_2`/`_3` 去重后缀，项目侧命名也可能与设计稿完全不同；**禁止用"文件名不同"推断"视觉不同"**。
- 脚本判定为**内容一致**的切图，其 `planned_changes.resource_impact` 必须填 `reuse_asset`（复用项目现有资源），**禁止** `add_asset` 重复导入同一份内容。
- 内容一致但**项目侧资源名与设计稿不同**时，引用前必须确认该资源在项目中的用途与当前节点一致。内容相同不等于语义相同——同一张图的字节可能同时对应不同位置的语义，直接引用可能把 A 槽位的图用到 B 槽位。
- 判定为 **同名不同内容** 时，禁止按名字直接复用。
- 脚本报出「同名图层组混淆风险」时，该组切图的归属只能按 `node_id` / 坐标判定（见 §7.7）。

本步结论必须进入 `restyle_report` 的 `planned_changes.resource_impact` 与报告的标注对照表。

### 7.7 切图与节点的映射只认 `slice.drawable` / `node_id`

`annotations.json` 节点上的 `slice.drawable` 与 `slices.json` 的 `node_id` 是**切图 ↔ 节点对应关系的唯一依据**。

禁止：

- **按图层名相似度匹配**。设计稿不同位置的图层可能同名（如两个 Tab 的图标组都叫 `icon_tab2_nor`），parser 为避免冲突会加 `_2`/`_3` 去重后缀——按名字匹配**可能取反**，且取反后不会报错。
- 按切图顺序、`slices.json` 数组下标或坐标排序猜测归属。
- 用 `source_layer` 判断归属——它只是图层名原文（不含去重后缀），同名时完全无法区分。

`slices.json` 的 `node_x` / `node_y`（dp 绝对坐标）用于交叉校验：同名图层组内，用节点坐标区分各自所属的槽位。`ancestor_path` 供人工核对归属。

`restore-check` 中，对同一画板内的同名图层组必须逐张比对 `slice.drawable` 与实际引用是否一致，报出「同名图层切图映射颠倒」。

#### 同名 drawable_name 取图步骤

`slices.json` 中同一 `drawable_name` 出现多条时：

1. 逐条核对 `node_id` + `download_url`：URL 不同即为不同切图，parser 按 `_<node_id 前 8 位>` 后缀独立落盘。
2. 每条记录取图只用自己的 `local_path`，禁止把多条记录映射到同一文件。
3. 引用改名后的文件时按 §7.1 重新命名，不带 node_id 后缀进项目。
4. 落盘前校验 `local_path` 无重复：
   `rg -o '"local_path": "[^"]+"' <extract_dir>/slices.json | sort | uniq -d`
