import math
import os
import re


class HitObject:
    def __init__(self, col, start_time, end_time=None):
        self.col = col  # Column (0, 1, 2, 3)
        self.start_time = start_time
        self.end_time = end_time  # Release time (ms), None for Rice Notes
        self.is_ln = end_time is not None

    @property
    def length(self):
        if self.is_ln:
            return self.end_time - self.start_time
        return 0


class ManiaBeatmap:
    """parse and save .osu file metadata and hit objects for 4K Mania."""
    def __init__(self, filepath):
        self.filepath = filepath
        self.title = ""
        self.artist = ""
        self.version = ""
        self.creator = ""
        self.od = 8.0  # Default Overall Difficulty
        self.columns = 4  # 4K only
        self.hit_objects = []
        self.parse_file()

    def parse_file(self):
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"Map not found: {self.filepath}")

        current_section = ""
        with open(self.filepath, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue

                # Match section headers like
                match_section = re.match(r'^\[(\w+)\]$', line)
                if match_section:
                    current_section = match_section.group(1)
                    continue

                # parse metadata
                if current_section == "Metadata":
                    if line.startswith("Title:"):
                        self.title = line.split("Title:", 1)[1].strip()
                    elif line.startswith("Artist:"):
                        self.artist = line.split("Artist:", 1)[1].strip()
                    elif line.startswith("Version:"):
                        self.version = line.split("Version:", 1)[1].strip()
                    elif line.startswith("Creator:"):
                        self.creator = line.split("Creator:", 1)[1].strip()

                # Parse difficulty settings
                elif current_section == "Difficulty":
                    if line.startswith("OverallDifficulty:"):
                        self.od = float(line.split("OverallDifficulty:", 1)[1].strip())
                    elif line.startswith("CircleSize:"):
                        self.columns = int(line.split("CircleSize:", 1)[1].strip())

                # Parse HitObjects
                elif current_section == "HitObjects":
                    parts = line.split(",")
                    if len(parts) >= 5:
                        x = int(parts[0])
                        # 4K columns: set to 0, 1, 2, 3 based on x position (0-512)
                        col = min(self.columns - 1, max(0, int(x / (512 / self.columns))))
                        start_time = int(parts[2])
                        obj_type = int(parts[3])

                        # Check if it's a Long Note (bit 7 is set, i.e., type & 128)
                        if obj_type & 128:
                            # The last item is additional parameters separated by colons, the first element is the end time
                            extra_parts = parts[5].split(":")
                            end_time = int(extra_parts[0])
                            self.hit_objects.append(HitObject(col, start_time, end_time))
                        else:
                            # Rice
                            self.hit_objects.append(HitObject(col, start_time))


class LN1Analyzer:
    """LN1 difficulty evaluation algorithm implementation."""
    def __init__(self, beatmap):
        self.beatmap = beatmap
        if beatmap.columns != 4:
            raise ValueError("This algorithm is only optimized for 4K mode!")
            
        # 1. Dynamic OD Hit Window Mapping
        self.od = beatmap.od
        self.w_300 = 64.0 - 3.0 * self.od
        self.w_200 = 97.0 - 3.0 * self.od
        
        # Dynamic awkward release window definition (Gaussian curve parameters)
        self.mu_rel = self.w_300 + 15.0  # Peak of the awkward window
        self.sigma_rel = max(5.0, (self.w_200 - self.w_300) / 2.0)  # Span of the awkward window
        
        # Global high OD precision multiplier
        self.m_precision = 1.0 + 0.5 * max(0.0, self.od - 7.0) ** 1.5

        # Short LN awkward interval parameters
        self.l_peak = max(80.0, self.w_300 + 70.0)
        self.k_short = 0.5  # Maximum penalty multiplier

    def analyze(self):
        objects = sorted(self.beatmap.hit_objects, key=lambda x: x.start_time)
        if not objects:
            return {}

        total_notes = len(objects)
        ln_notes = [obj for obj in objects if obj.is_ln]
        total_ln = len(ln_notes)
        ln_ratio = total_ln / total_notes if total_notes > 0 else 0

        # Get Drain Time (in seconds) for NPS calculation
        duration = (objects[-1].start_time - objects[0].start_time) / 1000.0
        nps = total_notes / duration if duration > 0 else 0

        # Finger assignment definition (common 4K layout)
        # 0: Left hand outer (middle/ring) finger, 1: Left hand index finger | 2: Right hand index finger, 3: Right hand outer (middle/ring) finger
        col_to_hand = {0: 'L', 1: 'L', 2: 'R', 3: 'R'}
        col_to_finger_type = {0: 'outer', 1: 'index', 2: 'index', 3: 'outer'}

        # Event stream conversion (for tracking real-time finger states)
        events = []
        for obj in objects:
            events.append({'time': obj.start_time, 'type': 'press', 'col': obj.col, 'obj': obj})
            if obj.is_ln:
                events.append({'time': obj.end_time, 'type': 'release', 'col': obj.col, 'obj': obj})
        
        # Sort events by time, with Release events before Press events if times are the same
        events.sort(key=lambda x: (x['time'], 0 if x['type'] == 'release' else 1))

        # State tracker
        holding_columns = set()
        last_press_time_on_hand = {'L': None, 'R': None}
        all_actions_on_hand = {'L': [], 'R': []}  # Storage (time, type) for each hand for coordination and release calculations

        # collect all actions per hand for later analysis
        for ev in events:
            hand = col_to_hand[ev['col']]
            all_actions_on_hand[hand].append(ev)

        coord_score_total = 0.0
        rel_score_total = 0.0
        awkward_releases_count = 0  # Count of releases falling in awkward release windows
        coordination_situations_count = 0  # Count of coordination situations (single-handed locked presses)

        # Start iterating through events to calculate coordination and release difficulty
        for ev in events:
            time = ev['time']
            col = ev['col']
            hand = col_to_hand[col]
            f_type = col_to_finger_type[col]

            if ev['type'] == 'press':
                # --- Coordination Difficulty ---
                # Check if the other column of the same hand is currently being held down
                other_col = (col + 1) if col % 2 == 0 else (col - 1)
                
                if other_col in holding_columns:
                    coordination_situations_count += 1
                    other_f_type = col_to_finger_type[other_col]
                    
                    # Determine the coordination difficulty weight based on finger types
                    if other_f_type == 'index' and f_type == 'outer':
                        # holding the index finger while pressing with the outer finger (hard)
                        lock_weight = 1.5
                    elif other_f_type == 'outer' and f_type == 'index':
                        # holding the outer finger while pressing with the index finger (moderate)
                        lock_weight = 1.0
                    else:
                        lock_weight = 1.0

                    # partial coordination difficulty based on the time since the last press on the same hand
                    last_hand_press = last_press_time_on_hand[hand]
                    if last_hand_press is not None:
                        dt_press = max(10, time - last_hand_press)
                        # exponential decay factor for speed: faster presses yield higher difficulty
                        speed_factor = (1000.0 / dt_press) ** 0.5
                    else:
                        speed_factor = 1.0

                    coord_score_total += lock_weight * speed_factor

                holding_columns.add(col)
                last_press_time_on_hand[hand] = time

            elif ev['type'] == 'release':
                if col in holding_columns:
                    holding_columns.remove(col)

                # --- Release Difficulty Calculation ---
                # 1. Find the minimum time difference delta_t with other actions on the same hand
                hand_actions = all_actions_on_hand[hand]
                min_dt = float('inf')
                for other_ev in hand_actions:
                    # Exclude the current release event itself
                    if other_ev is ev:
                        continue
                    dt = abs(time - other_ev['time'])
                    if dt < min_dt:
                        min_dt = dt

                # 2. Dynamic release penalty calculation (Gaussian distribution)
                p_val = 0.0
                if min_dt != float('inf') and min_dt > 0:
                    p_val = math.exp(-((min_dt - self.mu_rel) ** 2) / (2 * (self.sigma_rel ** 2)))
                    # Record whether the player was forced to release within the 200/100 judgment window
                    if self.w_300 < min_dt <= self.w_200:
                        awkward_releases_count += 1

                # 3. Short LN sticky hand penalty calculation
                m_short_val = 1.0
                obj = ev['obj']
                if obj.is_ln:
                    ln_len = obj.length
                    # only apply the short LN penalty for lengths between 40ms and 250ms
                    if 40 <= ln_len <= 250:
                        m_short_val = 1.0 + self.k_short * math.exp(-((ln_len - self.l_peak) ** 2) / (2 * (25.0 ** 2)))

                rel_score_total += p_val * m_short_val

        # normalization factor to scale the scores to a 0-100 range
        norm_factor = 100.0 / max(100, total_notes)

        raw_coord = (coord_score_total * norm_factor) * self.m_precision
        raw_rel = (rel_score_total * norm_factor) * self.m_precision
        raw_speed = nps * 0.4

        # logarithmic scaling to convert raw scores into star ratings
        coord_star = 5.0 * math.log1p(raw_coord)
        rel_star = 5.0 * math.log1p(raw_rel)
        speed_star = 5.0 * math.log1p(raw_speed)

        # RMS fusion of the three star ratings to produce a final LN1 difficulty rating
        final_rating = (
            0.40 * coord_star ** 2 +
            0.35 * rel_star ** 2 +
            0.25 * speed_star ** 2
        ) ** 0.5

        final_coord = coord_star
        final_rel = rel_star
        final_speed = speed_star

        # ratios for awkward release and coordination lock situations
        awkward_ratio = awkward_releases_count / total_ln if total_ln > 0 else 0
        coord_ratio = coordination_situations_count / total_notes if total_notes > 0 else 0

        return {
            "metadata": {
                "title": self.beatmap.title,
                "artist": self.beatmap.artist,
                "version": self.beatmap.version,
                "creator": self.beatmap.creator,
                "od": self.od,
                "total_notes": total_notes,
                "ln_ratio": f"{ln_ratio:.1%}",
                "nps": f"{nps:.2f}"
            },
            "metrics": {
                "coordination_rating": round(final_coord, 3),
                "release_rating": round(final_rel, 3),
                "speed_factor": round(final_speed, 3),
                "total_ln_rating": round(final_rating, 3)
            },
            "ratios": {
                "awkward_release_ratio": f"{awkward_ratio:.1%}",
                "coordination_lock_ratio": f"{coord_ratio:.1%}"
            }
        }


# ==========================================
# Auto test and report generation for a sample .osu file
# ==========================================
if __name__ == "__main__":
    # Detect the uploaded file
    target_file = "yuikonnu x sana - Fuzzy Future (Hylotl) [Toward Radiance].osu"
    
    if os.path.exists(target_file):
        print(f"Reading and parsing: {target_file} ...\n")
        try:
            bm = ManiaBeatmap(target_file)
            analyzer = LN1Analyzer(bm)
            result = analyzer.analyze()
            
            # Formatting and printing the results
            print("=" * 50)
            print(f" Artist - Title: {result['metadata']['artist']} - {result['metadata']['title']}")
            print(f" Beatmap Difficulty: [{result['metadata']['version']}]")
            print(f" Creator: {result['metadata']['creator']}")
            print(f" OD: {result['metadata']['od']}")
            print(f" Total Notes: {result['metadata']['total_notes']} (LN Ratio: {result['metadata']['ln_ratio']})")
            print(f" Average Density (NPS): {result['metadata']['nps']} note/s")
            print("-" * 50)
            print(f" Coordination Factor: {result['metrics']['coordination_rating']}")
            print(f" Release Factor:      {result['metrics']['release_rating']}")
            print(f" Speed Factor:  {result['metrics']['speed_factor']}")
            print(f" Overall LN1 Difficulty:        {result['metrics']['total_ln_rating']}")
            print("-" * 50)
            print(f" Coordination Lock Ratio:     {result['ratios']['coordination_lock_ratio']}")
            print(f" Awkward Release Ratio:  {result['ratios']['awkward_release_ratio']}")
            print("=" * 50)
            
        except Exception as e:
            print(f"Analysis failed with error: {e}")
    else:
        print(f"Sample file not found in the current working directory: '{target_file}'. Please ensure the filename and path are correct.")