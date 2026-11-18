"""Save searchable full text for evidence cards; preserve source provenance."""
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

LIMIT = 35 * 1024 * 1024


def normal(text):
    return " ".join(text.split())


def paper_id(text):
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", text):
        raise ValueError("Use a short alphanumeric source or idea ID")
    return text


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.pieces = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"style", "script", "noscript"}:
            self.hidden += 1
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "li", "tr", "br"}:
            self.pieces.append("\n")

    def handle_endtag(self, tag):
        if tag in {"style", "script", "noscript"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.pieces.append(data)


def pdf_text(data, *, manuscript=False):
    try:
        from pypdf import PdfReader
    except ImportError:
        tool = shutil.which("uv") or Path(__file__).resolve().parents[1] / ".tools" / "uv"
        if not Path(tool).is_file():
            raise ValueError("PDF extraction requires pypdf (or uv). An HTML full text also works.")
        proc = subprocess.run([str(tool), "run", "--no-project", "--with", "pypdf==7.1.0",
                               "--python", sys.executable, "python",
                               str(Path(__file__).resolve()), "--manuscript" if manuscript else "--pdf"],
                              input=data, stdout=subprocess.PIPE, check=True, timeout=180)
        return proc.stdout.decode()
    pages = PdfReader(io.BytesIO(data)).pages
    if not manuscript:
        return "\n".join(page.extract_text() or "" for page in pages)
    chunks = []
    def collect(text, cm, tm, font, size):
        # Anonymous templates print line numbers as separate small-font text runs.
        if text.strip() and not (size < 9 and re.fullmatch(r"\d{3,4}", text.strip())):
            chunks.append(text)
    for page in pages:
        page.extract_text(visitor_text=collect)
    return "\n".join(chunks)


def capture(folder, ident, url, local=None):
    paper_id(ident)
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("Provide a primary-source http(s) URL")
    sources = folder / "sources"
    sources.mkdir(exist_ok=True)
    target = sources / ident
    if target.exists():
        meta = json.loads((target / "source.json").read_text())
        if meta["url"] != url:
            raise ValueError(f"Source ID {ident} is already assigned to another URL")
        return target
    if local:
        if local.stat().st_size > LIMIT:
            raise ValueError("Source exceeds 35 MiB")
        data = local.read_bytes()
        effective_url = url
    else:
        request = Request(url, headers={"User-Agent": "AcademicResearchReader/1.0"})
        with urlopen(request, timeout=45) as stream:
            data = stream.read(LIMIT + 1)
            effective_url = stream.geturl()
        if len(data) > LIMIT:
            raise ValueError("Source exceeds 35 MiB")
    if data.lstrip().startswith(b"%PDF-"):
        text = pdf_text(data)
    else:
        decoded = data.decode("utf-8", errors="replace")
        parser = VisibleText()
        parser.feed(decoded)
        text = "".join(parser.pieces)
    text = "\n".join(filter(None, (normal(line) for line in text.splitlines())))
    if len(text) < 500:
        raise ValueError("Little readable text; use the full paper HTML or PDF")
    with tempfile.TemporaryDirectory(dir=sources) as tmp:
        pending = Path(tmp) / ident
        pending.mkdir()
        (pending / "text.txt").write_text(text, encoding="utf-8")
        meta = {"url": url, "resolved_url": effective_url,
                "retrieval": "provided_file" if local else "download",
                "raw_sha256": hashlib.sha256(data).hexdigest(),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
        (pending / "source.json").write_text(json.dumps(meta, indent=2) + "\n")
        pending.rename(target)
    return target


if __name__ == "__main__" and sys.argv[1:] in (["--pdf"], ["--manuscript"]):
    sys.stdout.buffer.write(pdf_text(sys.stdin.buffer.read(), manuscript=sys.argv[1] == "--manuscript").encode())
