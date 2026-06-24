import math
import os
import re
from tkinter import filedialog
from tkinter import Tk
import sys

class HitObject:
    """表示一个 osu!mania 的打击物件（Rice Note 或 Long Note）。"""
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
    """解析并存储 .osu 谱面的核心元数据和物件信息。"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.title = ""
        self.artist = ""
        self.version = ""
        self.creator = ""
        self.od = 8.0
        self.columns = 4  # 只有4k
        self.hit_objects = []
        self.parse_file()

    def parse_file(self):
        if not os.path.exists(self.filepath):
            raise FileNotFoundError(f"未找到指定的谱面文件: {self.filepath}")

        current_section = ""
        with open(self.filepath, 'r', encoding='utf-8-sig') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("//"):
                    continue

                # 匹配 Section 标签
                match_section = re.match(r'^\[(\w+)\]$', line)
                if match_section:
                    current_section = match_section.group(1)
                    continue

                # 解析元数据
                if current_section == "Metadata":
                    if line.startswith("Title:"):
                        self.title = line.split("Title:", 1)[1].strip()
                    elif line.startswith("Artist:"):
                        self.artist = line.split("Artist:", 1)[1].strip()
                    elif line.startswith("Version:"):
                        self.version = line.split("Version:", 1)[1].strip()
                    elif line.startswith("Creator:"):
                        self.creator = line.split("Creator:", 1)[1].strip()

                # 解析属性
                elif current_section == "Difficulty":
                    if line.startswith("OverallDifficulty:"):
                        self.od = float(line.split("OverallDifficulty:", 1)[1].strip())
                    elif line.startswith("CircleSize:"):
                        self.columns = int(line.split("CircleSize:", 1)[1].strip())

                # 解析 HitObjects
                elif current_section == "HitObjects":
                    parts = line.split(",")
                    if len(parts) >= 5:
                        x = int(parts[0])
                        # 4K 轨道计算：根据 x 坐标分配到 0, 1, 2, 3
                        col = min(self.columns - 1, max(0, int(x / (512 / self.columns))))
                        start_time = int(parts[2])
                        obj_type = int(parts[3])

                        # 判断是否为 LN (bit 7 被标记，即 type & 128)
                        if obj_type & 128:
                            # 最后一项是以冒号分隔的附加参数，第一个元素是结束时间
                            extra_parts = parts[5].split(":")
                            end_time = int(extra_parts[0])
                            self.hit_objects.append(HitObject(col, start_time, end_time))
                        else:
                            # 普通单键 (Rice)
                            self.hit_objects.append(HitObject(col, start_time))


class LN1Analyzer:
    """LN1 难度核心评估算法实现。"""
    def __init__(self, beatmap):
        self.beatmap = beatmap
        if beatmap.columns != 4:
            raise ValueError("当前算法仅针对 4K 模式进行优化建模！")
            
        # 1. 动态 OD Hit Window 映射
        self.od = beatmap.od
        self.w_300 = 64.0 - 3.0 * self.od
        self.w_200 = 97.0 - 3.0 * self.od
        
        # 动态放手恶心区间定义 (高斯曲线参数)
        self.mu_rel = self.w_300 + 15.0  # 别扭区间峰值
        self.sigma_rel = max(5.0, (self.w_200 - self.w_300) / 2.0)  # 别扭区间跨度
        
        # 全局高 OD 精度乘数
        self.m_precision = 1.0 + 0.5 * max(0.0, self.od - 7.0) ** 1.5

        # 短 LN 恶心区间参数
        self.l_peak = max(80.0, self.w_300 + 70.0)
        self.k_short = 0.5  # 最大惩罚倍率

    def analyze(self):
        objects = sorted(self.beatmap.hit_objects, key=lambda x: x.start_time)
        if not objects:
            return {}

        total_notes = len(objects)
        ln_notes = [obj for obj in objects if obj.is_ln]
        total_ln = len(ln_notes)
        ln_ratio = total_ln / total_notes if total_notes > 0 else 0

        # 获取谱面持续时间 (秒)
        duration = (objects[-1].start_time - objects[0].start_time) / 1000.0
        nps = total_notes / duration if duration > 0 else 0

        # 手指归属定义 (4K 常见布局)
        # 0: 左手外(中/无名)指, 1: 左手食指 | 2: 右手食指, 3: 右手外(中/无名)指
        col_to_hand = {0: 'L', 1: 'L', 2: 'R', 3: 'R'}
        col_to_finger_type = {0: 'outer', 1: 'index', 2: 'index', 3: 'outer'}

        # 事件流转化 (用于追踪实时手指状态)
        events = []
        for obj in objects:
            events.append({'time': obj.start_time, 'type': 'press', 'col': obj.col, 'obj': obj})
            if obj.is_ln:
                events.append({'time': obj.end_time, 'type': 'release', 'col': obj.col, 'obj': obj})
        
        # 按时间排序事件，若时间相同，先 Release 后 Press，防止状态重叠引发逻辑误判
        events.sort(key=lambda x: (x['time'], 0 if x['type'] == 'release' else 1))

        # 状态追踪器
        holding_columns = set()
        last_press_time_on_hand = {'L': None, 'R': None}
        all_actions_on_hand = {'L': [], 'R': []}  # 存储 (time, type) 供放手间距计算

        # 收集所有动作点以进行就近动作的时间差计算
        for ev in events:
            hand = col_to_hand[ev['col']]
            all_actions_on_hand[hand].append(ev)

        coord_score_total = 0.0
        rel_score_total = 0.0
        awkward_releases_count = 0  # 落在高难度放手区间的次数
        coordination_situations_count = 0  # 触发同手锁锚按压的次数

        # 开始遍历事件，计算协调度与放手难度
        for ev in events:
            time = ev['time']
            col = ev['col']
            hand = col_to_hand[col]
            f_type = col_to_finger_type[col]

            if ev['type'] == 'press':
                # --- 计算协调难度 (Coordination) ---
                # 检查同手另一轨道是否处于被锁（Hold）状态
                other_col = (col + 1) if col % 2 == 0 else (col - 1)
                
                if other_col in holding_columns:
                    coordination_situations_count += 1
                    other_f_type = col_to_finger_type[other_col]
                    
                    # 确定锁手指锚的类型
                    if other_f_type == 'index' and f_type == 'outer':
                        # 锁食指打中指 (难)
                        lock_weight = 1.5
                    elif other_f_type == 'outer' and f_type == 'index':
                        # 锁中指打食指 (易)
                        lock_weight = 1.0
                    else:
                        lock_weight = 1.0

                    # 引入局部速度惩罚 (相较于同手前一次按压的间隔)
                    last_hand_press = last_press_time_on_hand[hand]
                    if last_hand_press is not None:
                        dt_press = max(10, time - last_hand_press)
                        # 间隔越短，协调压力呈指数级别增长
                        speed_factor = (1000.0 / dt_press) ** 0.5
                    else:
                        speed_factor = 1.0

                    coord_score_total += lock_weight * speed_factor

                holding_columns.add(col)
                last_press_time_on_hand[hand] = time

            elif ev['type'] == 'release':
                if col in holding_columns:
                    holding_columns.remove(col)

                # --- 计算放手难度 (Release) ---
                # 1. 寻找同手其余动作的最小时间差 delta_t
                hand_actions = all_actions_on_hand[hand]
                min_dt = float('inf')
                for other_ev in hand_actions:
                    # 排除自己本身这次放手事件
                    if other_ev is ev:
                        continue
                    dt = abs(time - other_ev['time'])
                    if dt < min_dt:
                        min_dt = dt

                # 2. 动态放手惩罚计算 (高斯分布)
                p_val = 0.0
                if min_dt != float('inf') and min_dt > 0:
                    p_val = math.exp(-((min_dt - self.mu_rel) ** 2) / (2 * (self.sigma_rel ** 2)))
                    # 记录玩家是否被迫在 200/100 判定区间内放手
                    if self.w_300 < min_dt <= self.w_200:
                        awkward_releases_count += 1

                # 3. 短 LN 的黏手惩罚计算
                m_short_val = 1.0
                obj = ev['obj']
                if obj.is_ln:
                    ln_len = obj.length
                    # 仅在 40ms 到 250ms 的短面条区间施加惩罚
                    if 40 <= ln_len <= 250:
                        m_short_val = 1.0 + self.k_short * math.exp(-((ln_len - self.l_peak) ** 2) / (2 * (25.0 ** 2)))

                rel_score_total += p_val * m_short_val

        # 归一化评分
        norm_factor = 100.0 / max(100, total_notes)

        raw_coord = (coord_score_total * norm_factor) * self.m_precision
        raw_rel = (rel_score_total * norm_factor) * self.m_precision
        raw_speed = nps * 0.4

        # 幂函数压缩
        coord_star = raw_coord ** 0.67
        rel_star   = raw_rel ** 0.67
        speed_star = raw_speed ** 0.67

        # 均方根融合
        final_rating = (
            0.40 * coord_star ** 2 +
            0.35 * rel_star ** 2 +
            0.25 * speed_star ** 2
        ) ** 0.5

        final_coord = coord_star
        final_rel = rel_star
        final_speed = speed_star

        # 比例指标
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

# ==========================================
# 自动执行测试段：解析上传的 .osu 文件并运行分析
# ==========================================
if __name__ == "__main__":

    target_file = get_input_file()

    if not target_file:
        print("未选中任何文件。")
        input("\n按 Enter 键退出...")
        sys.exit()

    if not os.path.exists(target_file):
        print(f"文件未找到: {target_file}")
        input("\n按 Enter 键退出...")
        sys.exit()

    try:
        bm = ManiaBeatmap(target_file)
        analyzer = LN1Analyzer(bm)
        result = analyzer.analyze()

        print("=" * 50)
        print(
            f" 艺术家 - 标题 : "
            f"{result['metadata']['artist']} - "
            f"{result['metadata']['title']}"
        )

        print(
            f" 难度名: "
            f"[{result['metadata']['version']}]"
        )

        print(f" 作者: {result['metadata']['creator']}")
        print(f" OD: {result['metadata']['od']}")

        print(
            f" 总物量: "
            f"{result['metadata']['total_notes']} "
            f"(LN 比例: {result['metadata']['ln_ratio']})"
        )

        print(
            f" 平均密度 (NPS): "
            f"{result['metadata']['nps']} note/s"
        )

        print("-" * 50)

        print(
            f" 协调乘数(Coordination): "
            f"{result['metrics']['coordination_rating']}"
        )

        print(
            f" 放手乘数(Release): "
            f"{result['metrics']['release_rating']}"
        )

        print(
            f" 速度乘数(Speed): "
            f"{result['metrics']['speed_factor']}"
        )

        print(
            f" 综合 LN1 难度: "
            f"{result['metrics']['total_ln_rating']}"
        )

        print("-" * 50)

        print(
            f" 锁手触发比例: "
            f"{result['ratios']['coordination_lock_ratio']}"
        )

        print(
            f" 别扭放手区间占比: "
            f"{result['ratios']['awkward_release_ratio']}"
        )

        print("=" * 50)

    except Exception as e:
        print(f"分析失败: {e}")

    input("\n按 Enter 键退出...")