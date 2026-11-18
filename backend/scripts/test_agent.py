"""Smoke-test the agent turn directly, with raw response inspection."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.agent import AgentService

a = AgentService()
tests = [
    ("That is a first edition, flag it", [], 12, 2),
    ("Skip that shelf, those aren't mine", [], 8, 1),
    ("Is this shelf covered?", [], 15, 3),
    ("", [], 5, 0),  # should be empty
    ("Hello how are you doing today", [], 0, 0),  # off-topic
    ("that painting is a print", ["blur_high"], 20, 5),
]
for t in tests:
    reply = a.turn(*t)
    print(f"IN : {t[0]!r}  notes={t[1]} books={t[2]}")
    print(f"OUT: {reply!r}\n")
