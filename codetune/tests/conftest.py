"""
Shared pytest setup.

The tests must not depend on files you might edit (samples/ is meant to be played with),
so the pristine sample programs are embedded here and written to tests/data/ before any
test module is imported. Edit samples/ freely - the tests always use tests/data/.
"""

import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

PRISTINE_SAMPLES = {
    "optimize_demo.c": """int demo(int n) {
    int a = 4;
    int b = a * 2 + 3;
    int unused = n * 100;
    int c = n * 8;
    int d = n * 2;
    int flag = 0;
    int r = 0;
    if (flag) {
        r = 999;
    } else {
        r = b + c;
    }
    int i = 0;
    while (i < 3) {
        r = r + d;
        i = i + 1;
    }
    return r;
}
""",
    "optimize_demo.py": """def demo(n):
    a = 4
    b = a * 2 + 3
    unused = n * 100
    c = n * 8
    d = n * 2
    flag = 0
    r = 0
    if flag:
        r = 999
    else:
        r = b + c
    i = 0
    while i < 3:
        r = r + d
        i = i + 1
    return r
""",
    "optimize_demo.java": """class OptimizeDemo {
    int demo(int n) {
        int a = 4;
        int b = a * 2 + 3;
        int unused = n * 100;
        int c = n * 8;
        int d = n * 2;
        int flag = 0;
        int r = 0;
        if (flag != 0) {
            r = 999;
        } else {
            r = b + c;
        }
        int i = 0;
        while (i < 3) {
            r = r + d;
            i = i + 1;
        }
        return r;
    }
}
""",
    "twin_demo.c": """int work(int n) {
    int scale = 8;
    int offset = 2 * 3 + 1;
    int total = 0;
    int i = 0;
    while (i < 10) {
        total = total + i * scale;
        i = i + 1;
    }
    if (n > 0) {
        total = total + n * scale + offset;
    } else {
        total = total - offset;
    }
    int waste = total * 100;
    return total;
}
""",
    "twin_demo.py": """def work(n):
    scale = 8
    offset = 2 * 3 + 1
    total = 0
    i = 0
    while i < 10:
        total = total + i * scale
        i = i + 1
    if n > 0:
        total = total + n * scale + offset
    else:
        total = total - offset
    waste = total * 100
    return total
""",
    "twin_demo.java": """class TwinDemo {
    int work(int n) {
        int scale = 8;
        int offset = 2 * 3 + 1;
        int total = 0;
        int i = 0;
        while (i < 10) {
            total = total + i * scale;
            i = i + 1;
        }
        if (n > 0) {
            total = total + n * scale + offset;
        } else {
            total = total - offset;
        }
        int waste = total * 100;
        return total;
    }
}
""",
}
# the C++ samples are identical to the C ones
PRISTINE_SAMPLES["optimize_demo.cpp"] = PRISTINE_SAMPLES["optimize_demo.c"]
PRISTINE_SAMPLES["twin_demo.cpp"] = PRISTINE_SAMPLES["twin_demo.c"]


def _write_pristine_samples():
    os.makedirs(DATA_DIR, exist_ok=True)
    for name, text in PRISTINE_SAMPLES.items():
        path = os.path.join(DATA_DIR, name)
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                if fh.read() == text:
                    continue
        except OSError:
            pass
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)


_write_pristine_samples()