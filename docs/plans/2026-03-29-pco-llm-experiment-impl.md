# PCO LLM Experiment — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run a real LLM-powered PCO loop that teaches an actor to solve 15 programming puzzles, with a critic that learns to predict pass/fail, over 5 epochs.

**Architecture:** Single test file using the existing PCO framework (ProximalCogletOptimizer, LossCoglet, ConstraintCoglet, LearnerCoglet). Actor/Critic/Learner are coglets that make Claude Sonnet API calls. Results written to `.tests/pco_experiment/`.

**Tech Stack:** Python 3.11+, coglet PCO, anthropic SDK, pytest + pytest-asyncio

---

### Task 1: Puzzle suite and test harness

Define the 15 puzzles and the test runner that executes solutions.

**Files:**
- Create: `tests/test_pco_llm_experiment.py`

**Step 1: Write the puzzle definitions and harness**

```python
"""PCO LLM Experiment: actor learns to solve programming puzzles.

Requires ANTHROPIC_API_KEY env var. Skip if not set.
Results written to .tests/pco_experiment/
"""

import asyncio
import json
import os
import textwrap
import traceback
from pathlib import Path
from typing import Any

import pytest

from coglet import Coglet, CogletConfig, CogletRuntime, enact, listen
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.learner import LearnerCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer

# Skip entire module if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)

RESULTS_DIR = Path(".tests/pco_experiment")

PUZZLES = [
    # ── Easy ───────────────────────────────────────────
    {
        "name": "fizzbuzz",
        "description": "Given int n, return 'FizzBuzz' if divisible by 15, 'Fizz' if by 3, 'Buzz' if by 5, else str(n).",
        "signature": "def fizzbuzz(n: int) -> str:",
        "tests": [(1, "1"), (3, "Fizz"), (5, "Buzz"), (15, "FizzBuzz"), (30, "FizzBuzz"), (7, "7")],
    },
    {
        "name": "is_palindrome",
        "description": "Return True if the string is a palindrome (case-insensitive, ignoring non-alphanumeric chars).",
        "signature": "def is_palindrome(s: str) -> bool:",
        "tests": [("racecar", True), ("hello", False), ("A man a plan a canal Panama", True), ("", True), ("ab", False)],
    },
    {
        "name": "reverse_words",
        "description": "Reverse the order of words in a string. 'hello world' → 'world hello'. Strip extra spaces.",
        "signature": "def reverse_words(s: str) -> str:",
        "tests": [("hello world", "world hello"), ("  the sky is blue  ", "blue is sky the"), ("a", "a"), ("", "")],
    },
    {
        "name": "max_of_list",
        "description": "Return the maximum element in a list of integers. Raise ValueError if list is empty.",
        "signature": "def max_of_list(nums: list[int]) -> int:",
        "tests": [([1, 3, 2], 3), ([-1, -5, -2], -1), ([42], 42), ([0, 0, 0], 0)],
    },
    {
        "name": "factorial",
        "description": "Return n! (n factorial). n is a non-negative integer. 0! = 1.",
        "signature": "def factorial(n: int) -> int:",
        "tests": [(0, 1), (1, 1), (5, 120), (10, 3628800)],
    },
    # ── Medium ─────────────────────────────────────────
    {
        "name": "balanced_parens",
        "description": "Return True if the string has balanced parentheses. Only consider '(' and ')'.",
        "signature": "def balanced_parens(s: str) -> bool:",
        "tests": [("(())", True), ("(()", False), (")(", False), ("", True), ("()()", True), ("((()))", True), ("(()))(", False)],
    },
    {
        "name": "roman_to_int",
        "description": "Convert a roman numeral string to integer. Handle subtractive notation (IV=4, IX=9, XL=40, XC=90, CD=400, CM=900).",
        "signature": "def roman_to_int(s: str) -> int:",
        "tests": [("III", 3), ("IV", 4), ("IX", 9), ("XLII", 42), ("MCMXCIV", 1994), ("XIV", 14)],
    },
    {
        "name": "run_length_encode",
        "description": "Run-length encode a string. 'aaabbc' → '3a2b1c'. Single chars get '1' prefix.",
        "signature": "def run_length_encode(s: str) -> str:",
        "tests": [("aaabbc", "3a2b1c"), ("a", "1a"), ("", ""), ("aaa", "3a"), ("abcd", "1a1b1c1d")],
    },
    {
        "name": "flatten_list",
        "description": "Flatten an arbitrarily nested list. [[1,[2]],3] → [1,2,3].",
        "signature": "def flatten_list(lst: list) -> list:",
        "tests": [([[1, [2]], 3], [1, 2, 3]), ([1, 2, 3], [1, 2, 3]), ([[[[1]]]], [1]), ([], [])],
    },
    {
        "name": "nth_prime",
        "description": "Return the nth prime number (1-indexed). nth_prime(1)=2, nth_prime(2)=3, nth_prime(5)=11.",
        "signature": "def nth_prime(n: int) -> int:",
        "tests": [(1, 2), (2, 3), (3, 5), (5, 11), (10, 29), (20, 71)],
    },
    # ── Hard ───────────────────────────────────────────
    {
        "name": "eval_rpn",
        "description": "Evaluate a reverse Polish notation expression. Tokens are ints or '+','-','*','/'. Division truncates toward zero.",
        "signature": "def eval_rpn(tokens: list[str]) -> int:",
        "tests": [
            (["2", "3", "+"], 5),
            (["4", "13", "5", "/", "+"], 6),
            (["10", "6", "9", "3", "+", "-11", "*", "/", "*", "17", "+", "5", "+"], 22),
        ],
    },
    {
        "name": "longest_common_subseq",
        "description": "Return the length of the longest common subsequence of two strings.",
        "signature": "def longest_common_subseq(s1: str, s2: str) -> int:",
        "tests": [("abcde", "ace", 3), ("abc", "abc", 3), ("abc", "def", 0), ("", "abc", 0), ("abcba", "abcbcba", 5)],
    },
    {
        "name": "spiral_matrix",
        "description": "Given an NxN matrix (list of lists), return elements in spiral order (clockwise from top-left).",
        "signature": "def spiral_matrix(matrix: list[list[int]]) -> list[int]:",
        "tests": [
            ([[1, 2, 3], [4, 5, 6], [7, 8, 9]], [1, 2, 3, 6, 9, 8, 7, 4, 5]),
            ([[1]], [1]),
            ([[1, 2], [3, 4]], [1, 2, 4, 3]),
        ],
    },
    {
        "name": "merge_intervals",
        "description": "Merge overlapping intervals. Input: list of [start, end] pairs sorted by start. Return merged list.",
        "signature": "def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:",
        "tests": [
            ([[1, 3], [2, 6], [8, 10], [15, 18]], [[1, 6], [8, 10], [15, 18]]),
            ([[1, 4], [4, 5]], [[1, 5]]),
            ([[1, 2]], [[1, 2]]),
            ([], []),
        ],
    },
    {
        "name": "valid_sudoku",
        "description": "Validate a 9x9 Sudoku board. Board is list of 9 strings, each 9 chars. '.' means empty. Return True if valid (no duplicates in rows, cols, 3x3 boxes). Board doesn't need to be solvable.",
        "signature": "def valid_sudoku(board: list[str]) -> bool:",
        "tests": [
            ([
                "53..7....",
                "6..195...",
                ".98....6.",
                "8...6...3",
                "4..8.3..1",
                "7...2...6",
                ".6....28.",
                "...419..5",
                "....8..79",
            ], True),
            ([
                "83..7....",
                "6..195...",
                ".98....6.",
                "8...6...3",
                "4..8.3..1",
                "7...2...6",
                ".6....28.",
                "...419..5",
                "....8..79",
            ], False),  # duplicate 8 in col 0
        ],
    },
]


def run_solution(puzzle: dict, code: str) -> dict:
    """Execute a solution against test cases. Returns result dict."""
    namespace: dict[str, Any] = {}
    try:
        exec(code, namespace)
    except Exception as e:
        return {
            "name": puzzle["name"],
            "passed": False,
            "total_tests": len(puzzle["tests"]),
            "passed_tests": 0,
            "error": f"compile error: {e}",
        }

    fn_name = puzzle["signature"].split("(")[0].replace("def ", "").strip()
    fn = namespace.get(fn_name)
    if fn is None:
        return {
            "name": puzzle["name"],
            "passed": False,
            "total_tests": len(puzzle["tests"]),
            "passed_tests": 0,
            "error": f"function {fn_name} not found in code",
        }

    passed_tests = 0
    first_error = None
    for test_input, expected in puzzle["tests"]:
        try:
            if isinstance(test_input, tuple):
                result = fn(*test_input)
            else:
                result = fn(test_input)
            if result == expected:
                passed_tests += 1
            elif first_error is None:
                first_error = f"input={test_input!r}: got {result!r}, expected {expected!r}"
        except Exception as e:
            if first_error is None:
                first_error = f"input={test_input!r}: raised {type(e).__name__}: {e}"

    return {
        "name": puzzle["name"],
        "passed": passed_tests == len(puzzle["tests"]),
        "total_tests": len(puzzle["tests"]),
        "passed_tests": passed_tests,
        "error": first_error,
    }
```

**Step 2: Write a quick sanity test for the harness**

```python
def test_harness_runs_correct_solution():
    """Verify run_solution works with a known-good solution."""
    puzzle = PUZZLES[0]  # fizzbuzz
    code = textwrap.dedent("""\
        def fizzbuzz(n):
            if n % 15 == 0: return "FizzBuzz"
            if n % 3 == 0: return "Fizz"
            if n % 5 == 0: return "Buzz"
            return str(n)
    """)
    result = run_solution(puzzle, code)
    assert result["passed"] is True
    assert result["passed_tests"] == len(puzzle["tests"])


def test_harness_catches_bad_solution():
    """Verify run_solution catches errors."""
    puzzle = PUZZLES[0]
    result = run_solution(puzzle, "def fizzbuzz(n): return str(n)")
    assert result["passed"] is False
    assert result["error"] is not None
```

**Step 3: Run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_pco_llm_experiment.py::test_harness_runs_correct_solution tests/test_pco_llm_experiment.py::test_harness_catches_bad_solution -v`
Expected: PASS (these don't need API key)

**Step 4: Commit**

```bash
git add tests/test_pco_llm_experiment.py .gitignore
git commit -m "feat: puzzle suite and test harness for PCO LLM experiment"
```

---

### Task 2: LLM helper and Actor coglet

Create the Anthropic client helper and the CodeGenActor.

**Files:**
- Modify: `tests/test_pco_llm_experiment.py`

**Step 1: Add LLM helper and actor**

```python
import anthropic


def llm_call(prompt: str, *, system: str = "", max_tokens: int = 4096) -> str:
    """Single Claude Sonnet call. Returns text response."""
    client = anthropic.Anthropic()
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = dict(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=messages,
    )
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return response.content[0].text


def extract_json(text: str) -> Any:
    """Extract JSON from LLM response, handling markdown code blocks."""
    # Try direct parse first
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


class CodeGenActor(Coglet):
    """Actor that holds Python solutions to puzzles.

    enact("run"): execute solutions against tests, transmit experience.
    enact("update"): replace solutions from learner patch.
    """

    def __init__(self, *, puzzles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.puzzles = puzzles
        self.solutions: dict[str, str] = {}
        self._initialized = False

    @enact("run")
    async def run_rollout(self, data):
        if not self._initialized:
            self._initialize_solutions()
            self._initialized = True

        results = []
        for puzzle in self.puzzles:
            code = self.solutions.get(puzzle["name"], "")
            result = run_solution(puzzle, code)
            result["code"] = code
            results.append(result)

        await self.transmit("experience", {"results": results})

    def _initialize_solutions(self):
        """Generate initial solutions via one LLM call."""
        puzzle_specs = []
        for p in self.puzzles:
            puzzle_specs.append(f"### {p['name']}\n{p['description']}\n```python\n{p['signature']}\n```")

        prompt = (
            "Write a Python solution for each puzzle below. "
            "Return a JSON object mapping puzzle name to the complete Python function code (as a string). "
            "Each value must be a complete, standalone Python function. "
            "Return ONLY the JSON object, no other text.\n\n"
            + "\n\n".join(puzzle_specs)
        )

        response = llm_call(prompt, system="You are an expert Python programmer.")
        self.solutions = extract_json(response)

    @enact("update")
    async def apply_update(self, patch):
        new_solutions = patch.get("solutions", {})
        self.solutions.update(new_solutions)
```

**Step 2: Add a test that creates actor and runs one rollout (requires API key)**

```python
@pytest.mark.asyncio
async def test_actor_generates_and_runs():
    """Actor generates solutions and runs them. Some should pass."""
    runtime = CogletRuntime()
    handle = await runtime.spawn(CogletConfig(
        cls=CodeGenActor, kwargs=dict(puzzles=PUZZLES[:3]),  # just easy ones
    ))
    actor = handle.coglet

    results = []
    async def collect():
        async for exp in handle.observe("experience"):
            results.append(exp)
            break

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.01)
    await actor._dispatch_enact(type("Cmd", (), {"type": "run", "data": None})())
    await asyncio.wait_for(task, timeout=60.0)

    assert len(results[0]["results"]) == 3
    # At least 1 easy puzzle should pass on first try
    passed = sum(1 for r in results[0]["results"] if r["passed"])
    print(f"Actor initial pass rate (easy): {passed}/3")
    await runtime.shutdown()
```

**Step 3: Run (only if API key set)**

Run: `ANTHROPIC_API_KEY=... PYTHONPATH=src python -m pytest tests/test_pco_llm_experiment.py::test_actor_generates_and_runs -v -s`
Expected: PASS, prints pass rate

**Step 4: Commit**

```bash
git add tests/test_pco_llm_experiment.py
git commit -m "feat: CodeGenActor with LLM-generated solutions"
```

---

### Task 3: Critic coglet

**Files:**
- Modify: `tests/test_pco_llm_experiment.py`

**Step 1: Add critic**

```python
class CodeReviewCritic(Coglet):
    """Critic that predicts pass/fail for each solution."""

    def __init__(self, *, puzzles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.puzzles = puzzles
        self.strategy = "Look for common bugs: off-by-one errors, missing edge cases, wrong return types."

    @listen("experience")
    async def evaluate(self, experience):
        results = experience["results"]

        # Build prompt: show solutions, ask for predictions
        solution_texts = []
        for r in results:
            solution_texts.append(f"### {r['name']}\n```python\n{r['code']}\n```")

        prompt = (
            f"Your evaluation strategy: {self.strategy}\n\n"
            "For each solution below, predict whether it will PASS or FAIL all test cases. "
            "Return a JSON object mapping puzzle name to 'pass' or 'fail'. "
            "Return ONLY the JSON object.\n\n"
            + "\n\n".join(solution_texts)
        )

        response = llm_call(prompt, system="You are a code reviewer predicting test outcomes.")
        try:
            predictions = extract_json(response)
        except (json.JSONDecodeError, ValueError):
            predictions = {}

        # Compare predictions to actuals
        evaluation = []
        for r in results:
            predicted = predictions.get(r["name"], "fail").lower()
            actual = "pass" if r["passed"] else "fail"
            evaluation.append({
                "name": r["name"],
                "predicted": predicted,
                "actual": actual,
                "correct": predicted == actual,
                "code": r["code"],
                "error": r.get("error"),
            })

        await self.transmit("evaluation", {"predictions": evaluation})

    @enact("update")
    async def apply_update(self, patch):
        new_strategy = patch.get("critic_strategy")
        if new_strategy:
            self.strategy = new_strategy
```

**Step 2: Commit**

```bash
git add tests/test_pco_llm_experiment.py
git commit -m "feat: CodeReviewCritic with LLM predictions"
```

---

### Task 4: Losses, constraint, and learner

**Files:**
- Modify: `tests/test_pco_llm_experiment.py`

**Step 1: Add losses**

```python
class ActorLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        results = experience["results"]
        failed = [r for r in results if not r["passed"]]
        return {
            "name": "actor_loss",
            "magnitude": len(failed),
            "total": len(results),
            "failed_puzzles": [{"name": r["name"], "error": r.get("error"), "code": r["code"]} for r in failed],
        }


class CriticLoss(LossCoglet):
    async def compute_loss(self, experience, evaluation):
        preds = evaluation["predictions"]
        wrong = [p for p in preds if not p["correct"]]
        return {
            "name": "critic_loss",
            "magnitude": len(wrong),
            "total": len(preds),
            "wrong_predictions": wrong,
        }
```

**Step 2: Add constraint**

```python
class MaxRewritesConstraint(ConstraintCoglet):
    """Reject if learner rewrites more than 5 solutions at once."""
    async def check(self, patch):
        n = len(patch.get("solutions", {}))
        if n > 5:
            return {"accepted": False, "reason": f"too many rewrites: {n} (max 5)"}
        return {"accepted": True}
```

**Step 3: Add learner**

```python
class CodeGenLearner(LearnerCoglet):
    """Learner that rewrites failing solutions and updates critic strategy."""

    async def learn(self, experience, evaluation, signals):
        # Gather failing puzzles from actor loss signal
        actor_signal = next((s for s in signals if s.get("name") == "actor_loss"), None)
        critic_signal = next((s for s in signals if s.get("name") == "critic_loss"), None)

        new_solutions = {}
        new_critic_strategy = None

        # Fix failing solutions (max 5)
        if actor_signal and actor_signal.get("failed_puzzles"):
            failed = actor_signal["failed_puzzles"][:5]
            puzzle_map = {p["name"]: p for p in PUZZLES}

            fix_parts = []
            for f in failed:
                puzzle = puzzle_map.get(f["name"], {})
                fix_parts.append(
                    f"### {f['name']}\n"
                    f"Description: {puzzle.get('description', 'N/A')}\n"
                    f"Signature: {puzzle.get('signature', 'N/A')}\n"
                    f"Current code:\n```python\n{f['code']}\n```\n"
                    f"Error: {f['error']}"
                )

            prompt = (
                "Fix these failing Python solutions. For each, return the corrected complete function. "
                "Return a JSON object mapping puzzle name to the fixed Python code string. "
                "Return ONLY the JSON object.\n\n"
                + "\n\n".join(fix_parts)
            )

            response = llm_call(prompt, system="You are an expert Python programmer fixing bugs.")
            try:
                new_solutions = extract_json(response)
            except (json.JSONDecodeError, ValueError):
                pass

        # Update critic strategy
        if critic_signal and critic_signal.get("wrong_predictions"):
            wrong = critic_signal["wrong_predictions"]
            wrong_parts = []
            for w in wrong:
                wrong_parts.append(
                    f"- {w['name']}: predicted {w['predicted']}, actually {w['actual']}"
                    + (f" (error: {w['error']})" if w.get("error") else "")
                )

            prompt = (
                "You are a code review critic. Your predictions were wrong for these puzzles:\n"
                + "\n".join(wrong_parts)
                + "\n\nWrite an improved evaluation strategy (1-3 sentences) that would help you "
                "predict more accurately next time. Focus on specific patterns you missed."
                "\n\nReturn ONLY the strategy text, no JSON or markdown."
            )

            new_critic_strategy = llm_call(prompt, max_tokens=200)

        return {
            "solutions": new_solutions,
            "critic_strategy": new_critic_strategy,
        }
```

**Step 4: Commit**

```bash
git add tests/test_pco_llm_experiment.py
git commit -m "feat: losses, constraint, and LLM learner for PCO experiment"
```

---

### Task 5: Full experiment runner

**Files:**
- Modify: `tests/test_pco_llm_experiment.py`

**Step 1: Add the main experiment test**

```python
@pytest.mark.asyncio
async def test_pco_llm_experiment():
    """Full PCO experiment: 5 epochs of LLM-driven code improvement."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    runtime = CogletRuntime()
    pco_handle = await runtime.spawn(CogletConfig(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogletConfig(cls=CodeGenActor, kwargs=dict(puzzles=PUZZLES)),
            critic_config=CogletConfig(cls=CodeReviewCritic, kwargs=dict(puzzles=PUZZLES)),
            losses=[ActorLoss(), CriticLoss()],
            constraints=[MaxRewritesConstraint()],
            learner=CodeGenLearner(),
            max_retries=2,
        ),
    ))
    pco = pco_handle.coglet

    num_epochs = 5
    metrics = []

    for epoch in range(num_epochs):
        result = await pco.run_epoch(timeout=120.0)

        # Extract metrics
        actor_signal = next((s for s in result["signals"] if s["name"] == "actor_loss"), {})
        critic_signal = next((s for s in result["signals"] if s["name"] == "critic_loss"), {})

        total = actor_signal.get("total", 15)
        actor_pass = total - actor_signal.get("magnitude", 0)
        critic_correct = total - critic_signal.get("magnitude", 0)

        epoch_metrics = {
            "epoch": epoch + 1,
            "actor_pass_rate": actor_pass / total,
            "actor_passed": actor_pass,
            "critic_accuracy": critic_correct / total,
            "critic_correct": critic_correct,
            "total": total,
            "accepted": result["accepted"],
        }
        metrics.append(epoch_metrics)

        # Print table row
        print(
            f"  Epoch {epoch + 1}: "
            f"actor={actor_pass}/{total} ({epoch_metrics['actor_pass_rate']:.0%})  "
            f"critic={critic_correct}/{total} ({epoch_metrics['critic_accuracy']:.0%})  "
            f"accepted={result['accepted']}"
        )

    # Write results
    (RESULTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # Save final solutions
    actor = pco._actor_handle.coglet
    (RESULTS_DIR / "final_solutions.json").write_text(
        json.dumps(actor.solutions, indent=2)
    )

    # Save final critic strategy
    critic = pco._critic_handle.coglet
    (RESULTS_DIR / "final_critic_strategy.txt").write_text(critic.strategy)

    await runtime.shutdown()

    # ── Assertions ─────────────────────────────────────
    first = metrics[0]
    last = metrics[-1]

    print(f"\n  Improvement: actor {first['actor_pass_rate']:.0%} → {last['actor_pass_rate']:.0%}")
    print(f"  Improvement: critic {first['critic_accuracy']:.0%} → {last['critic_accuracy']:.0%}")

    assert last["actor_pass_rate"] > first["actor_pass_rate"], \
        f"Actor should improve: {first['actor_pass_rate']:.0%} → {last['actor_pass_rate']:.0%}"
    assert last["actor_pass_rate"] >= 10 / 15, \
        f"Actor should solve at least 10/15: got {last['actor_passed']}/15"
```

**Step 2: Run the full experiment**

Run: `ANTHROPIC_API_KEY=... PYTHONPATH=src python -m pytest tests/test_pco_llm_experiment.py::test_pco_llm_experiment -v -s --timeout=600`
Expected: PASS, prints epoch table, writes results to `.tests/pco_experiment/`

**Step 3: Commit**

```bash
git add tests/test_pco_llm_experiment.py docs/plans/2026-03-29-pco-llm-experiment-impl.md docs/plans/2026-03-29-pco-llm-experiment.md
git commit -m "feat: full PCO LLM experiment — 15 puzzles, 5 epochs"
```
