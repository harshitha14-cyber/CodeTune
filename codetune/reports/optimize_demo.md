# CodeTune report: optimize_demo.c

Language: **c**  |  transformations: **17**  |  validation: **all passed**

## Function `demo`

### 1. Pass selection

| Pass | Confidence | Decision | Reason |
|---|---|---|---|
| constant_propagation | 0.95 | run | 5 assignment(s) of a constant value; dry run found 2 concrete site(s) |
| constant_folding | 0.80 | run | constant propagation will expose new constants for this pass |
| strength_reduction | 0.99 | run | 4 multiply/divide/modulo operator(s); dry run found 3 concrete site(s) |
| dead_code_elimination | 0.99 | run | 9 variable(s) and 1 branch(es) that may be unused or constant; dry run found 3 concrete site(s) |

### 2. What changed and why

- **constant_propagation** (3): A variable that always holds the same value was replaced by that value, which exposes further simplifications.
- **constant_folding** (2): An expression made only of constants is computed once at compile time instead of every time the program runs.
- **strength_reduction** (2): An expensive operation (such as multiplication) was replaced by a cheaper equivalent (a shift or an addition).
- **dead_code_elimination** (10): Code that can never run, or whose result is never used, was removed (side effects such as function calls are always kept).

  - line 3: `replaced a with constant 4` (constant_propagation)
  - line 9: `replaced flag with constant 0` (constant_propagation)
  - line 3: `folded (4 * 2) -> 8` (constant_folding)
  - line 3: `folded (8 + 3) -> 11` (constant_folding)
  - line 5: `(n * 8) -> (n << 3)` (strength_reduction)
  - line 6: `(n * 2) -> (n << 1)` (strength_reduction)
  - line 9: `condition 0 is constant -> kept only the else branch` (dead_code_elimination)
  - line 8: `dead store to 'r' removed (value never used)` (dead_code_elimination)
  - line 7: `dead store to 'flag' removed (value never used)` (dead_code_elimination)
  - line 4: `dead store to 'unused' removed (value never used)` (dead_code_elimination)
  - line 2: `dead store to 'a' removed (value never used)` (dead_code_elimination)
  - line 2: `unused declaration of 'a' removed` (dead_code_elimination)
  - line 4: `unused declaration of 'unused' removed` (dead_code_elimination)
  - line 7: `unused declaration of 'flag' removed` (dead_code_elimination)
  - line 12: `replaced b with constant 11` (constant_propagation)
  - line 3: `dead store to 'b' removed (value never used)` (dead_code_elimination)
  - line 3: `unused declaration of 'b' removed` (dead_code_elimination)

### 3. Code comparison

Before:

```
int demo(int n) {
    int a = 4;
    int b = ((a * 2) + 3);
    int unused = (n * 100);
    int c = (n * 8);
    int d = (n * 2);
    int flag = 0;
    int r = 0;
    if (flag) {
        r = 999;
    } else {
        r = (b + c);
    }
    int i = 0;
    while ((i < 3)) {
        r = (r + d);
        i = (i + 1);
    }
    return r;
}
```

After:

```
int demo(int n) {
    int c = (n << 3);
    int d = (n << 1);
    int r;
    r = (11 + c);
    int i = 0;
    while ((i < 3)) {
        r = (r + d);
        i = (i + 1);
    }
    return r;
}
```

### 4. Features and metrics

| Feature | Before | After |
|---|---|---|
| constant_count | 12 | 6 |
| variable_count | 9 | 5 |
| branch_count | 1 | 0 |
| loop_count | 1 | 1 |
| arithmetic_op_count | 8 | 5 |
| mul_div_op_count | 4 | 0 |
| lines of code | 20 | 12 |

### 5. Semantic validation

Result: **PASSED** - 47/47 conclusive differential tests, 0 mismatch(es).
Dynamic cost (operations executed over the tests): 1739 -> 1316 (**24.3% fewer**).
