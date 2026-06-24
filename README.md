# osu!mania 4K LN1 Difficulty Analyzer

A specialized difficulty analysis system for **osu!mania 4K LN-oriented maps**, designed to evaluate difficulty beyond traditional NPS-based metrics.

Instead of treating density as the primary source of difficulty, this project focuses on two core LN1 skillsets:

* Coordination (locked-hand anchor patterns)
* Awkward Release Timing

The analyzer models physiological finger constraints and timing discomfort zones to estimate the actual execution difficulty of LN-heavy charts.

---

## Why This Project Exists

Most existing difficulty systems primarily reward:

* Density
* Stamina
* Jack speed
* Pattern complexity

However, LN1 charts often derive their difficulty from entirely different sources:

* Single-hand anchors
* Finger independence
* Asymmetric hand control
* Non-chorded release timing
* Short-LN discomfort zones

Two LN1 charts with identical NPS can have vastly different execution difficulty.

This project attempts to quantify those differences.

---

## Features

### Coordination Analysis

Detects situations where one finger is forced to hold an LN while another finger on the same hand performs additional actions.

Examples:

* Index anchor + outer finger notes
* Outer finger anchor + index finger notes
* Continuous same-hand LN manipulation

The model assigns different weights depending on the anatomical difficulty of the anchor configuration.

---

### Awkward Release Analysis

Measures release timing discomfort using an OD-dependent Gaussian model.

The algorithm identifies release timings that fall near the border between:

* Chunkable releases
* Independent releases

These timing offsets often produce significant consistency issues for players despite appearing visually simple.

---

### Short LN Discomfort Model

Short LNs are neither fully tap-like nor fully hold-like.

The analyzer applies additional penalties to LN lengths that fall inside known awkward execution ranges.

---

### OD-Aware Evaluation

Judgement windows are dynamically derived from map OD.

Higher OD values result in:

* Smaller release tolerance windows
* Increased timing precision requirements
* Higher release-related strain

---

### RMS Difficulty Fusion

Difficulty dimensions are normalized independently and combined using RMS aggregation instead of linear averaging.

This prevents a single metric from completely dominating the final rating.

---

## Difficulty Model

### Coordination Difficulty

When a note is pressed while another column on the same hand is currently held:

\[D_{coord}=\sumW(c_h,c_p)\cdot\sqrt{\frac{1000}{\Delta t_{press}}}\]

Where:

* \(c_h\) = holding column
* \(c_p\) = pressed column
* \(W\) = coordination weight
* \(\Delta t_{press}\) = interval since previous same-hand press

The square-root scaling prevents coordination values from exploding at extremely small intervals.

---

### Release Difficulty

Hit windows are calculated dynamically:

\[W_{300}=64-3OD\]

\[W_{200}=97-3OD\]

The awkward release region is modeled using a Gaussian function:

\[P(\Delta t)=e^{-\frac{(\Delta t-\mu)^2}{2\sigma^2}}\]

Where:

\[\mu=W_{300}+15\]

\[\sigma=\frac{W_{200}-W_{300}}{2}\]

---

### Short LN Penalty

For LN lengths between 40ms and 250ms:

\[M_{short}=1+Ke^{-\frac{(L-L_{peak})^2}{2\cdot25^2}}\]

Where:

\[L_{peak}=\max(80,W_{300}+70)\]

---

### Star Scaling

Raw metrics are transformed using logarithmic compression:

\[S(x)=x ^ {0.67}\]

Resulting in:

\[D_{coord}^{*}\]

\[D_{rel}^{*}\]

\[D_{speed}^{*}\]

This places all dimensions into a comparable star-scale space.

---

### Final Rating

The final LN1 rating is computed using RMS fusion:

\[D_{total}=\sqrt{0.35(D_{coord}^{*})^2+0.40(D_{rel}^{*})^2+0.25(D_{speed}^{*})^2}\]

Weight distribution:

| Component    | Weight |
| ------------ | ------ |
| Coordination | 40%    |
| Release      | 35%    |
| Speed        | 25%    |

The model intentionally prioritizes release control and coordination over raw density.

---

## Example Results

### MWC 2024 Qualifiers — sasakure.UK - Decadence

```text
Artist - Title: sasakure.UK - Decadence feat. mami
Difficulty: Stage 4: Terminus

Coordination Factor: 27.771
Release Factor:      18.420
Speed Factor:         9.320

Overall LN1 Difficulty: 21.189

Coordination Lock Ratio: 43.2%
Awkward Release Ratio:   41.1%
```

---

### MWC 2025 Grand Finals — yuikonnu x sana - Fuzzy Future

```text
Artist - Title: yuikonnu x sana - Fuzzy Future
Difficulty: Toward Radiance

Coordination Factor: 28.982
Release Factor:      19.651
Speed Factor:        10.287

Overall LN1 Difficulty: 22.307

Coordination Lock Ratio: 43.0%
Awkward Release Ratio:   41.9%
```

The results indicate that both charts place similar demands on:

* Same-hand coordination
* Release execution
* LN manipulation

with Toward Radiance showing slightly higher overall strain.

---

## Usage

```bash
python osu_mania_4k_ln_analyzer.py
```

Or import directly:

```python
from osu_mania_4k_ln_analyzer import ManiaBeatmap, LN1Analyzer

bm = ManiaBeatmap("map.osu")

analyzer = LN1Analyzer(bm)

result = analyzer.analyze()

print(result)
```

---

## Current Limitations

* 4K only
* Designed specifically for LN1-oriented charts
* Does not model reading difficulty
* Does not model pattern memorization
* Does not model stamina decay
* Not calibrated against large-scale player score datasets

This project is intended as an experimental LN difficulty research framework rather than a replacement for osu! official star rating.

---

## Future Work

* LN tech support
* Pattern clustering
* Strain graph visualization
* Community calibration datasets
* Machine-learned parameter fitting

---

## AI Usage Disclosure

This project was developed with assistance from AI-based tools, including ChatGPT.

AI was used for:

* Code review
* Refactoring suggestions
* Mathematical model discussion
* Documentation drafting

Final implementation, testing, parameter tuning, and project direction were determined by the author.

## License

MIT License

Copyright (c) 2026
