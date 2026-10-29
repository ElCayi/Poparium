"""What popOS reproduces of Python itself (textwrap, difflib, random.Random), as
real Python computes it: `python3 tests/python_cases.py [seed] > cases.json`,
then `POPOS_PYCASES=cases.json cargo test -- --ignored`."""
import difflib, json, random, sys, textwrap
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
WORDS = ["hola", "que", "tal", "bien-estar", "auto-cuidado", "no", "x", "palabra--otra", "--", "-", "a-b",
         "acuerdo", "muy-muy-largo-con-guiones", "supercalifragilisticoespialidoso", "¿qué?", "sí,", "ñandú",
         "año-nuevo", "3-4", "e-mail", "x--y", "—", "🐾", "...", "fin.", "'cita'", "\"dos\"", "a_b-c", "-guion", "guion-"]
SEPS = [" ", " ", " ", "  ", "\t", "  ", "\n"]
def text():
    n = rng.randint(0, 14)
    s = "".join(rng.choice(WORDS) + rng.choice(SEPS) for _ in range(n))
    if rng.random() < 0.3: s = " " + s
    if rng.random() < 0.3: s = s.rstrip()
    return s
wrap_cases = []
for _ in range(4000):
    t, w = text(), rng.randint(1, 40)
    wrap_cases.append({"text": t, "width": w, "out": textwrap.wrap(t, width=w, break_long_words=True)})
LINES = ["a", "b", "c", "", "x", "Coordinarnos", "## Contexto", "- item", "--- raya", "+más", "igual"]
def lines():
    return [rng.choice(LINES) for _ in range(rng.randint(0, 12))]
diff_cases = []
for _ in range(3000):
    a, b = lines(), lines()
    if rng.random() < 0.5:  # mostly-similar sequences, the common case
        b = list(a); 
        for _ in range(rng.randint(0, 3)):
            if b and rng.random() < 0.5: b.pop(rng.randrange(len(b)))
            else: b.insert(rng.randint(0, len(b)), rng.choice(LINES))
    diff_cases.append({"a": a, "b": b, "out": list(difflib.unified_diff(a, b, lineterm="", n=1))})
big_a = [str(i % 7) for i in range(450)]
big_b = list(big_a); big_b[100] = "X"; big_b.insert(300, "Y")
diff_cases.append({"a": big_a, "b": big_b, "out": list(difflib.unified_diff(big_a, big_b, lineterm="", n=1))})
rand_cases = []
for seed in [0, 1, 7, 42, 1000047, 2**33 + 5, 12345678901]:
    r = random.Random(seed)
    rand_cases.append({"seed": seed, "out": [r.randrange(1), r.randrange(97), r.randrange(10**6), r.choice((-1, 1)), r.randrange(10)] + [r.randrange(n) for n in range(1, 300)] + [r.randint(5, 25)]})
json.dump({"wrap": wrap_cases, "diff": diff_cases, "random": rand_cases}, sys.stdout, ensure_ascii=False)
