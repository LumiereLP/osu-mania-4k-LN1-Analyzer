# osu!mania 4K LN1 Difficulty Analyzer

A specialized difficulty analysis system for **osu!mania 4K LN Coordination**, designed to evaluate chart difficulty beyond traditional NPS (Notes Per Second) metrics.

Instead of treating density as the primary source of difficulty, this project utilizes a **Strain Decay System** to locate local bursts, modeling and calculating the actual execution difficulty of LN charts based on practical play experience.

---

## Why This Project Exists

Most existing difficulty systems primarily evaluate the following capabilities:

* Density
* Stamina
* Pattern complexity

However, the difficulty of LN1 charts often stems from entirely different factors:

* Coordination difficulty caused by fingerlock anchors and varied movements
* Release difficulty introduced by independent hand releases and short LNs

Two LN1 charts with the exact same NPS can have a massive divergence in actual execution difficulty. This analyzer quantifies these differences by analyzing local sections of the map and computing a decayed sum.

---

## Difficulty Model & Core Mechanics

The algorithm divides the beatmap into **400ms sections**. Within each section, it independently calculates three types of raw strain:

* Coordination Strain
* Release Strain
* Speed Strain

### 1. Standardization and Dimensional Unification

Before merging these metrics, the system maps the raw scores across different dimensions to a similar magnitude using heuristic constants and a non-linear compression function ($p=0.75$).

**Coordination Strain:**
$$Strain_{coord} = (Raw_{coord} \times 0.2)^{0.75} \times OD_{phys}$$

**Release Strain:**
$$Strain_{rel} = (Raw_{rel} \times 0.4)^{0.75} \times OD_{tech}$$

**Speed Strain:**
$$Strain_{speed} = (Raw_{speed} \times 0.4)^{0.75} \times OD_{phys}$$

### 2. Differentiated OD Multipliers

OD (Overall Difficulty) not only affects the strictness of timing windows, but also influences how players approach the map.

Taking $OD = 6.0$ as the baseline, release timing (i.e., tail judgment) is affected the most, using the following technical multiplier:
$$OD_{tech} = 1.0 + 0.20 \cdot \max(0, OD - 6.0)^{1.2}$$

Meanwhile, aspects like coordination and speed are relatively less affected, using the following physical multiplier:
$$OD_{phys} = 1.0 + 0.10 \cdot \max(0, OD - 6.0)^{1.2}$$

### 3. Local Synergy Fusion (Combined Sectional Strain)

Within each 400ms section, the analyzer calculates a combined local strain value.

$$Strain_{local} = \sqrt{0.45 \cdot (Strain_{coord})^2 + 0.40 \cdot (Strain_{rel})^2 + 0.15 \cdot (Strain_{speed})^2}$$

### 4. Peak Strain Decay

The analyzer uses a decayed weighted sum to prevent underestimating maps with long break periods.

$$Rating = \sum_{i=0}^{N} (0.95)^i \cdot Strain_{i}$$

This mechanic shares a similar philosophy with osu!'s official SR (Star Rating) model.

---

## Sub-Skill Analysis Details

### Coordination Difficulty

This detects scenarios where a finger is forced to hold an LN while another finger on the same hand must perform additional actions (challenging fingerlock and same-hand independence).

**Key Features & Core Updates:**

* **Anatomical Weights:** Weights are dynamically adjusted based on physiological finger anatomy. For example, performing a tap with the ring finger while the index finger is fingerlocked is typically more difficult than other combinations.
* **Proximity Amplification:** The difficulty is exponentially or power-law amplified when the time interval ($\Delta t$) between actions on the same hand is small.
* **Millisecond Batching:** To completely resolve parallel timing conflicts caused by note-by-note sequential updates, the algorithm processes event updates in millisecond-level batches:
  1. *Time Aggregation:* Group all events occurring at the exact same millisecond into a single batch for unified processing.
  2. *Prioritize Releases:* Within the current millisecond, remove all released columns from the active holding-state pool first.
  3. *History-Based Press Evaluation:* When calculating press events within that millisecond, notes are evaluated for coordination based solely on the holding state carried over from the previous millisecond. This ensures that simultaneous double-taps or perfectly aligned LN heads do not falsely trigger fingerlock detection against each other.



### Awkward Release Analysis

Evaluates the discomfort of release timing using an OD-dependent Gaussian model. The algorithm identifies releases that fall into the mental "gray zone" between the following two scenarios:

* Chunkable Release (releases that can be handled simultaneously as chords)
* Independent Release (completely independent releases)

$$P(\Delta t) = e^{-\frac{(\Delta t-\mu)^2}{2\sigma^2}}$$

### Short LN Penalty

Short LNs with lengths between **40ms and 250ms** receive an additional penalty.

The reason is that LNs of this length can neither be treated purely as standard rice notes, nor do they align cleanly with longer LNs, causing a mismatch in release timing that leads to judgment and accuracy loss.

---

## Usage

```bash
python osu_mania_4k_ln_analyzer_CN.py

```

Or import directly:

```python
from osu_mania_4k_ln_analyzer_CN import ManiaBeatmap, LN1Analyzer

bm = ManiaBeatmap("map.osu")
analyzer = LN1Analyzer(bm)
result = analyzer.analyze()

print(result)

```

---

## Current Limitations

* 4K only.
* Designed specifically for LN1-oriented charts.
* For LN Mix charts, LN Jacks will cause inflated difficulty values.
* Not yet fully calibrated against global leaderboard data.

This project is positioned as an experimental LN difficulty research framework for recreational and research purposes; actual ingame feel and play experience shall prevail.

---

## AI Usage Statement

This project was developed with the assistance of artificial intelligence tools (including ChatGPT).

AI was utilized in the following areas:

* Code review
* Refactoring suggestions
* Mathematical model discussion
* Documentation drafting

The final implementation, testing, parameter tuning, and the overall direction of the project were entirely determined by the author.

---

## License

MIT License

Copyright (c) 2026