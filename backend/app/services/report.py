"""Jinja2 HTML report built from the claim packet. No LLM involvement."""
from __future__ import annotations
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..models.schema import ClaimPacket

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_report(packet: ClaimPacket) -> str:
    env = _env()
    tpl = env.get_template("report.html.j2")
    return tpl.render(packet=packet)
