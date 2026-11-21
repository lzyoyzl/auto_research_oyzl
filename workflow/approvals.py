"""Human-facing requests and experiment resource arithmetic (hours, GiB, currency units)."""
import json
import math
import csv
import os
import re
import shutil
import subprocess
from pathlib import Path

WAITING = {"idea_review", "budget_review"}


def proposal_path(s):
    revision = s.get("proposal_revision", 1)
    return "ideas.json" if revision == 1 else f"proposals/{revision:02}/ideas.json"


def pilot_dir(s):
    return f"pilots/{s['selection']:02}/{s['pilot_attempt']:02}"


def budget_path(s):
    return f"budgets/{s.get('budget_revision', 1):02}/request.json"


def round_path(s):
    path = f"rounds/{s['round']:02}"
    if s.get("plan_revision", 1) > 1:
        path += f"-rev{s['plan_revision']:02}"
    return path


def positive_number(obj, key, *, zero=False):
    x = obj.get(key)
    if type(x) not in (float, int) or not math.isfinite(x) or x < 0 or (not zero and x == 0):
        raise ValueError(f"Invalid resource quantity: {key}")
    return x


def hardware(obj):
    cards = obj.get("cards")
    mem = positive_number(obj, "vram_gib_per_card", zero=True)
    model = obj.get("gpu_model")
    if type(cards) is not int or cards < 0 or not isinstance(model, str) or not model.strip():
        raise ValueError("Specify GPU model, integer card count and peak GiB per card (CPU: CPU, 0, 0)")
    if (cards == 0) != (mem == 0) or (cards == 0) != (model == "CPU"):
        raise ValueError("Inconsistent GPU model/count/VRAM")
    return {"gpu_model": model, "cards": cards, "vram_gib_per_card": mem}


def estimate(req):
    hw = hardware(req)
    hours = positive_number(req, "wall_hours")
    rate = positive_number(req, "hourly_rate", zero=True)
    currency = req.get("currency", "")
    if not isinstance(currency, str) or not re.fullmatch("[A-Z]{3}", currency):
        raise ValueError("Specify currency as a three-letter code")
    card_hours = hours * hw["cards"]
    cost = hours * max(1, hw["cards"]) * rate
    if not math.isfinite(card_hours) or not math.isfinite(cost):
        raise ValueError("Non-finite budget")
    return dict(hw, wall_hours=hours, gpu_hours=card_hours, cost=cost, hourly_rate=rate, currency=currency)


def totals(run, grant_id):
    seconds = gpu_hours = cost = 0.0
    for path in sorted((run / "accounting").glob("*.json")):
        charge = json.loads(path.read_text())
        if charge["grant"] != grant_id:
            continue
        # Interrupted reservations are counted in full until reconciled.
        duration = charge.get("charged_seconds", charge["reserved_seconds"])
        seconds += duration
        gpu_hours += duration * charge["cards"] / 3600
        cost += duration * max(1, charge["cards"]) * charge["hourly_rate"] / 3600
    return {"wall_hours": seconds / 3600, "gpu_hours": gpu_hours, "cost": cost}


def excess(run, grant, proposed):
    caps = grant["limits"]
    if (proposed["cards"] and proposed["gpu_model"] != caps["gpu_model"]
            or proposed["cards"] > caps["cards"]
            or proposed["vram_gib_per_card"] > caps["vram_gib_per_card"]
            or proposed["currency"] != caps["currency"] or proposed["hourly_rate"] > caps["hourly_rate"]):
        return "所需硬件配置、币种或单价超出已批范围。"
    used = totals(run, grant["id"])
    for key in ("wall_hours", "gpu_hours", "cost"):
        if used[key] + proposed[key] > caps[key] + 1e-10:
            return f"下一次运行预计超过已批 {key}：已记 {used[key]:.8g}，新增 {proposed[key]:.8g}，上限 {caps[key]:.8g}。"
    return ""


def pending_text(run, s):
    gate = s["pending"]
    if s["phase"] == "idea_review":
        obj = json.loads((run / proposal_path(s)).read_text())
        lines = [f"# 选题审核 {gate['id']} · {s['direction']}", f"推荐 {gate['recommended']}。{gate['reason']}"]
        for item in obj["ideas"]:
            lines.append(f"\n## {item['id']} · {item['title']}\n")
            # Older sealed proposals may contain only the original comparison.
            for key, label in (("novelty_assessment", "查新判断"), ("closest_difference", "最近邻与差异"),
                               ("introduction", "Introduction"), ("background", "Background"),
                               ("motivation", "Motivation"), ("evidence_gap", "已知证据与待验证前提"),
                               ("technical_obstacle", "技术难点"), ("mechanism", "核心机制"),
                               ("design_argument", "从设计到任务目标"), ("design_check", "设计核验"),
                               ("cost_boundary", "代价与适用边界"), ("prediction", "机制产生的可区分预测"),
                               ("competing_explanation", "竞争解释与对照"),
                               ("pilot", "预实验"), ("falsifier", "推翻条件")):
                if key in item:
                    lines.append(f"**{label}**　{item[key]}\n")
                if key == "closest_difference" and "technical_neighbor" in item:
                    neighbor = item["technical_neighbor"]
                    lines.append(f"**已有方法直接迁移的强对照**　{neighbor['transfer_baseline']} "
                                 f"[原文章节 · {neighbor['section']}]({neighbor['url']})\n")
            sources = []
            for ident in item["sources"]:
                url = json.loads((run / "sources" / ident / "source.json").read_text())["url"]
                sources.append(f"[{ident}]({url})")
            lines.append("参考原文　" + " · ".join(sources))
        lines.append("\n请选择候选 ID、指出需要补强的论证，或退回整批并提出意见。")
    else:
        req = json.loads((run / budget_path(s)).read_text())
        limits = estimate(req)
        pilot = json.loads((run / req["pilot_ref"]).read_text())
        peak = pilot["peak_vram_gib_per_card"]
        peak_text = "未测得" if peak is None else f"{peak:g} GiB/卡"
        observed = (f"{pilot['gpu_model']} × {pilot['cards']}，实测峰值显存 {peak_text}"
                    if pilot["cards"] else "CPU 运行，未占用 GPU；GPU 峰值显存未经实测")
        lines = [f"正式实验算力审核 {gate['id']} · {s['idea']}",
                 f"预实验：{pilot['workload']}，n={pilot['n']}，实耗 {pilot['elapsed_seconds']:.4g} 秒，"
                 f"{observed}。",
                 f"正式配置：{limits['gpu_model']}，{limits['cards']} 张卡，预计每卡峰值 {limits['vram_gib_per_card']:g} GiB。",
                 f"申请总量：{limits['wall_hours']:.6g} 墙钟小时，{limits['gpu_hours']:.6g} 卡时，"
                 f"预计费用及上限 {limits['cost']:.8g} {limits['currency']}。",
                 f"单价：{limits['hourly_rate']:.8g} {limits['currency']}/"
                 + ("卡时。" if limits["cards"] else "主机小时。"),
                 f"计价依据：{req['pricing_basis']}", f"外推方法及不确定性：{req['estimate_basis']}",
                 f"预实验记录：{req['pilot_ref']}"]
        if s.get("budget_reason"):
            lines.append("申请原因：" + s["budget_reason"])
        if s.get("grant"):
            prev = s["grant"]
            used = totals(run, prev["id"])
            lines.append(f"上一批额度已记 {used['gpu_hours']:.6g} 卡时、{used['cost']:.8g} "
                         f"{prev['limits']['currency']}。本申请为后续新增额度，替换旧批次余额。")
        lines.append("请批准本申请，或退回调整配置和费用。")
    return "\n".join(lines)


def process_env(shape, pilot_device=None):
    """Bind cooperating CUDA workloads to the allocated visible local GPUs."""
    env = os.environ.copy()
    if not shape["cards"]:
        env.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", HIP_VISIBLE_DEVICES="",
                   ROCR_VISIBLE_DEVICES="", JAX_PLATFORMS="cpu")
        return env, "CPU"
    smi = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
    if not Path(smi).is_file():
        raise RuntimeError("批准的 NVIDIA GPU 尚未分配到本机。配置资源后 resume。")
    raw = subprocess.check_output([smi, "--query-gpu=index,uuid,name,memory.total", "--format=csv,noheader,nounits"],
                                  text=True, timeout=10)
    visible = env.get("CUDA_VISIBLE_DEVICES")
    allowed = set(visible.split(",")) if visible is not None else None
    devices = []
    for index, uuid, name, mib in csv.reader(raw.splitlines(), skipinitialspace=True):
        if allowed is not None and not {index, uuid} & allowed:
            continue
        if pilot_device is not None and pilot_device not in {index, uuid}:
            continue
        if pilot_device is None and (name != shape["gpu_model"] or float(mib) / 1024 < shape["vram_gib_per_card"]):
            continue
        devices.append((uuid, name))
    if len(devices) < shape["cards"]:
        raise RuntimeError("可见 GPU 型号、张数或显存不足。按已批配置分配设备后 resume。")
    env["CUDA_VISIBLE_DEVICES"] = ",".join(u for u, _ in devices[:shape["cards"]])
    env["NVIDIA_VISIBLE_DEVICES"] = env["CUDA_VISIBLE_DEVICES"]
    return env, devices[0][1]
