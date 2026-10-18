"""Edith's instant library: small talk, Echo VR / Lone Echo knowledge and in-game reactions,
answered without the model (ai/library/*.json, edited freely; reloaded at start).

    from library import Library
    lib = Library()
    lib.smalltalk("hey edith")            -> ("hello", "Hey {name}!") or None
    lib.answer("how do i win the joust")  -> (score, entry id, answer) or None
    lib.snippets("tell me about combat")  -> the best entries' answers, for the model's prompt
    lib.reaction("bumped", count_today)   -> a line or None (cooldown)
"""
from __future__ import annotations

import json
import math
import random
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent / "library"
STOP = set("""a an the is are was were be been am i you he she it we they me my your our their this that
these those to of in on at for with and or but do does did can could would should will shall what whats
who whos how hows when where why which there here please tell about know any some so just really very
cubie edith hey hi yo okay ok like give get got have has had its it's im i'm youre you're""".split())


def norm(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = re.sub(r"\b(two|ii)\b", "2", t)                     # Lone Echo II = two = 2
    return re.sub(r"\s+", " ", t).strip()


def words(text: str) -> list[str]:
    return [w.strip("'") for w in norm(text).split() if w.strip("'")]


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def terms(text: str) -> list[str]:
    return [stem(w) for w in words(text) if w not in STOP]


class Library:
    def __init__(self, folder: Path = HERE):
        self.folder = folder
        k = json.loads((folder / "knowledge.json").read_text(encoding="utf-8"))
        s = json.loads((folder / "smalltalk.json").read_text(encoding="utf-8"))
        r = json.loads((folder / "reactions.json").read_text(encoding="utf-8"))
        self.entries = k["entries"]
        self.intents = [(i["id"], [re.compile(p) for p in i["patterns"]], i["replies"]) for i in s["intents"]]
        self.reactions = r["events"]
        self.dizzy = {int(k): v for k, v in r.get("dizzy", {}).items()}   # seconds spun -> lines
        self.moods = {k: v for k, v in r.items() if isinstance(v, list)}   # stopped spinning, angry push, ...
        self.cooldown = float(r.get("cooldown_s", 3))
        self.last_reaction = 0.0
        self.last_line: dict[str, str] = {}
        self.exact = None
        # a small search index: per entry, weighted terms from its keys (x3), questions and answers
        self.index = []
        df: dict[str, int] = {}
        for e in self.entries:
            tf: dict[str, float] = {}
            for key in e.get("keys", []):
                for t in terms(key):
                    tf[t] = tf.get(t, 0) + 3.0
            for q in e.get("q", []):
                for t in terms(q):
                    tf[t] = tf.get(t, 0) + 1.5
            for a in e.get("a", []):
                for t in set(terms(a)):
                    tf[t] = tf.get(t, 0) + 0.3
            phrases = [norm(x) for x in e.get("keys", []) + e.get("q", [])]
            self.index.append((e, tf, phrases))
            for t in tf:
                df[t] = df.get(t, 0) + 1
        n = max(1, len(self.entries))
        self.idf = {t: math.log(1 + n / c) for t, c in df.items()}
        # the chat bank: example phrasings -> replies (optionally an order), matched loosely
        self.chats = []
        cf = folder / "chat.json"
        if cf.exists():
            for e in json.loads(cf.read_text(encoding="utf-8"))["entries"]:
                qs = [self._chat_norm(q) for q in e["q"]]
                self.chats.append((e, [(q, set(words(q)), set(terms(q))) for q in qs if q]))

    # -- picking lines -------------------------------------------------------------------------
    def pick(self, key: str, lines: list[str]) -> str:
        """A random line, never the same as the last one for this key."""
        if len(lines) > 1:
            lines = [l for l in lines if l != self.last_line.get(key)] or lines
        line = random.choice(lines)
        self.last_line[key] = line
        return line

    def all_lines(self, knowledge: bool = True) -> list[str]:
        """Every stock line (for pre-voicing). Lines with {name} etc. are filled in later."""
        out = []
        for _, _, replies in self.intents:
            out += replies
        for ev in self.reactions.values():
            for lines in ev.values():
                out += lines
        for lines in list(self.dizzy.values()) + list(self.moods.values()):
            out += lines
        for e, _ in self.chats:
            out += e["a"]
        if knowledge:
            for e in self.entries:
                out += e.get("a", [])
        return out

    # -- the chat bank -------------------------------------------------------------------------
    @staticmethod
    def _chat_norm(text: str) -> str:
        t = norm(text)
        t = re.sub(r"^((hey|oi|yo|um|uh|so|okay|ok|well|and|but)\s+)+", "", t)
        t = re.sub(r"^((cubie|edith)\s+)+|\s+(cubie|edith)$", "", t)
        t = re.sub(r"\s+(please|buddy|mate|bro|dude)$", "", t)
        # fillers that only dilute the match ("im really sad today" -> "im sad")
        t = re.sub(r"\b(really|so|very|super|just|actually|kinda|kind of|literally|honestly|today|right now|"
                   r"at the moment|tonight|like)\b", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    def examples(self, phrasings: list[str]) -> list[tuple[str, set, set]]:
        qs = [self._chat_norm(q) for q in phrasings]
        return [(q, set(words(q)), set(terms(q))) for q in qs if q]

    def learn(self, learned: list[dict]):
        """What the player taught her (memory.json "learned": {id, q, a}), matched like the chat bank."""
        self.learned = [(e, self.examples(e["q"])) for e in learned]

    def taught(self, text: str, threshold: float = 0.68) -> tuple[float, str, str, str] | None:
        """A taught answer for what was heard (checked before her own lines: yours win)."""
        return self.chat(text, threshold, 0.0, getattr(self, "learned", []))

    def chat(self, text: str, threshold: float = 0.67, margin: float = 0.03, pool=None) -> tuple[float, str, str, str] | None:
        """The chat bank's best entry for what was heard -> (score, id, reply, order or ""), or None.
        Score per example: 0.55 x character similarity (survives mishearing) + 0.45 x word overlap,
        plus 0.1 when every content word of the example was said; the entry must clear `threshold`
        and beat the next entry by `margin` (or score 0.85+)."""
        from difflib import SequenceMatcher
        t = self._chat_norm(text)
        if not t or len(t.split()) > 14:
            return None
        tw, tt = set(words(t)), set(terms(t))
        scored = []
        for e, examples in (self.chats if pool is None else pool):
            best = 0.0
            for q, qw, qt in examples:
                r = SequenceMatcher(None, t, q).ratio()
                j = len(tw & qw) / max(1, len(tw | qw))
                s = 0.55 * r + 0.45 * j + (0.1 if qt and qt <= tt else 0.0)
                best = max(best, s)
            scored.append((best, e))
        if not scored:
            return None
        scored.sort(key=lambda x: -x[0])
        best, e = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best < threshold or (best - second < margin and best < 0.85):
            return None
        return best, e["id"], self.pick("chat/" + e["id"], e["a"]), e.get("do", "")

    # -- small talk ----------------------------------------------------------------------------
    def smalltalk(self, text: str) -> tuple[str, str] | None:
        t = norm(text)
        t = re.sub(r"^(cubie|edith|hey cubie|hey edith|oi|um|uh|so)\s+", "", t).strip()
        t = re.sub(r"\s+(cubie|edith|please|buddy)$", "", t).strip()
        if not t or len(t.split()) > 9:
            return None
        for iid, pats, replies in self.intents:
            if any(p.search(t) for p in pats):
                return iid, self.pick(iid, replies)
        return None

    # -- knowledge -----------------------------------------------------------------------------
    def score(self, text: str) -> list[tuple[float, dict]]:
        q = terms(text)
        nq = norm(text)
        if not q:
            return []
        out = []
        self.exact = None
        for e, tf, phrases in self.index:
            s = sum(tf.get(t, 0) * self.idf.get(t, 0) for t in set(q))
            for ph in phrases:                                   # whole key phrases / questions
                if ph and len(ph) > 3 and ph in nq:
                    s += 6.0 + 2.0 * len(ph.split())
            if nq in [norm(x) for x in e.get("q", [])]:
                self.exact = e["id"]                             # asked word for word
                s += 20.0
            if s > 0:
                out.append((s / (1.0 + 0.15 * len(q)), e))
        out.sort(key=lambda x: -x[0])
        return out

    def answer(self, text: str, threshold: float = 9.0) -> tuple[float, str, str] | None:
        """An instant answer when one entry clearly matches the question."""
        ranked = self.score(text)
        if not ranked:
            return None
        best, e = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        if best < threshold or (best < second * 1.15 and self.exact != e["id"]):
            return None
        return best, e["id"], self.pick(e["id"], e["a"])

    def snippets(self, text: str, k: int = 2) -> list[str]:
        """The best entries for the model's prompt (only ones that really match: every line
        in the prompt costs time on the CPU)."""
        return [e["a"][0] for s, e in self.score(text)[:k] if s > 8.0]

    # -- reactions -----------------------------------------------------------------------------
    def reaction(self, event: str, count_today: int) -> str | None:
        ev = self.reactions.get(event)
        if not ev:
            return None
        now = time.time()
        if now - self.last_reaction < self.cooldown:
            return None
        self.last_reaction = now
        tier = "first" if count_today <= 1 else "again" if count_today <= 5 else "lots"
        return self.pick(f"{event}/{tier}", ev.get(tier) or ev["first"])

    def dizzy_line(self, seconds: int) -> str | None:
        """A line for an endless spin / flip that has gone on this long."""
        if not self.dizzy:
            return None
        tier = max(t for t in self.dizzy if t <= seconds) if any(t <= seconds for t in self.dizzy) else min(self.dizzy)
        return self.pick(f"dizzy/{tier}", self.dizzy[tier])

    def mood(self, key: str) -> str | None:
        """A line from a top-level list (stopped spinning, angry push, asked shutdown, ...)."""
        lines = self.moods.get(key)
        return self.pick(key, lines) if lines else None


if __name__ == "__main__":                                      # quick check: python ai/library.py "question"
    import sys
    lib = Library()
    for q in sys.argv[1:] or ["hi", "how are you", "what is a joust", "who is jack", "what weapons are in combat",
                              "when did echo vr shut down", "tell me a joke", "how do i go faster", "what is lone echo 2"]:
        st = lib.smalltalk(q)
        an = lib.answer(q)
        ch = lib.chat(q)
        print(f"{q!r}: smalltalk={st} answer={an and (round(an[0], 1), an[1])} chat={ch and (round(ch[0], 2), ch[1], ch[3])} "
              f"top={[(round(s, 1), e['id']) for s, e in lib.score(q)[:3]]}")
