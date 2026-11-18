"""Durable controller for direction-driven empirical research. Run in WSL/Linux."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
import re
from pathlib import Path
import signal
from statistics import fmean
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone

from approvals import (WAITING, budget_path, estimate, excess, hardware, pending_text, pilot_dir,
                       process_env, proposal_path, round_path, totals)
from reading import capture, normal, paper_id, pdf_text
from tasks import task
from venues import VENUES, compile_tex, prepare

ROOT = Path(__file__).resolve().parents[1]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
    os.replace(f.name, path)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


@contextmanager
def lock(folder, name):
    with (folder / name).open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This study already has an active operation.") from None
        yield


def fields(obj, names):
    require(isinstance(obj, dict), "Expected a JSON object")
    for key in names.split():
        require(isinstance(obj.get(key), str) and obj[key].strip(), f"Missing text field {key}")


def items(value, n, label):
    require(isinstance(value, list) and len(value) >= n, f"{label} needs at least {n} entries")
    return value


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def verify_units(rd, split, values):
    path = rd / f"{split}-scores.json"
    rows = items(read(path), 1, "Paired raw evaluation units")
    require(len(rows) == values["n"], "Unit count differs from reported n")
    ids = set()
    for row in rows:
        fields(row, "unit")
        require(row["unit"] not in ids and all(finite(row.get(k)) for k in ("baseline", "candidate")),
                "Expected distinct units and paired finite scores")
        ids.add(row["unit"])
    for key in ("baseline", "candidate"):
        require(math.isclose(fmean(row[key] for row in rows), values[key], abs_tol=1e-8, rel_tol=1e-7),
                f"{key} mean differs from raw evidence")
    return path


def remember(run, state, *paths):
    for path in paths:
        state["sealed"][str(path.relative_to(run))] = digest(path)


def check(run, state):
    for relative, expected in state["sealed"].items():
        require(digest(run / relative) == expected, f"Frozen evidence changed: {relative}")


def review_state():
    return {"approval_version": 1, "proposal_revision": 1, "budget_revision": 1,
            "selection": 0, "receipts": [], "grant": None}


def ask_idea(s, obj, recommended, reason):
    s["pending"] = {"id": f"idea-{len(s['history']) + 1}", "recommended": recommended, "reason": reason}
    s["venue"] = obj["venue"]
    return "idea_review"


def current(run):
    """Called under the state lock. Older unfinished runs must acquire actual approvals."""
    s = read(run / "state.json")
    if "approval_version" not in s:
        check(run, s)
        s.update(review_state())
        if s["phase"] in {"plan", "decide", "confirm"}:
            obj = read(run / "ideas.json")
            s["phase"] = ask_idea(s, obj, s["idea"], "旧研究尚未记录人工选题及预算批准。")
            occupied = [int(p.name) for p in (run / "rounds").glob("*") if p.name.isdigit()]
            s["round"] = max([s["round"]] + [n + 1 for n in occupied])
            s["max_rounds"] = max(s["round"], s["max_rounds"])
            s["idea"] = None
        save(run / "state.json", s)
    return s


def snapshot(run):
    with lock(run, ".state.lock"):
        s = current(run)
        check(run, s)
        return s


def new(direction, run=None, rounds=4, seconds=300):
    require(direction.strip() and rounds > 0 and seconds > 0, "Supply a direction and positive budget")
    ident = hashlib.sha256(direction.strip().encode()).hexdigest()[:12]
    run = (run or ROOT / "studies" / ident).resolve()
    run.mkdir(parents=True, exist_ok=True)
    with lock(run, ".state.lock"):
        path = run / "state.json"
        if path.exists():
            require(read(path)["direction"] == direction.strip(), "Directory belongs to another direction")
        else:
            require(not any(p.name != ".state.lock" for p in run.iterdir()), "Use an empty study directory")
            save(path, {**review_state(), "direction": direction.strip(), "phase": "discover", "round": 1,
                        "max_rounds": rounds, "timeout": seconds, "idea": None, "version": 1,
                        "history": [], "sealed": {}, "measurements": []})
    return run


def literature(run, s):
    path = run / "literature.json"
    doc = read(path)
    items(doc.get("searches"), 1, "Search log")
    seen, contents, urls = set(), set(), set()
    for paper in items(doc.get("papers"), 3, "Full-text papers"):
        fields(paper, "id title section excerpt method data comparison finding limitation")
        require(normal(paper["section"]).casefold() not in {"abstract", "摘要"},
                "Read a methods, results, or limitations section in the original paper")
        ident = paper_id(paper["id"])
        folder = run / "sources" / ident
        textfile, metafile = folder / "text.txt", folder / "source.json"
        meta = read(metafile)
        require(ident not in seen and meta["text_sha256"] not in contents and meta["url"] not in urls,
                "Duplicate reading record")
        require(digest(textfile) == meta["text_sha256"], "Cached source changed")
        excerpt = normal(paper["excerpt"])
        require(len(excerpt) >= 12 and excerpt in normal(textfile.read_text()), f"Unmatched excerpt in {ident}")
        seen.add(ident)
        contents.add(meta["text_sha256"])
        urls.add(meta["url"])
        remember(run, s, textfile, metafile)
    remember(run, s, path)
    return "ideas"


def discover(run, s):
    path = run / "search.json"
    search = read(path)
    items(search.get("queries"), 1, "Search queries")
    results, seen = {}, set()
    for source in items(search.get("sources"), 3, "Search sources"):
        fields(source, "id title url")
        ident = paper_id(source["id"])
        require(ident not in results, "Duplicate discovered ID")
        try:
            folder = capture(run, ident, source["url"])
            seen.add(read(folder / "source.json")["text_sha256"])
            results[ident] = "cached"
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            results[ident] = str(exc)
    save(run / "downloads.json", results)
    require(len(seen) >= 3, "Need three distinct readable sources; inspect downloads.json and try alternate full texts.")
    remember(run, s, path, run / "downloads.json")
    return "read"


def shortlist(run, s):
    sources = {p["id"] for p in read(run / "literature.json")["papers"]}
    path = run / proposal_path(s)
    obj = read(path)
    fields(obj, "reason venue venue_reason")
    require(obj["venue"] in VENUES, "Choose one supported conference template")
    ids, mechanisms = [], set()
    rejected = {normal(i["mechanism"]).casefold() for receipt in s["receipts"] if receipt["action"] == "repropose"
                for i in read(run / receipt["artifact"])["ideas"]}
    for idea in items(obj.get("ideas"), 3, "Ranked ideas"):
        fields(idea, "id title novelty_assessment closest_difference introduction background motivation mechanism pilot falsifier")
        fields(idea, "evidence_gap prediction competing_explanation")
        ident = paper_id(idea["id"])
        require(ident not in ids and normal(idea["mechanism"]) not in mechanisms, "Duplicate candidate")
        require(normal(idea["mechanism"]).casefold() not in rejected, "Previously rejected mechanism; propose a new idea")
        require(set(items(idea.get("sources"), 1, "Source IDs")) <= sources, "Unknown source ID")
        ids.append(ident)
        mechanisms.add(normal(idea["mechanism"]))
    remember(run, s, path)
    return ask_idea(s, obj, ids[0], obj["reason"])


def record_reply(run, request, action, value=None, pilot_gpu=None):
    """Only the human-facing CLI/chat handler invokes this function. Workers never do."""
    with lock(run, ".state.lock"):
        s = current(run)
        check(run, s)
        phase = s["phase"]
        require(phase in WAITING and request == s["pending"]["id"], "No matching pending review; inspect next/status")
        expected = {"idea_review": {"choose", "repropose", "revise-brief"}, "budget_review": {"approve-budget", "revise-budget"}}
        require(action in expected[phase], "Wrong response for this review")
        artifact = proposal_path(s) if phase == "idea_review" else budget_path(s)
        if action == "choose":
            obj = read(run / artifact)
            require(value in [i["id"] for i in obj["ideas"]], "Choose an ID from this proposal")
            if value == s["idea"] and s.get("selected_proposal") == artifact and s.get("pilot_ref"):
                following = "plan"
            else:
                s.update(idea=value, selected_proposal=artifact, selection=s["selection"] + 1, pilot_attempt=1,
                         pilot_gpu=pilot_gpu, pilot_ref=None, budget_selection=None)
                s.pop("needed", None)
                following = "pilot"
        elif action in {"repropose", "revise-brief"}:
            s["proposal_revision"] += 1
            if action == "revise-brief":
                require(value and value.strip(), "Specify what the proposal should clarify")
                s["idea_feedback"] = f"修订 {artifact} 的论证后重新送审。用户反馈：{value}"
            else:
                s["idea_feedback"] = value or "本批候选均未获认可，请提出不同的机制。"
            following = "ideas"
        elif action == "approve-budget":
            s["grant"] = {"id": request, "limits": estimate(read(run / artifact)), "artifact": artifact}
            s["budget_selection"] = s["selection"]
            following = s["budget_resume"]
        else:
            s["budget_revision"] += 1
            s["budget_reason"] = value or "请提交调整后的资源方案。"
            if s.pop("needed", None):
                # A lower ceiling may require a smaller experiment. Keep old files and
                # any measured development scores; pair the new design with its own confirmation.
                s["plan_revision"] = s.get("plan_revision", 1) + 1
                s["budget_resume"] = "plan"
            following = "budget"
        s["receipts"].append({"id": request, "action": action, "value": value, "pilot_gpu": pilot_gpu,
                              "artifact": artifact, "sha256": digest(run / artifact),
                              "time": datetime.now(timezone.utc).isoformat()})
        s.pop("pending")
        s["history"].append({"from": phase, "to": following, "round": s["round"], "reply": action})
        s["phase"] = following
        save(run / "state.json", s)
        return following


def execute(script, args, logfile, seconds, env):
    started = time.monotonic()
    with logfile.open("wb") as stream:
        # GNU timeout survives loss of the controller and bounds its experiment process group.
        proc = subprocess.Popen(["timeout", "--signal=KILL", f"{seconds}s", sys.executable, script.name, *args], cwd=script.parent,
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True, env=env)
        try:
            status = proc.wait(timeout=seconds + 1)
            if status in (124, 137, -signal.SIGKILL):
                status = "timeout"
        except subprocess.TimeoutExpired:
            status = "timeout"
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
    return status, time.monotonic() - started


def last_output(logfile):
    with logfile.open("rb") as stream:
        stream.seek(max(0, stream.seek(0, 2) - 100000))
        return json.loads(stream.read().strip().splitlines()[-1])


def start_budget(s, resume, reason=""):
    if s.get("last_budget_path") == budget_path(s):
        s["budget_revision"] += 1
    s.update(budget_resume=resume, budget_reason=reason)
    return "budget"


def profile(run, s):
    require(s["idea"] and s["selection"] > 0, "Human idea selection required")
    folder = run / pilot_dir(s)
    script, plan_path = folder / "pilot.py", folder / "plan.json"
    plan = read(plan_path)
    fields(plan, "idea_id workload")
    require(plan["idea_id"] == s["idea"], "Pilot does not match the approved idea")
    result_path, logfile = folder / "result.json", folder / "pilot.log"
    frozen = {"code": digest(script), "plan": digest(plan_path)}
    if not result_path.exists():
        gpu = s.get("pilot_gpu")
        cards = int(gpu is not None)
        env, model = process_env({"cards": cards}, gpu)
        status, elapsed = execute(script, [], logfile, min(60, s["timeout"]), env)
        result = dict(frozen=frozen, idea_id=s["idea"], workload=plan["workload"], cards=cards,
                      gpu_model=model, elapsed_seconds=elapsed, exit=status, outcome="error")
        try:
            require(status == 0, f"Pilot exited with {status}")
            output = last_output(logfile)
            require(isinstance(output, dict) and type(output.get("n")) is int and output["n"] > 0,
                    "Report a positive number of measured pilot units")
            peak = output.get("peak_vram_gib_per_card") if cards else 0
            require(peak is None or finite(peak) and peak >= 0, "Invalid measured GPU peak")
            result.update(n=output["n"], peak_vram_gib_per_card=peak, outcome="measured")
        except (ValueError, TypeError, IndexError) as exc:
            result["error"] = str(exc)
        save(result_path, result)
    result = read(result_path)
    require(result["frozen"] == frozen, "Pilot inputs changed after execution")
    remember(run, s, result_path, script, plan_path, logfile)
    if result["outcome"] != "measured":
        s["pilot_attempt"] += 1
        if s["pilot_attempt"] <= 3:
            return "pilot"
        s["idea_feedback"] = "三次限额内预实验均未产生有效测量。根据预实验日志重拟可检验的候选。"
        s["proposal_revision"] += 1
        return "ideas"
    s["pilot_ref"] = str(result_path.relative_to(run))
    return start_budget(s, "plan")


def request_budget(run, s):
    path = run / budget_path(s)
    obj = read(path)
    fields(obj, "idea_id pilot_ref estimate_basis pricing_basis")
    require(obj["idea_id"] == s["idea"] and obj["pilot_ref"] == s["pilot_ref"], "Use this idea's measured pilot")
    require(read(run / s["pilot_ref"])["outcome"] == "measured", "Pilot measurement required")
    limits = estimate(obj)
    needed = s.get("needed")
    if needed:
        # A top-up must accommodate the pending run, even with a fresh allowance.
        require(not excess(run, {"id": "unissued", "limits": limits}, needed),
                "Requested allowance cannot cover the pending experiment; revise the estimate")
    s["last_budget_path"] = budget_path(s)
    remember(run, s, path)
    if s["grant"] and not excess(run, s["grant"], limits) and not (needed and excess(run, s["grant"], needed)):
        s["budget_selection"] = s["selection"]
        return s["budget_resume"]
    s["pending"] = {"id": f"budget-{s['budget_revision']}"}
    return "budget_review"


def measure(run, rd, s, split):
    require(s.get("grant") and s["selection"] == s.get("budget_selection") and s["selection"] > 0,
            "Formal execution requires an approved idea, measured pilot and budget")
    plan_path, code = rd / "plan.json", rd / "experiment.py"
    plan = read(plan_path)
    fields(plan, "idea_id hypothesis change dataset metric dev_split confirm_split")
    require(plan["idea_id"] == s["idea"], "Wrong idea for this round")
    require(plan["dev_split"].strip() != plan["confirm_split"].strip(), "Specify distinct development and confirmation data")
    require(finite(plan.get("min_gain")) and plan["min_gain"] >= 0
            and type(plan.get("higher_is_better")) is bool, "Specify a finite threshold and metric direction")
    frozen = {"plan": digest(plan_path), "code": digest(code)}
    if split == "confirm":
        require(frozen == read(rd / "dev.json")["frozen"], "Confirmation code or protocol differs from development")
    dest = rd / f"{split}.json"
    charge_path = run / "accounting" / f"{rd.name}-{split}.json"
    if dest.exists():
        result = read(dest)
        require(result["frozen"] == frozen, "An interrupted run already measured different inputs")
    else:
        logfile = rd / f"{split}.log"
        if charge_path.exists():
            # An interrupted controller must not start another paid process for the same reservation.
            charge = read(charge_path)
            require(charge["frozen"] == frozen, "Interrupted experiment inputs changed")
            status = charge.get("exit", "interrupted")
            logfile.touch(exist_ok=True)
        else:
            spec = plan.get("compute", {})
            hardware(spec)
            seconds = spec.get("seconds")
            require(type(seconds) is int and seconds > 0, "Specify the maximum wall seconds per job")
            proposed = estimate(dict(spec, wall_hours=seconds / 3600))
            over = excess(run, s["grant"], proposed)
            if over:
                s["needed"] = proposed
                return start_budget(s, s["phase"], over)
            # Respect both the study runtime limit and the selected job's reservation.
            seconds = min(seconds, s["timeout"])
            env, _ = process_env(proposed)
            charge = {"grant": s["grant"]["id"], "cards": proposed["cards"], "hourly_rate": proposed["hourly_rate"],
                      "currency": proposed["currency"], "reserved_seconds": seconds, "frozen": frozen}
            save(charge_path, charge)
            status, elapsed = execute(code, ["--split", split], logfile, seconds, env)
            charge.update(exit=status, elapsed_seconds=elapsed, charged_seconds=min(seconds, elapsed))
            save(charge_path, charge)
        result = {"split": split, "idea_id": s["idea"], "frozen": frozen, "exit": status,
                  "accounting": str(charge_path.relative_to(run)),
                  "outcome": "execution_error", "metric": plan["metric"]}
        try:
            require(status == 0, f"Experiment exited with {status}")
            values = last_output(logfile)
            require(isinstance(values, dict) and all(finite(values.get(k)) for k in ("baseline", "candidate"))
                    and type(values.get("n")) is int and values["n"] > 0,
                    "Last output line must report finite baseline, candidate, and positive integer n")
            raw = verify_units(rd, split, values)
            gain = values["candidate"] - values["baseline"]
            gain = gain if plan["higher_is_better"] else -gain
            require(finite(gain), "Invalid difference")
            result.update(baseline=values["baseline"], candidate=values["candidate"], n=values["n"],
                          raw=raw.name, raw_sha256=digest(raw), gain=gain,
                          outcome="met" if gain > 0 and gain >= plan["min_gain"] else "not_met")
        except (OSError, ValueError, IndexError, TypeError, KeyError) as exc:
            result["error"] = str(exc)
        require(frozen == {"plan": digest(plan_path), "code": digest(code)},
                "The experiment modified its own frozen program or plan")
        save(dest, result)
    remember(run, s, plan_path, code, dest, rd / f"{split}.log")
    if "raw" in result:
        raw = rd / result["raw"]
        require(digest(raw) == result["raw_sha256"], "Raw measurement changed")
        remember(run, s, raw)
    remember(run, s, charge_path)
    s.pop("needed", None)
    s["measurements"].append(str(dest.relative_to(run)))
    return "decide" if split == "dev" else finish_measurements(run, s)


def finish_measurements(run, s):
    if any(read(run / p)["outcome"] != "execution_error" for p in s["measurements"]):
        return "write"
    s["reason"] = "实验预算内未获得有效测量。可从各轮日志诊断执行问题。"
    return "blocked"


def decision(run, rd, s):
    path = rd / "decision.json"
    d = read(path)
    fields(d, "action idea_id diagnosis next_test")
    action, ident = d["action"], d["idea_id"]
    obj = read(run / proposal_path(s))
    ids = {i["id"] for i in obj["ideas"]}
    require(ident in ids and (ident != s["idea"]) == (action == "pivot"), "Idea and decision disagree")
    require(action in {"refine", "pivot", "confirm", "write"}, "Unknown decision")
    remember(run, s, path)
    if action == "confirm":
        require(read(rd / "dev.json")["outcome"] == "met", "Confirm requires qualifying development evidence")
        return "confirm"
    if action == "write" or s["round"] >= s["max_rounds"]:
        return finish_measurements(run, s)
    s["round"] += 1
    s.pop("plan_revision", None)
    if action == "pivot":
        return ask_idea(s, obj, ident, f"{d['diagnosis']} 下一步拟验证：{d['next_test']}")
    return "plan"


def manuscript(run, s, folder):
    draft, claims = folder / "draft.md", folder / "claims.json"
    body = draft.read_text(encoding="utf-8")
    require(len(body.strip()) >= 200, "Draft is empty or too short for review")
    urls = [read(run / "sources" / p["id"] / "source.json")["url"]
            for p in read(run / "literature.json")["papers"]]
    require(any(url in body for url in urls), "Cite primary sources in the draft")
    evidence = {p for p in s["measurements"] if read(run / p)["outcome"] != "execution_error"}
    for c in items(read(claims), 1, "Empirical claims"):
        fields(c, "claim")
        require(c["claim"] in body and set(items(c.get("evidence"), 1, "Evidence")) <= evidence,
                "Each claim must appear in the draft and reference measured results")
    remember(run, s, claims, draft)
    return "review"


def advance(run):
    with lock(run, ".state.lock"):
        s = current(run)
        check(run, s)
        phase, number = s["phase"], s["round"]
        rd = run / round_path(s)
        writing = run / "writing" / f"v{s['version']:02}"
        if phase == "discover":
            following = discover(run, s)
        elif phase == "read":
            following = literature(run, s)
        elif phase == "ideas":
            following = shortlist(run, s)
        elif phase in WAITING:
            return phase
        elif phase == "pilot":
            following = profile(run, s)
        elif phase == "budget":
            following = request_budget(run, s)
        elif phase == "plan":
            following = measure(run, rd, s, "dev")
        elif phase == "decide":
            following = decision(run, rd, s)
        elif phase == "confirm":
            following = measure(run, rd, s, "confirm")
        elif phase == "write":
            following = manuscript(run, s, writing)
        elif phase == "review":
            path = writing / "review.json"
            doc = read(path)
            require(doc.get("verdict") in {"ready", "revise"} and isinstance(doc.get("issues"), list),
                    "Need a review verdict and issue list")
            items(doc.get("checks"), 1, "Review checks")
            remember(run, s, path)
            if doc["verdict"] == "ready":
                require(not doc["issues"], "Resolve outstanding review issues")
                prepare(s["venue"], run / "latex")
                following = "typeset"
            elif s["version"] >= 3:
                require(doc["issues"], "List the required revisions")
                s["reason"] = "三版稿件后仍有审查问题，见最后一份 review.json。"
                following = "blocked"
            else:
                require(doc["issues"], "List the required revisions")
                s["version"] += 1
                following = "write"
        elif phase == "typeset":
            tex = run / "latex" / "manuscript.tex"
            bib = run / "latex" / "references.bib"
            kit = VENUES[s["venue"]]
            prepare(s["venue"], tex.parent)
            body = tex.read_text()
            style = next(Path(f).stem for f in kit["files"] if f.endswith(".sty")
                         and Path(f).stem.startswith(s["venue"]))
            require(style in body and "@" in bib.read_text(),
                    "Use the selected official style and verified BibTeX references")
            pdf = compile_tex(tex, tex.parent / "build.log")
            # PDF fonts can insert ligatures, whitespace or line-break hyphens.
            def normalized_claim(text):
                text = re.sub(r"(?<=[a-zA-Z])-\s*\n\s*(?=[a-zA-Z])", "", text)
                text = unicodedata.normalize("NFKC", text).casefold().replace("−", "-")
                return "".join(c for c in text if c.isalnum() or c in "+-%.")
            rendered = normalized_claim(pdf_text(pdf.read_bytes(), manuscript=True))
            for claim in read(writing / "claims.json"):
                require(normalized_claim(claim["claim"]) in rendered,
                        f"Reviewed claim missing or changed in PDF: {claim['claim']}")
            (run / "paper.md").write_bytes((writing / "draft.md").read_bytes())
            (run / "paper.pdf").write_bytes(pdf.read_bytes())
            remember(run, s, tex, bib, run / "paper.md", run / "paper.pdf")
            following = "done"
        else:
            return phase
        s["history"].append({"from": phase, "to": following, "round": number})
        s["phase"] = following
        if following in WAITING:
            note = run / "reviews" / (s["pending"]["id"] + ".md")
            note.parent.mkdir(exist_ok=True)
            note.write_text(pending_text(run, s) + "\n", encoding="utf-8")
            remember(run, s, note)
        save(run / "state.json", s)
        return following


def cli():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "run"):
        p = sub.add_parser(name)
        p.add_argument("direction")
        p.add_argument("--dir", type=Path)
        p.add_argument("--rounds", type=int, default=4)
        p.add_argument("--seconds", type=int, default=300)
    for name in ("next", "advance", "status", "resume", "source"):
        p = sub.add_parser(name)
        p.add_argument("directory", type=Path)
        if name == "source":
            p.add_argument("id")
            p.add_argument("url")
            p.add_argument("--file", type=Path)
    for name in ("choose", "repropose", "revise-brief", "approve-budget", "revise-budget"):
        p = sub.add_parser(name)
        p.add_argument("directory", type=Path)
        p.add_argument("request", help="ID shown on the pending review")
        if name == "choose":
            p.add_argument("idea")
            p.add_argument("--pilot-gpu", help="One already authorized local GPU index or UUID")
        if name in {"repropose", "revise-brief", "revise-budget"}:
            p.add_argument("--reason")
    args = ap.parse_args()
    if args.cmd in {"start", "run"}:
        run = new(args.direction, args.dir, args.rounds, args.seconds)
        print(run, flush=True)
    else:
        run = args.directory.resolve()
    if args.cmd in {"run", "resume"}:
        from driver import drive
        drive(run)
    elif args.cmd == "source":
        with lock(run, ".state.lock"):
            require(read(run / "state.json")["phase"] in {"discover", "read"}, "Literature has been frozen")
            print(capture(run, args.id, args.url, args.file))
    elif args.cmd == "advance":
        phase = advance(run)
        print(pending_text(run, snapshot(run)) if phase in WAITING else phase)
    elif args.cmd == "next":
        print(task(run, snapshot(run)))
    elif args.cmd == "status":
        s = snapshot(run)
        if s["grant"]:
            s["usage"] = totals(run, s["grant"]["id"])
        print(json.dumps({k:v for k,v in s.items() if k != "sealed"}, ensure_ascii=False, indent=2))
        if s["phase"] in WAITING:
            print(pending_text(run, s))
    elif args.cmd in {"choose", "repropose", "revise-brief", "approve-budget", "revise-budget"}:
        print(record_reply(run, args.request, args.cmd, getattr(args, "idea", None) or getattr(args, "reason", None),
                           getattr(args, "pilot_gpu", None)))


if __name__ == "__main__":
    try:
        cli()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        sys.exit(str(exc))
