# osu!mania 4K LN1 难度分析器

一个专门面向 **osu!mania 4K LN Coordination** 的难度分析系统，旨在评估传统基于 NPS（Notes Per Second）指标之外的谱面难度。

本项目不再将谱面密度视为难度的主要来源，而是采用 **压力衰减（Strain Decay）** 来定位局部爆发，并结合实际游玩经验对 LN 谱面的实际游玩难度进行建模与计算。

---

## 项目背景

现有大多数难度系统主要考察以下能力：

* 密度
* 耐力
* 排列复杂度

然而，LN1 谱面的难度往往来源于完全不同的因素：

* 锁手锚键和不同动作带来的协调（Coordination）难度
* 单手不同时放手和短 LN 带来的放手（Release）难度

两张拥有完全相同 NPS 的 LN1 谱面，其实际难度可能存在巨大差异。本分析器通过分析谱面的局部片段并进行衰减求和来量化这些差异。

---

## 难度模型与核心机制

算法将谱面划分为 **400ms 的时间区段（Section）**。

在每个区段内，分别计算以下三种原始压力值（Raw Strain）：

* 协调压力（Coordination）
* 放手压力（Release）
* 速度压力（Speed）

### 1. 统一数量级

在合并各项指标之前，系统首先利用经验常数和非线性压缩函数（$p=0.75$）将不同维度的原始分数映射到相近数量级。

**协调压力：**

$$
Strain_{coord}=(Raw_{coord}\times0.2)^{0.75}\times OD_{phys}
$$

**放手压力：**

$$
Strain_{rel}=(Raw_{rel}\times0.4)^{0.75}\times OD_{tech}
$$

**速度压力：**

$$
Strain_{speed}=(Raw_{speed}\times0.4)^{0.75}\times OD_{phys}
$$

### 2. OD 乘数

OD（Overall Difficulty）不仅会影响抓判难度，还会对玩家的游玩方式产生影响。

以 $OD = 6.0$ 作为基准，放手（即尾判）受影响最大，使用$$OD_{tech}=1.0+0.20\cdot\max(0,OD-6.0)^{1.2}$$作为乘数，而协调、速度等方面受影响相对更小，使用$$OD_{phys}=1.0+0.10\cdot\max(0,OD-6.0)^{1.2}$$作为乘数。

### 3. 计算切片内综合压力

在每个 400ms 区段内，分析器会计算切片内的综合压力值。

$$
Strain_{local}
=\sqrt{0.45\cdot(Strain_{coord})^2+0.40\cdot(Strain_{rel})^2+0.15\cdot(Strain_{speed})^2}
$$

### 4. 压力衰减

分析器将使用衰减的权重求和以防止休息段导致的数值偏低。$$
Rating=\sum_{i=0}^{N}(0.95)^i\cdot Strain_i$$

这一机制与 osu! 官方 SR 模型的思想相似。

---

## 各维度技术细节

### 协调（Coordination）难度

当同一只手中的某根手指被迫持续按住 LN 时，另一根手指仍需执行额外操作（锁手/同手独立性挑战）。

特点与核心更新：

* 根据手指生理结构动态调整权重。例如，当食指被锁定时使用无名指进行操作，通常比其他组合更加困难。
* 当同手动作之间的时间间隔（$\Delta t$）较小时，难度会被指数级/幂函数放大。
* 为了彻底解决逐个音符更新导致的并行时序冲突，算法按照毫秒对事件批处理更新：
  1. 按时间聚合：将所有处于同一毫秒的事件打包进同一个 Batch 内统一处理。
  2. 优先处理放手：在当前毫秒内，首先将所有放手轨移出按压状态池。
  3. 基于历史判定按压：在计算该毫秒内的所有按压事件时，音符仅根据上一毫秒遗留的状态进行协调性判定。同时落下的双押或完全对齐的 LN 面头不会互相误触发锁手判定。

---

### 不同时放手（Awkward Release）分析

利用基于 OD 的高斯模型评估放手时机的不适感。

算法会识别那些位于以下两种情况之间的放手：

* 可同时处理的面尾（Chunkable Release）
* 完全独立的面尾（Independent Release）

$$
P(\Delta t)=
e^{-\frac{(\Delta t-\mu)^2}{2\sigma^2}}
$$

---

### 短 LN 系数（Short LN Penalty）

长度在 **40ms ～ 250ms** 之间的短 LN 会受到额外惩罚。

原因在于这种长度的 LN 既不能当作单点处理，又恰好与其他较长的 LN 形成了放手时机的差别，会导致判定的损失。

---

## 使用方法

```bash
python osu_mania_4k_ln_analyzer_CN.py
```

或者直接作为模块导入：

```python
from osu_mania_4k_ln_analyzer_CN import ManiaBeatmap, LN1Analyzer

bm = ManiaBeatmap("map.osu")
analyzer = LN1Analyzer(bm)
result = analyzer.analyze()

print(result)
```

---

## 当前限制

* 仅支持 4K 模式。
* 专门针对 LN1 导向谱面设计。
* 对于 LN Mix，LN Jack 会造成数据偏高。
* 尚未针对全球排行榜数据完成全面校准。

本项目定位为一个实验性的 LN 难度研究框架，仅供娱乐，一切以实际游玩情况为准。

---

## AI 使用声明

本项目是在人工智能工具（包括 ChatGPT）的协助下开发的。

AI 在以下方面得到了应用：

* 代码审查 (Code review)
* 重构建议 (Refactoring suggestions)
* 数学模型讨论 (Mathematical model discussion)
* 文档草拟 (Documentation drafting)

最终的实现、测试、参数调优以及项目的整体方向，均由作者本人决定。

---

## 许可证

MIT License

Copyright (c) 2026
