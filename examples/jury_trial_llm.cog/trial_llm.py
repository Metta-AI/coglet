"""LLM-powered Jury Trial — advocates argue before an LLM jury.

Requires ANTHROPIC_API_KEY to be set. Will crash on startup if missing.

Full adversarial system where:
  - Two AdvocateCoglets use LLM to build arguments (pro and con)
  - N JurorCoglets hear both sides, then use LLM to deliberate
  - SuppressLet gates juror output during argument phase
  - TrialCoglet orchestrates the full proceeding

Demonstrates every mixin in combination:
  - LifeLet: lifecycle hooks
  - ProgLet: program table with LLM executor
  - LLMExecutor: real LLM reasoning via Anthropic API
  - LogLet: structured logging
  - SuppressLet: output gating during argument phase
  - MulLet pattern: fan-out jurors
  - Full guide/observe/transmit/listen data+control planes
"""

import os
import sys

import anthropic

from coglet import (
    Coglet, LifeLet, ProgLet, LogLet, CogletConfig, Command,
    Program, LLMExecutor, enact, listen,
)
from coglet.suppresslet import SuppressLet

if not os.environ.get("ANTHROPIC_API_KEY"):
    sys.exit("error: ANTHROPIC_API_KEY is required. Set it and try again.")

CLIENT = anthropic.Anthropic()

JUROR_PERSONAS = [
    "a strict empiricist who demands reproducible evidence",
    "a philosophical skeptic who questions all assumptions",
    "a practical engineer who trusts measurement and observation",
    "a historian who values the accumulated record of human knowledge",
    "a curious child who asks simple but penetrating questions",
]


def _parse_verdict(text: str) -> dict:
    lower = text.lower()
    if "vote: yes" in lower or "i vote yes" in lower:
        vote = "yes"
    elif "vote: no" in lower or "i vote no" in lower:
        vote = "no"
    else:
        vote = "yes" if lower.count("yes") > lower.count("no") else "no"
    return {"vote": vote, "reasoning": text.strip()}


def _parse_argument(text: str) -> dict:
    return {"argument": text.strip()}


class AdvocateCoglet(Coglet, LifeLet, ProgLet, LogLet):
    """An advocate that uses LLM to construct arguments."""

    def __init__(self, side: str = "prosecution", **kwargs):
        super().__init__(**kwargs)
        self.side = side

    async def on_start(self):
        self.executors["llm"] = LLMExecutor(CLIENT)

        if self.side == "prosecution":
            role_prompt = (
                "You are a debate team member assigned the PRO side. "
                "The motion will be given as the user message. "
                "Argue that the motion IS TRUE. Present 3-4 strong, "
                "specific arguments with evidence. Be persuasive and concise."
            )
        else:
            role_prompt = (
                "You are a debate team member assigned the CON side. "
                "The motion will be given as the user message. "
                "Argue that the motion IS FALSE. Present 3-4 strong, "
                "specific arguments with evidence. Be persuasive and concise."
            )

        self.programs["argue"] = Program(
            executor="llm",
            system=lambda _ctx, rp=role_prompt: rp,
            parser=_parse_argument,
            config={"max_turns": 1, "max_tokens": 300, "temperature": 0.9},
        )
        await self.log("info", f"{self.side} advocate ready")

    @enact("present")
    async def on_present(self, motion: str):
        result = await self.invoke("argue", motion)
        await self.log("info", f"{self.side} presented argument")
        await self.transmit("argument", {
            "side": self.side,
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"{self.side} rests")


class JurorCoglet(SuppressLet, Coglet, LifeLet, ProgLet, LogLet):
    """LLM-powered juror that hears arguments and votes."""

    def __init__(self, juror_id: int = 0, persona: str = "", **kwargs):
        super().__init__(**kwargs)
        self.juror_id = juror_id
        self.persona = persona
        self.arguments_heard: list[dict] = []

    async def on_start(self):
        self.executors["llm"] = LLMExecutor(CLIENT)

        self.programs["weigh"] = Program(
            executor="llm",
            system=lambda _ctx: (
                f"You are a juror. Your persona: {self.persona}. "
                f"You have heard the following arguments:\n\n"
                + "\n\n".join(
                    f"[{a['side'].upper()}]: {a['argument']}"
                    for a in self.arguments_heard
                )
                + "\n\nWeigh both sides from your unique perspective. "
                "State your reasoning briefly, then end with 'Vote: yes' or 'Vote: no'."
            ),
            parser=_parse_verdict,
            config={"max_turns": 1, "max_tokens": 200, "temperature": 0.8},
        )
        await self.log("info", f"juror-{self.juror_id} ({self.persona[:30]}...) seated")

    @listen("evidence")
    async def on_evidence(self, argument: dict):
        self.arguments_heard.append(argument)
        await self.log("debug", f"juror-{self.juror_id} heard {argument['side']}")

    @enact("deliberate")
    async def on_deliberate(self, motion: str):
        result = await self.invoke("weigh", motion)
        await self.log("info", f"juror-{self.juror_id} votes {result['vote']}")
        await self.transmit("verdict", {
            "juror_id": self.juror_id,
            "persona": self.persona[:40],
            **result,
        })

    async def on_stop(self):
        await self.log("info", f"juror-{self.juror_id} dismissed")


class TrialCoglet(Coglet, LifeLet):
    """Orchestrates a full LLM-powered trial."""

    def __init__(self, motion: str = "", num_jurors: int = 5, **kwargs):
        super().__init__(**kwargs)
        self.motion = motion
        self.num_jurors = num_jurors

    async def on_start(self):
        print(f"{'='*60}")
        print(f"  TRIAL: {self.motion}")
        print(f"{'='*60}")
        print()

        # Phase 1: Empanel jury (suppress verdicts)
        print("[trial] empaneling jury...")
        juror_handles = []
        for i in range(self.num_jurors):
            persona = JUROR_PERSONAS[i % len(JUROR_PERSONAS)]
            h = await self.create(CogletConfig(
                cls=JurorCoglet,
                kwargs={"juror_id": i, "persona": persona},
            ))
            await self.guide(h, Command("suppress", {"channels": ["verdict"]}))
            juror_handles.append(h)

        # Phase 2: Seat advocates
        print("[trial] seating advocates...")
        prosecution = await self.create(CogletConfig(
            cls=AdvocateCoglet, kwargs={"side": "prosecution"},
        ))
        defense = await self.create(CogletConfig(
            cls=AdvocateCoglet, kwargs={"side": "defense"},
        ))

        pro_sub = prosecution.coglet._bus.subscribe("argument")
        def_sub = defense.coglet._bus.subscribe("argument")

        # Phase 3: Prosecution
        print()
        print("[trial] PROSECUTION, present your case.")
        await self.guide(prosecution, Command("present", self.motion))
        pro_arg = await pro_sub.get()
        print(f"  PRO: {pro_arg['argument']}")

        # Phase 4: Defense
        print()
        print("[trial] DEFENSE, present your case.")
        await self.guide(defense, Command("present", self.motion))
        def_arg = await def_sub.get()
        print(f"  DEF: {def_arg['argument']}")

        # Phase 5: Deliver to jury
        print()
        print("[trial] delivering arguments to jury...")
        for h in juror_handles:
            await h.coglet._dispatch_listen("evidence", pro_arg)
            await h.coglet._dispatch_listen("evidence", def_arg)

        # Phase 6: Deliberate
        print("[trial] jury may now deliberate.")
        print()

        verdict_subs = []
        for h in juror_handles:
            verdict_subs.append(h.coglet._bus.subscribe("verdict"))

        for h in juror_handles:
            await self.guide(h, Command("unsuppress", {"channels": ["verdict"]}))
            await self.guide(h, Command("deliberate", self.motion))

        # Phase 7: Collect verdicts
        verdicts = []
        for sub in verdict_subs:
            verdicts.append(await sub.get())

        # Phase 8: Announce
        yes_votes = sum(1 for v in verdicts if v["vote"] == "yes")
        no_votes = len(verdicts) - yes_votes
        result = "MOTION CARRIES" if yes_votes > no_votes else "MOTION FAILS"

        print("[trial] === JURY DELIBERATION ===")
        for v in verdicts:
            symbol = "+" if v["vote"] == "yes" else "-"
            print(f"  [{symbol}] juror-{v['juror_id']} ({v['persona']}):")
            for line in v["reasoning"].split(". "):
                if line.strip():
                    print(f"      {line.strip()}.")
            print()

        print(f"[trial] === VERDICT: {result} ({yes_votes}-{no_votes}) ===")
        await self.transmit("result", {"motion": self.motion, "result": result})

    async def on_stop(self):
        print("[trial] court adjourned")
