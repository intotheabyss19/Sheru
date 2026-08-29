"""Fast, EXACT local calculator — no LLM, no network. Turns spoken math into an expression and evaluates it
with a safe AST walker (numbers + - * / ** % and a whitelist of functions). Supports continued calculations:
'that / it / the result' and a leading operator ('times 2', 'plus 10') reuse the previous answer.

Returns None when the text isn't confidently math, so the router falls through to normal handling.
"""
from __future__ import annotations

import ast
import math
import operator
import re

_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"sqrt": math.sqrt, "factorial": lambda n: math.factorial(int(n)), "sin": math.sin, "cos": math.cos,
          "tan": math.tan, "log": math.log, "ln": math.log, "log10": math.log10, "abs": abs, "round": round,
          "exp": math.exp, "floor": math.floor, "ceil": math.ceil}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _ev(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp):
        return _OPS[type(node.op)](_ev(node.left), _ev(node.right))
    if isinstance(node, ast.UnaryOp):
        return _OPS[type(node.op)](_ev(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return _FUNCS[node.func.id](*[_ev(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("unsupported")


_WORDS = [
    (r"\bplus\b|\band\b|\badd(?:ed)?\b", "+"),
    (r"\bminus\b|\bsubtract(?:ed)?\b|\bless\b|\btake away\b", "-"),
    (r"\btimes\b|\bmultiplied by\b|\bmultiply(?: by)?\b|\bx\b", "*"),
    (r"\bdivided by\b|\bdivide(?: by)?\b|\bover\b", "/"),
    (r"\bto the power of\b|\braised to(?: the power of)?\b|\bpower\b", "**"),
    (r"\bmod(?:ulo)?\b", "%"),
    (r"\bsquare root of\b|\broot of\b|\bsqrt of\b", "sqrt "),
    (r"\bfactorial of\b", "factorial "),
]


def _to_expr(text: str, last=None) -> str:
    t = " " + text.lower().strip().rstrip("?.! ") + " "
    t = re.sub(r"\b(what'?s|what is|whats|calculate|compute|how much is|the value of|result of|equals?|is|please)\b",
               " ", t)
    if last is not None:                                   # continued calc: 'that/it/the result' -> previous answer
        t = re.sub(r"\b(that|it|this|the (?:result|answer|total|value)|previous(?: (?:result|answer))?)\b",
                   f"({last})", t)
    t = re.sub(r"\badd\s+(\d+(?:\.\d+)?)\s+to\b", r"\1 + ", t)         # 'add 5 to that' -> '5 + that'
    t = re.sub(r"\bsubtract\s+(\d+(?:\.\d+)?)\s+from\b", r"- \1 + 0 +", t)  # 'subtract 5 from that' -> 'that - 5'
    for pat, rep in _WORDS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\bsquared\b", "**2", t)
    t = re.sub(r"\bcubed\b", "**3", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:percent|%)\s+of\s+", r"(\1/100)*", t)   # 15% of 200
    t = re.sub(r"(\d+(?:\.\d+)?)\s*(?:percent|%)", r"(\1/100)", t)
    t = re.sub(r"\b(sqrt|factorial)\s+(\(?-?\d+(?:\.\d+)?\)?)", r"\1(\2)", t)  # sqrt 144 -> sqrt(144)
    t = t.replace("^", "**")
    known = set(_FUNCS) | set(_CONSTS)                     # drop stray words ('the', 'at', 'of'…) that aren't math
    t = re.sub(r"[a-z_]+", lambda m: m.group(0) if m.group(0) in known else " ", t)
    # leading operator with an implied 'that' — 'times 2', 'plus 10'
    ts = t.strip()
    if last is not None and re.match(r"^(\*\*|[+\-*/%])", ts):
        ts = f"({last}) {ts}"
    return ts.strip()


_KNOWN_WORDS = {
    "plus", "and", "add", "added", "minus", "subtract", "subtracted", "less", "take", "away", "times",
    "multiplied", "multiply", "by", "divided", "divide", "over", "to", "the", "power", "of", "raised",
    "mod", "modulo", "square", "root", "sqrt", "factorial", "squared", "cubed", "percent", "that", "it",
    "this", "result", "answer", "total", "value", "previous", "what", "whats", "is", "calculate", "compute",
    "how", "much", "equals", "equal", "please", "a", "an", "x", "pi", "e", "tau", "from", "point",
}


def calc(text: str, last=None):
    """Return the numeric value for a math utterance, or None if it isn't confidently math."""
    noise = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _KNOWN_WORDS]
    if len(noise) > 1:                                     # 'add 2 apples and 3 oranges' -> not a calculation
        return None
    expr = _to_expr(text, last)
    if not re.search(r"\d", expr) or not re.search(r"[+\-*/%]|sqrt|factorial|pi|\be\b", expr):
        return None                                        # needs a number AND an operation — not a bare number
    if not re.fullmatch(r"[\d\s.+\-*/%()a-z_]+", expr):     # only safe characters/identifiers
        return None
    try:
        val = _ev(ast.parse(expr, mode="eval").body)
    except Exception:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return None
    return val


def speak_result(val) -> str:
    if isinstance(val, float) and val.is_integer() and abs(val) < 1e15:
        val = int(val)
    if isinstance(val, int) and abs(val) >= 10 ** 15:      # huge (e.g. factorial) -> scientific, spoken
        m, e = f"{float(val):.4e}".split("e")
        return f"That's about {m} times ten to the power {int(e)}."
    if isinstance(val, float):
        return f"That's {round(val, 6):,}."
    return f"That's {val:,}."
