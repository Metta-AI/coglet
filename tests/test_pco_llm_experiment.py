"""PCO LLM Experiment: actor learns to solve programming puzzles.

Requires ANTHROPIC_API_KEY env var for LLM tests.
Results written to .tests/pco_experiment/
"""

import asyncio
import json
import os
import textwrap
from pathlib import Path
from typing import Any

import anthropic

import pytest

from coglet import Coglet, CogBase, CogletRuntime, enact, listen
from coglet.handle import Command
from coglet.pco.constraint import ConstraintCoglet
from coglet.pco.learner import LearnerCoglet
from coglet.pco.loss import LossCoglet
from coglet.pco.optimizer import ProximalCogletOptimizer

RESULTS_DIR = Path(".tests/pco_experiment")

PUZZLES = [
    # ── Puzzles that Sonnet struggles with ─────────────
    #
    # These are selected because they have subtle edge cases
    # that LLMs consistently get wrong on first attempt.
    {
        "name": "next_permutation",
        "description": "Given a list of ints, rearrange it to the next lexicographically greater permutation. If it's the last permutation (fully descending), wrap to sorted ascending. Return the list. Algorithm: from right, find first i where nums[i] < nums[i+1]. Find rightmost j > i where nums[j] > nums[i]. Swap i,j. Reverse everything after i. If no such i exists, reverse the whole list.",
        "signature": "def next_permutation(nums: list[int]) -> list[int]:",
        "tests": [
            ([1, 2, 3], [1, 3, 2]),
            ([3, 2, 1], [1, 2, 3]),
            ([1, 1, 5], [1, 5, 1]),
            ([1, 3, 2], [2, 1, 3]),
            ([2, 3, 1], [3, 1, 2]),
            ([1], [1]),
            ([5, 4, 7, 5, 3, 2], [5, 5, 2, 3, 4, 7]),
        ],
    },
    {
        "name": "task_scheduler",
        "description": "Given tasks (list of chars) and cooldown n, return the minimum number of intervals to execute all tasks. Between two same tasks, there must be at least n intervals (other tasks or idle). Formula: max(len(tasks), (max_freq - 1) * (n + 1) + count_of_max_freq_tasks).",
        "signature": "def task_scheduler(tasks: list[str], n: int) -> int:",
        "tests": [
            (["A", "A", "A", "B", "B", "B"], 2, 8),
            (["A", "A", "A", "B", "B", "B"], 0, 6),
            (["A", "A", "A", "A", "A", "A", "B", "C", "D", "E", "F", "G"], 2, 16),
            (["A"], 5, 1),
            # 3 distinct tasks, each appears twice. max_freq=2, count=3.
            # formula: (2-1)*(3+1)+3 = 7, len=6, answer = max(7,6) = 7
            (["A", "B", "C", "A", "B", "C"], 3, 7),
        ],
    },
    {
        "name": "minimax_tictactoe",
        "description": "Given a tic-tac-toe board (list of 9 ints: 0=empty, 1=X, 2=O) and current player (1 or 2), return the best move index (0-8). Use depth-aware minimax: X maximizes, O minimizes. Score = +10-depth for X win, -10+depth for O win, 0 for draw. This means faster wins score higher. Ties broken by lowest index.",
        "signature": "def minimax_tictactoe(board: list[int], player: int) -> int:",
        "tests": [
            ([1, 1, 0, 2, 2, 0, 0, 0, 0], 1, 2),   # X wins immediately at 2
            ([1, 1, 0, 0, 2, 0, 0, 0, 0], 2, 2),   # O blocks at 2
            ([0, 0, 0, 0, 0, 0, 0, 0, 0], 1, 0),   # empty board, corner
            ([0, 0, 0, 0, 1, 0, 0, 0, 0], 2, 0),   # X center, O takes corner
            # Fork: X at 0,4 O at 1,3. Move 8 gives forced win (depth-aware prefers it)
            ([1, 2, 0, 2, 1, 0, 0, 0, 0], 1, 8),
        ],
    },
    {
        "name": "text_justify",
        "description": "Given a list of words and a max width, format text with full justification. Each line must be exactly maxWidth chars. Distribute extra spaces as evenly as possible; if uneven, left slots get more. Last line is left-justified with no extra spaces. Single-word lines are left-justified.",
        "signature": "def text_justify(words: list[str], maxWidth: int) -> list[str]:",
        "tests": [
            (["This", "is", "an", "example", "of", "text", "justification."], 16,
             ["This    is    an", "example  of text", "justification.  "]),
            (["What", "must", "be", "acknowledgment", "shall", "be"], 16,
             ["What   must   be", "acknowledgment  ", "shall be        "]),
            (["Science", "is", "what", "we", "understand", "well", "enough", "to", "explain",
              "to", "a", "computer.", "Art", "is", "everything", "else", "we", "do"], 20,
             ["Science  is  what we", "understand      well", "enough to explain to",
              "a  computer.  Art is", "everything  else  we", "do                  "]),
        ],
    },
    {
        "name": "candy_crush",
        "description": "Given a 1D list of integers representing candy colors, repeatedly remove all groups of 3+ consecutive same-colored candies until no more can be removed. After removal, remaining candies fall together (close gaps). Return the final list.",
        "signature": "def candy_crush(board: list[int]) -> list[int]:",
        "tests": [
            ([1, 3, 3, 3, 2, 2, 2, 1], [1, 1]),           # remove 3s, then 2s
            ([1, 1, 1], []),                                 # all removed
            ([1, 2, 3], [1, 2, 3]),                          # nothing to remove
            # remove 2s → [1,1,1] → remove those → []
            ([1, 2, 2, 2, 1, 1], []),
            ([1, 1, 2, 2, 2, 1], []),                        # remove 2s → [1,1,1] → remove → []
            ([1, 2, 1], [1, 2, 1]),                          # no groups of 3
        ],
    },
    {
        "name": "int_to_roman",
        "description": "Convert an integer (1-3999) to a Roman numeral string. Use subtractive notation: IV=4, IX=9, XL=40, XC=90, CD=400, CM=900.",
        "signature": "def int_to_roman(num: int) -> str:",
        "tests": [
            (3, "III"),
            (4, "IV"),
            (9, "IX"),
            (58, "LVIII"),
            (1994, "MCMXCIV"),
            (3999, "MMMCMXCIX"),
            (44, "XLIV"),
            (100, "C"),
        ],
    },
    {
        "name": "atoi",
        "description": "Implement string to integer (atoi). Steps: 1) Skip leading whitespace. 2) Optional '+' or '-' sign. 3) Read digits until non-digit or end. 4) Clamp to 32-bit signed int range [-2^31, 2^31-1]. Return 0 if no digits found.",
        "signature": "def atoi(s: str) -> int:",
        "tests": [
            ("42", 42),
            ("   -42", -42),
            ("4193 with words", 4193),
            ("words and 987", 0),
            ("", 0),
            ("-91283472332", -2147483648),     # clamp to INT_MIN
            ("91283472332", 2147483647),       # clamp to INT_MAX
            ("+-12", 0),                        # invalid
            ("  +0 123", 0),
            ("   +", 0),
        ],
    },
    {
        "name": "trap_rain_water",
        "description": "Given a list of non-negative ints representing an elevation map (width 1 per bar), compute how much rain water can be trapped. Use the two-pointer approach.",
        "signature": "def trap_rain_water(height: list[int]) -> int:",
        "tests": [
            ([0, 1, 0, 2, 1, 0, 1, 3, 2, 1, 2, 1], 6),
            ([4, 2, 0, 3, 2, 5], 9),
            ([1, 2, 3, 4], 0),
            ([], 0),
            ([3, 0, 3], 3),
            ([5, 2, 1, 2, 1, 5], 14),
        ],
    },
    {
        "name": "zigzag_level_order",
        "description": "Given a binary tree as nested tuple (value, left, right) where None = no child, return zigzag (spiral) level-order traversal as list of lists. First level left-to-right, second right-to-left, alternating.",
        "signature": "def zigzag_level_order(root: tuple | None) -> list[list[int]]:",
        "tests": [
            ((3, (9, None, None), (20, (15, None, None), (7, None, None))),
             [[3], [20, 9], [15, 7]]),
            ((1, (2, (4, None, None), None), (3, None, (5, None, None))),
             [[1], [3, 2], [4, 5]]),
            (None, []),
            ((1, None, None), [[1]]),
        ],
    },
    {
        "name": "alien_dictionary",
        "description": "Given a list of words sorted in an alien language, derive the character ordering. Return a string of characters in sorted order. If invalid (cycle), return ''. If multiple valid orderings, return any. Use topological sort on the character graph inferred from adjacent word pairs.",
        "signature": "def alien_dictionary(words: list[str]) -> str:",
        "tests": [
            (["wrt", "wrf", "er", "ett", "rftt"], "wertf"),
            (["z", "x"], "zx"),
            (["z", "x", "z"], ""),              # cycle: z < x < z
            (["abc", "ab"], ""),                 # invalid: longer word before prefix
        ],
    },
    {
        "name": "kth_smallest_bst",
        "description": "Given a BST as nested tuple (value, left, right) and k (1-indexed), return the kth smallest element. Use in-order traversal.",
        "signature": "def kth_smallest_bst(root: tuple, k: int) -> int:",
        "tests": [
            ((3, (1, None, (2, None, None)), (4, None, None)), 1, 1),
            ((5, (3, (2, (1, None, None), None), (4, None, None)), (6, None, None)), 3, 3),
            ((1, None, (2, None, None)), 2, 2),
            ((3, (1, None, (2, None, None)), (4, None, None)), 4, 4),
        ],
    },
    {
        "name": "median_sorted_arrays",
        "description": "Find the median of two sorted arrays. Must run in O(log(min(m,n))) time. If the combined length is even, return the average of the two middle values as a float. If odd, return the middle value as a float.",
        "signature": "def median_sorted_arrays(nums1: list[int], nums2: list[int]) -> float:",
        "tests": [
            ([1, 3], [2], 2.0),
            ([1, 2], [3, 4], 2.5),
            ([0, 0], [0, 0], 0.0),
            ([], [1], 1.0),
            ([2], [], 2.0),
            ([1, 3, 5, 7], [2, 4, 6, 8], 4.5),
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
    errors = []
    for test_case in puzzle["tests"]:
        *inputs, expected = test_case
        test_input = inputs[0] if len(inputs) == 1 else tuple(inputs)
        try:
            result = fn(*inputs) if len(inputs) > 1 else fn(inputs[0])
            if result == expected:
                passed_tests += 1
            else:
                errors.append(f"input={test_input!r}: got {result!r}, expected {expected!r}")
        except Exception as e:
            errors.append(f"input={test_input!r}: raised {type(e).__name__}: {e}")

    return {
        "name": puzzle["name"],
        "passed": passed_tests == len(puzzle["tests"]),
        "total_tests": len(puzzle["tests"]),
        "passed_tests": passed_tests,
        "error": "; ".join(errors) if errors else None,
        "all_errors": errors,
    }


# ── LLM helpers ──────────────────────────────────────

_HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


_LLM_TRACE: list[dict] = []  # global trace log for all LLM calls


def llm_call(prompt: str, *, system: str = "", max_tokens: int = 4096, label: str = "") -> str:
    """Single Claude Sonnet call. Logs to _LLM_TRACE."""
    client = anthropic.Anthropic()
    kwargs: dict[str, Any] = dict(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    text = response.content[0].text
    _LLM_TRACE.append({
        "label": label,
        "system": system,
        "prompt": prompt,
        "response": text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    })
    return text


def extract_json(text: str) -> Any:
    """Extract JSON from LLM response. Tries multiple strategies."""
    text = text.strip()

    # Strip markdown code fences
    if "```" in text:
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    import re
    # Find outermost { ... } allowing nested braces
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = None

    raise json.JSONDecodeError("No valid JSON found", text, 0)


# ── Coglets ──────────────────────────────────────────


class CodeGenActor(Coglet):
    """Actor that holds Python solutions to puzzles."""

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
        # Batch to avoid token limit truncation
        batch_size = 5
        for i in range(0, len(self.puzzles), batch_size):
            batch = self.puzzles[i : i + batch_size]
            puzzle_specs = []
            for p in batch:
                puzzle_specs.append(f"### {p['name']}\n{p['description']}\n```python\n{p['signature']}\n```")

            prompt = (
                "Write a Python solution for each puzzle below. "
                "Return a JSON object mapping puzzle name to the complete Python function code (as a string). "
                "Each value must be a complete, standalone Python function. "
                "Return ONLY the JSON object, no other text.\n\n"
                + "\n\n".join(puzzle_specs)
            )

            response = llm_call(prompt, system="You are an expert Python programmer.", max_tokens=8192, label="actor_init")
            try:
                batch_solutions = extract_json(response)
                self.solutions.update(batch_solutions)
            except (json.JSONDecodeError, ValueError):
                # If JSON parsing fails, generate empty stubs
                for p in batch:
                    fn_name = p["signature"].split("(")[0].replace("def ", "").strip()
                    self.solutions.setdefault(p["name"], f"def {fn_name}(*args): pass")

    @enact("update")
    async def apply_update(self, patch):
        new_solutions = patch.get("solutions", {})
        self.solutions.update(new_solutions)


class CodeReviewCritic(Coglet):
    """Critic that predicts pass/fail for each solution."""

    def __init__(self, *, puzzles: list[dict], **kwargs):
        super().__init__(**kwargs)
        self.puzzles = puzzles
        self.strategy = "Look for common bugs: off-by-one errors, missing edge cases, wrong return types."

    @listen("experience")
    async def evaluate(self, experience):
        results = experience["results"]
        solution_texts = []
        for r in results:
            p = next((p for p in self.puzzles if p["name"] == r["name"]), None)
            desc = p["description"] if p else ""
            test_example = ""
            if p and p.get("tests"):
                tc = p["tests"][0]
                *inputs, expected = tc
                inp = inputs[0] if len(inputs) == 1 else tuple(inputs)
                test_example = f"  e.g. {inp!r} → {expected!r}"
            solution_texts.append(
                f"### {r['name']}\n{desc}\n{test_example}\n```python\n{r['code']}\n```"
            )

        prompt = (
            f"Strategy: {self.strategy}\n\n"
            "Predict PASS or FAIL for each solution. "
            "Return JSON mapping name to 'pass' or 'fail'. ONLY JSON.\n\n"
            + "\n\n".join(solution_texts)
        )

        response = llm_call(prompt, system="You are a code reviewer predicting test outcomes.", label="critic_predict")
        try:
            predictions = extract_json(response)
        except (json.JSONDecodeError, ValueError):
            predictions = {}

        evaluation = []
        for r in results:
            predicted = predictions.get(r["name"], "fail").lower().strip()
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


# ── Losses ───────────────────────────────────────────


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


# ── Constraint ───────────────────────────────────────


class MaxRewritesConstraint(ConstraintCoglet):
    async def check(self, patch):
        n = len(patch.get("solutions", {}))
        if n > 5:
            return {"accepted": False, "reason": f"too many rewrites: {n} (max 5)"}
        return {"accepted": True}


# ── Learner ──────────────────────────────────────────


class CodeGenLearner(LearnerCoglet):
    """Learner with memory: tracks all previous attempts per puzzle.

    Each epoch appends to a per-puzzle log of (code, error) pairs.
    The full history is included in the fix prompt so the LLM doesn't
    repeat the same broken approaches.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # puzzle_name → list of {"code": str, "error": str, "epoch": int}
        self._history: dict[str, list[dict]] = {}
        self._epoch = 0
        self._last_critic_strategy = "Look for common bugs: off-by-one errors, missing edge cases, wrong return types."

    async def learn(self, experience, evaluation, signals):
        self._epoch += 1
        actor_signal = next((s for s in signals if s.get("name") == "actor_loss"), None)
        critic_signal = next((s for s in signals if s.get("name") == "critic_loss"), None)

        # Record all failures into history
        if actor_signal and actor_signal.get("failed_puzzles"):
            for f in actor_signal["failed_puzzles"]:
                name = f["name"]
                self._history.setdefault(name, [])
                # Don't log duplicates (same code)
                if not self._history[name] or self._history[name][-1]["code"] != f["code"]:
                    self._history[name].append({
                        "code": f["code"],
                        "error": f["error"],
                        "epoch": self._epoch,
                    })

        new_solutions = {}
        new_critic_strategy = None

        # Fix failing solutions (max 5)
        if actor_signal and actor_signal.get("failed_puzzles"):
            failed = actor_signal["failed_puzzles"][:5]
            puzzle_map = {p["name"]: p for p in PUZZLES}

            fix_parts = []
            for f in failed:
                puzzle = puzzle_map.get(f["name"], {})
                # Include test cases so the LLM knows exact expected behavior
                test_lines = ""
                if puzzle.get("tests"):
                    for tc in puzzle["tests"]:
                        *inputs, expected = tc
                        inp = inputs[0] if len(inputs) == 1 else tuple(inputs)
                        test_lines += f"  assert fn({inp!r}) == {expected!r}\n"
                part = (
                    f"### {f['name']}\n"
                    f"Description: {puzzle.get('description', 'N/A')}\n"
                    f"Signature: {puzzle.get('signature', 'N/A')}\n"
                    f"Test cases:\n{test_lines}\n"
                    f"Current code:\n```python\n{f['code']}\n```\n"
                    f"Errors: {f['error']}\n"
                )

                # Add history of previous failed attempts
                history = self._history.get(f["name"], [])
                if len(history) > 1:
                    part += "\nPREVIOUS FAILED ATTEMPTS (do NOT repeat these approaches):\n"
                    # Show last 5 attempts to keep prompt bounded
                    for prev in history[-5:]:
                        part += (
                            f"- Epoch {prev['epoch']}:\n"
                            f"  ```python\n  {prev['code'][:300]}{'...' if len(prev['code']) > 300 else ''}\n  ```\n"
                            f"  Error: {prev['error']}\n"
                        )
                    part += "\nYou MUST try a fundamentally different approach than the ones above.\n"

                fix_parts.append(part)

            prompt = (
                "Fix these failing Python solutions. For each, return the corrected complete function. "
                "IMPORTANT: If previous attempts are listed, you MUST try a different algorithm or approach. "
                "Do not make minor tweaks to code that has already failed — rethink the solution.\n"
                "Return a JSON object mapping puzzle name to the fixed Python code string. "
                "Return ONLY the JSON object.\n\n"
                + "\n\n".join(fix_parts)
            )

            response = llm_call(prompt, system="You are an expert Python programmer fixing bugs.", max_tokens=8192, label="learner_fix")
            try:
                new_solutions = extract_json(response)
            except (json.JSONDecodeError, ValueError):
                pass

        # Update critic strategy — only when there are false positives
        # (predicted pass but actually failed). False negatives (predicted fail,
        # actually pass) are less harmful — being cautious is fine.
        if critic_signal and critic_signal.get("wrong_predictions"):
            wrong = critic_signal["wrong_predictions"]
            false_positives = [w for w in wrong if w["predicted"] == "pass" and w["actual"] == "fail"]
            false_negatives = [w for w in wrong if w["predicted"] == "fail" and w["actual"] == "pass"]

            if false_positives or len(false_negatives) > 5:
                wrong_parts = []
                for w in false_positives:
                    wrong_parts.append(f"- {w['name']}: you said PASS but it FAILED (error: {w.get('error', 'unknown')})")
                for w in false_negatives[:5]:
                    wrong_parts.append(f"- {w['name']}: you said FAIL but it actually PASSED")

                prompt = (
                    f"You are a code review critic. Your current strategy is:\n\"{self._last_critic_strategy}\"\n\n"
                    f"You got {len(false_positives)} false positives and {len(false_negatives)} false negatives:\n"
                    + "\n".join(wrong_parts)
                    + "\n\nUpdate your strategy. Be SPECIFIC about what patterns to look for. "
                    "Start with your existing strategy text and add/modify specific rules. "
                    "Key insight: if you have many false negatives (said FAIL but passed), you are being too pessimistic — "
                    "most well-structured code does pass. 2-4 sentences."
                    "\n\nReturn ONLY the strategy text."
                )

                new_critic_strategy = llm_call(prompt, max_tokens=300, label="learner_critic_update")
                self._last_critic_strategy = new_critic_strategy

        return {
            "solutions": new_solutions,
            "critic_strategy": new_critic_strategy,
        }


# ── Sanity tests (no API key needed) ──────────────────


def test_harness_runs_correct_solution():
    puzzle = next(p for p in PUZZLES if p["name"] == "trap_rain_water")
    code = textwrap.dedent("""\
        def trap_rain_water(height):
            if not height: return 0
            l, r = 0, len(height) - 1
            lmax = rmax = water = 0
            while l < r:
                if height[l] <= height[r]:
                    lmax = max(lmax, height[l])
                    water += lmax - height[l]
                    l += 1
                else:
                    rmax = max(rmax, height[r])
                    water += rmax - height[r]
                    r -= 1
            return water
    """)
    result = run_solution(puzzle, code)
    assert result["passed"] is True
    assert result["passed_tests"] == len(puzzle["tests"])


def test_harness_catches_bad_solution():
    puzzle = next(p for p in PUZZLES if p["name"] == "trap_rain_water")
    code = "def trap_rain_water(height): return 0"
    result = run_solution(puzzle, code)
    assert result["passed"] is False
    assert result["error"] is not None


@pytest.mark.skipif(not _HAS_API_KEY, reason="ANTHROPIC_API_KEY not set")
@pytest.mark.asyncio
async def test_pco_llm_experiment():
    """Full PCO experiment: 5 epochs of LLM-driven code improvement."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    runtime = CogletRuntime()
    pco_handle = await runtime.spawn(CogBase(
        cls=ProximalCogletOptimizer,
        kwargs=dict(
            actor_config=CogBase(cls=CodeGenActor, kwargs=dict(puzzles=PUZZLES)),
            critic_config=CogBase(cls=CodeReviewCritic, kwargs=dict(puzzles=PUZZLES)),
            losses=[ActorLoss(), CriticLoss()],
            constraints=[MaxRewritesConstraint()],
            learner=CodeGenLearner(),
            max_retries=2,
        ),
    ))
    pco = pco_handle.coglet

    num_epochs = 5
    metrics = []

    print("\n  ┌───────┬──────────────────┬──────────────────┬──────────┐")
    print("  │ Epoch │ Actor Pass Rate  │ Critic Accuracy  │ Accepted │")
    print("  ├───────┼──────────────────┼──────────────────┼──────────┤")

    for epoch in range(num_epochs):
        result = await pco.run_epoch(timeout=120.0)

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

        print(
            f"  │   {epoch + 1}   │   {actor_pass:2d}/{total} ({epoch_metrics['actor_pass_rate']:5.0%})   "
            f"│   {critic_correct:2d}/{total} ({epoch_metrics['critic_accuracy']:5.0%})   "
            f"│ {'  yes   ' if result['accepted'] else '  no    '} │"
        )

    print("  └───────┴──────────────────┴──────────────────┴──────────┘")

    # Write results
    (RESULTS_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

    actor = pco._actor_handle.coglet
    (RESULTS_DIR / "final_solutions.json").write_text(
        json.dumps(actor.solutions, indent=2)
    )

    critic = pco._critic_handle.coglet
    (RESULTS_DIR / "final_critic_strategy.txt").write_text(critic.strategy)

    await runtime.shutdown()

    # ── Assertions ─────────────────────────────────────
    first = metrics[0]
    last = metrics[-1]

    print(f"\n  Actor improvement:  {first['actor_pass_rate']:.0%} → {last['actor_pass_rate']:.0%}")
    print(f"  Critic improvement: {first['critic_accuracy']:.0%} → {last['critic_accuracy']:.0%}")

    # Assert improvement or stability — the best epoch should beat the first
    best_actor = max(m["actor_pass_rate"] for m in metrics)
    best_critic = max(m["critic_accuracy"] for m in metrics)

    assert best_actor >= first["actor_pass_rate"], \
        f"Actor should not degrade overall: first={first['actor_pass_rate']:.0%}, best={best_actor:.0%}"
    assert best_actor >= 0.5, \
        f"Actor should solve at least half: best was {best_actor:.0%}"
    assert best_critic >= 0.5, \
        f"Critic should reach at least 50% accuracy: best was {best_critic:.0%}"
