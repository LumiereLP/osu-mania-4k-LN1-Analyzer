import math
import os
import re
import collections
from tkinter import filedialog
from tkinter import Tk
import sys

class HitObject:

    def __init__(self, col, start_time, end_time=None):
        self.col = col
        self.start_time = start_time
        self.end_time = end_time
        self.is_ln = end_time is not None

    @property
    def length(self):
        if self.is_ln:
            return self.end_time - self.start_time
        return 0


class ManiaBeatmap:
    """Parse and store the core metadata and object information of an .osu beatmap"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.title = ""
        self.artist = ""
        self.version = ""
        self.creator = ""
        self.od = 8.0
        self.columns = 4
        self.hit_objects = []
        self.parse_file()

    def parse_file(self):
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"File not found: {self.filepath}")

        current_section = ""
        with open(self.filepath, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue

                match_section = re.match(r'^\[(\w+)\]$', line)
                if match_section:
                    current_section = match_section.group(1)
                    continue

                if current_section == "Metadata":
                    if line.startswith("Title:"):
                        self.title = line.split("Title:", 1)[1].strip()
                    elif line.startswith("Artist:"):
                        self.artist = line.split("Artist:", 1)[1].strip()
                    elif line.startswith("Version:"):
                        self.version = line.split("Version:", 1)[1].strip()
                    elif line.startswith("Creator:"):
                        self.creator = line.split("Creator:", 1)[1].strip()

                elif current_section == "Difficulty":
                    if line.startswith("OverallDifficulty:"):
                        self.od = float(line.split("OverallDifficulty:", 1)[1].strip())
                    elif line.startswith("CircleSize:"):
                        self.columns = int(line.split("CircleSize:", 1)[1].strip())

                elif current_section == "HitObjects":
                    parts = line.split(",")
                    if len(parts) >= 5:
                        x = int(parts[0])
                        col = min(self.columns - 1, max(0, int(x / (512 / self.columns))))
                        start_time = int(parts[2])
                        obj_type = int(parts[3])

                        if obj_type & 128:
                            extra_parts = parts[5].split(":")
                            end_time = int(extra_parts[0])
                            self.hit_objects.append(HitObject(col, start_time, end_time))
                        else:
                            self.hit_objects.append(HitObject(col, start_time))


class LN1Analyzer:
    """A difficulty algorithm for LN1 based on local slices and strain decay"""
    def __init__(self, beatmap):
        self.beatmap = beatmap
        if beatmap.columns != 4:
            raise ValueError("The current algorithm is optimized for 4K mode only!")
            
        self.od = beatmap.od
        self.w_300 = 64.0 - 3.0 * self.od
        self.w_200 = 97.0 - 3.0 * self.od
        
        # Gaussian distribution parameters for release intervals
        self.mu_rel = self.w_300 + 15.0
        self.sigma_rel = max(5.0, (self.w_200 - self.w_300) / 2.0)
        
        # Gaussian distribution parameters for short LN objects
        self.l_peak = max(80.0, self.w_300 + 70.0)
        self.k_short = 0.5 

        # OD multiplier adjustments
        self.od_phys_mult = 1.0 + 0.10 * max(0.0, self.od - 6.0) ** 1.2
        self.od_tech_mult = 1.0 + 0.20 * max(0.0, self.od - 6.0) ** 1.2

        # Section parameters
        self.section_length = 400.0 
        self.decay_base = 0.95        # Decay base

    def _calculate_decayed_strain(self, strains):
        """Core decay algorithm: Sort all section strains and sum them with decay factors"""
        if not strains:
            return 0.0
        sorted_strains = sorted(strains, reverse=True)
        total = 0.0
        for i, val in enumerate(sorted_strains):
            total += 0.5 * val * (self.decay_base ** i)
        return total

    def analyze(self):
        objects = sorted(self.beatmap.hit_objects, key=lambda x: x.start_time)
        if not objects:
            return {}

        total_notes = len(objects)
        ln_notes = [obj for obj in objects if obj.is_ln]
        total_ln = len(ln_notes)
        ln_ratio = total_ln / total_notes if total_notes > 0 else 0

        duration = (objects[-1].start_time - objects[0].start_time) / 1000.0
        nps = total_notes / duration if duration > 0 else 0

        col_to_hand = {0: 'L', 1: 'L', 2: 'R', 3: 'R'}
        col_to_finger_type = {0: 'outer', 1: 'index', 2: 'index', 3: 'outer'}

        events = []
        for obj in objects:
            events.append({'time': obj.start_time, 'type': 'press', 'col': obj.col, 'obj': obj})
            if obj.is_ln:
                events.append({'time': obj.end_time, 'type': 'release', 'col': obj.col, 'obj': obj})
        
        events.sort(key=lambda x: (x['time'], 0 if x['type'] == 'release' else 1))

        holding_columns = set()
        last_press_time_on_hand = {'L': None, 'R': None}
        all_actions_on_hand = {'L': [], 'R': []} 

        for ev in events:
            hand = col_to_hand[ev['col']]
            all_actions_on_hand[hand].append(ev)

        # Statistics for awkward releases and coordination situations
        awkward_releases_count = 0 
        coordination_situations_count = 0 

        # Use defaultdict to collect raw difficulty values by section index
        section_data = collections.defaultdict(lambda: {'coord': 0.0, 'rel': 0.0, 'speed': 0.0})

        events_by_time = collections.defaultdict(list)
        for ev in events:
            events_by_time[ev['time']].append(ev)

        sorted_times = sorted(events_by_time.keys())

        for t in sorted_times:
            batch = events_by_time[t]
            sec_idx = int(t / self.section_length)

            # Divide releases and presses
            releases = [ev for ev in batch if ev['type'] == 'release']
            presses = [ev for ev in batch if ev['type'] == 'press']

            # 1. Process release in priority
            # remove column from holding_columns
            for ev in releases:
                col = ev['col']
                hand = col_to_hand[col]
                
                if col in holding_columns:
                    holding_columns.remove(col)

                # --- Calculate release difficulty ---
                hand_actions = all_actions_on_hand[hand]
                min_dt = float('inf')
                for other_ev in hand_actions:
                    if other_ev is ev:
                        continue
                    dt = abs(t - other_ev['time'])
                    if dt < min_dt:
                        min_dt = dt

                p_val = 0.0
                if min_dt != float('inf') and min_dt > 0:
                    p_val = math.exp(-((min_dt - self.mu_rel) ** 2) / (2 * (self.sigma_rel ** 2)))
                    if self.w_300 < min_dt <= self.w_200:
                        awkward_releases_count += 1

                m_short_val = 1.0
                obj = ev['obj']
                if obj.is_ln:
                    ln_len = obj.length
                    if 40 <= ln_len <= 250:
                        m_short_val = 1.0 + self.k_short * math.exp(-((ln_len - self.l_peak) ** 2) / (2 * (25.0 ** 2)))

                section_data[sec_idx]['rel'] += p_val * m_short_val

            # 2. Calculate Press (Before completing the press for the entire Batch, never write new pressed keys to holding_columns)
            new_holds = []
            for ev in presses:
                col = ev['col']
                hand = col_to_hand[col]
                f_type = col_to_finger_type[col]
                
                # --- Speed ---
                section_data[sec_idx]['speed'] += 1.0

                # --- Calculate coordination difficulty ---
                other_col = (col + 1) if col % 2 == 0 else (col - 1)
                
                # Core judgment: Only check if the other column on the same hand was in a Hold state before this millisecond
                if other_col in holding_columns:
                    coordination_situations_count += 1
                    other_f_type = col_to_finger_type[other_col]
                    
                    if other_f_type == 'index' and f_type == 'outer':
                        lock_weight = 1.5
                    elif other_f_type == 'outer' and f_type == 'index':
                        lock_weight = 1.0
                    else:
                        lock_weight = 1.0

                    last_hand_press = last_press_time_on_hand[hand]
                    if last_hand_press is not None:
                        dt_press = max(10, t - last_hand_press)
                        speed_factor = (1000.0 / dt_press) ** 0.5
                    else:
                        speed_factor = 1.0

                    section_data[sec_idx]['coord'] += lock_weight * speed_factor

                new_holds.append(col)

            # 3. Write new holds to holding_columns after processing all presses in this batch
            for col in new_holds:
                holding_columns.add(col)
            
            for ev in presses:
                hand = col_to_hand[ev['col']]
                last_press_time_on_hand[hand] = t

        # Generate strain vectors for each section
        coord_strains = []
        rel_strains = []
        speed_strains = []
        combined_strains = []

        max_sec = max(section_data.keys()) if section_data else 0

        for sec_idx in range(max_sec + 1):
            raw_c = section_data[sec_idx]['coord']
            raw_r = section_data[sec_idx]['rel']
            raw_s = section_data[sec_idx]['speed']

            # Normalize units: Add baseline coefficients to align values, use 0.75 power to prevent local value explosion
            strain_c = ((raw_c * 0.2) ** 0.75) * self.od_phys_mult
            strain_r = ((raw_r * 0.4) ** 0.75) * self.od_tech_mult
            strain_s = ((raw_s * 0.4) ** 0.75) * self.od_phys_mult

            coord_strains.append(strain_c)
            rel_strains.append(strain_r)
            speed_strains.append(strain_s)

            # Combine strains within the section using weighted sum of squares
            strain_comb = (0.45 * strain_c**2 + 0.40 * strain_r**2 + 0.15 * strain_s**2) ** 0.5
            combined_strains.append(strain_comb)

        # Sum all strains with decay factors to get final ratings
        final_coord = self._calculate_decayed_strain(coord_strains)
        final_rel = self._calculate_decayed_strain(rel_strains)
        final_speed = self._calculate_decayed_strain(speed_strains)
        final_rating = self._calculate_decayed_strain(combined_strains)

        # ratios
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

def get_input_file():
    if len(sys.argv) > 1:
        return sys.argv[1]
    root = Tk()
    root.withdraw()
    return filedialog.askopenfilename(
        title="Select an osu! beatmap",
        filetypes=[("osu! beatmap", "*.osu")]
    )

if __name__ == "__main__":
    target_file = get_input_file()

    if not target_file:
        print("No file selected.")
        input("\nPress Enter to exit...")
        sys.exit()

    if not os.path.exists(target_file):
        print(f"File not found: {target_file}")
        input("\nPress Enter to exit...")
        sys.exit()

    try:
        bm = ManiaBeatmap(target_file)
        analyzer = LN1Analyzer(bm)
        result = analyzer.analyze()

        print("=" * 50)
        print(f" Artist - Title: {result['metadata']['artist']} - {result['metadata']['title']}")
        print(f" Difficulty: [{result['metadata']['version']}]")
        print(f" Creator: {result['metadata']['creator']}")
        print(f" OD: {result['metadata']['od']}")
        print(f" Total Objects: {result['metadata']['total_notes']} (LN Ratio: {result['metadata']['ln_ratio']})")
        print(f" Average NPS: {result['metadata']['nps']} note/s")
        print("-" * 50)
        print(f" Coordination Factor: {result['metrics']['coordination_rating']}")
        print(f" Release Multiplier: {result['metrics']['release_rating']}")
        print(f" Speed Multiplier: {result['metrics']['speed_factor']}")
        print(f" Combined LN1 Difficulty: {result['metrics']['total_ln_rating']}")
        print("-" * 50)
        print(f" Fingerlock Ratio: {result['ratios']['coordination_lock_ratio']}")
        print(f" Awkward Release Ratio: {result['ratios']['awkward_release_ratio']}")
        print("=" * 50)

    except Exception as e:
        print(f"Analysis failed: {e}")

    input("\nPress Enter to exit...")