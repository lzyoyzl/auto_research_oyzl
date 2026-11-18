"""Prepare a verified conference author kit and compile its submission source."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parent / "templates"
VENUES = json.loads((TEMPLATES / "venues.json").read_text())


def prepare(venue, target):
    kit = VENUES[venue]
    for name, checksum in kit["files"].items():
        source = TEMPLATES / venue / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Official template changed: {venue}/{name}")
        out = target / name
        if out.exists() and out.read_bytes() != source.read_bytes():
            raise ValueError(f"Won't overwrite edited author-kit file: {out}")
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, out)
    return target / kit["entry"]


def compile_tex(entry, log, *, strict=True):
    folder = entry.parent.resolve()
    local_bin = TEMPLATES.parents[1] / ".tools/tinytex/.TinyTeX/bin/x86_64-linux"
    env = os.environ.copy()
    if (local_bin / "latexmk").is_file():
        env["PATH"] = str(local_bin) + os.pathsep + env.get("PATH", "")
    latexmk = shutil.which("latexmk", path=env.get("PATH"))
    tectonic = shutil.which("tectonic") or TEMPLATES.parents[1] / ".tools" / "tectonic"
    if latexmk:
        cmd = [latexmk, "-g", "-pdf", "-interaction=nonstopmode", "-halt-on-error", entry.name]
    elif Path(tectonic).is_file():
        cmd = [str(tectonic), "--keep-logs", entry.name]
    else:
        raise RuntimeError("Install latexmk + pdfLaTeX or Tectonic, then resume the typeset stage.")
    with log.open("w") as stream:
        run = subprocess.run(cmd, cwd=folder, stdout=stream, stderr=subprocess.STDOUT, timeout=900, env=env)
    pdf = entry.with_suffix(".pdf")
    if run.returncode or not pdf.is_file() or not pdf.read_bytes().startswith(b"%PDF"):
        raise ValueError(f"LaTeX build failed; inspect {log} and correct the manuscript")
    texlog = entry.with_suffix(".log")
    text = texlog.read_text(errors="replace") if texlog.exists() else log.read_text(errors="replace")
    biblog = entry.with_suffix(".blg")
    if biblog.exists():
        text += biblog.read_text(errors="replace")
    if any(s in text for s in ["There were undefined citations", "There were undefined references",
                               "I didn't find a database entry for"]):
        if strict:
            raise ValueError(f"Unresolved citations or references; inspect {log}")
        print(f"Official example built with reference warnings. Details: {log}")
    return pdf


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("venue", choices=VENUES)
    p.add_argument("target", type=Path)
    p.add_argument("--compile", action="store_true")
    args = p.parse_args()
    entry = prepare(args.venue, args.target)
    print(entry)
    if args.compile:
        print(compile_tex(entry, args.target / "build.log", strict=False))
