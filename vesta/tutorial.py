"""A tutorial you walk through rather than read.

`guide` is a reference: everything at once, for somebody who already knows what
they are looking for. This is the other thing — five chapters, one at a time,
each rendered as a page of topics with the lesson beside them. You arrow down
the list to read, and selecting turns the page.

**It is drawn by the host, not by Vesta.** A plugin cannot render a menu in the
Claude Code TUI, and running a curses application would put it outside the
session where the user is working. What it can do is hand the agent a page and
have the agent draw it with `AskUserQuestion`, whose `preview` field renders
markdown in a pane beside the options. That is a real navigable interface —
arrow keys move, content follows, no external process — and it is the same
mechanism the mode dialog already uses, so it is proven here rather than hoped
for.

Which fixes the shape of a page, and the constraint is the host's: **two to
four topics**, a header of at most twelve characters, and selection as the only
way forward. So the page indicator lives in the header (`Ch 2 of 5`) and every
chapter is written to fit in four.

**Taught on the reader's own repository.** A chapter about asking where work is
done runs the question against the code they are sitting in and shows what came
back. An invented example proves nothing and ages badly; a real one proves the
tool runs here, which is the thing a new user actually doubts.

**It never acts.** Reading the repository is free and safe. Signing a contract
or starting a build is neither, and a tutorial that demonstrates automation by
beginning some is a tutorial that hijacked a session to explain itself. So the
chapters on contracts and driving are told, not performed — every command run
here is read-only, and that is enforced by a test rather than by intention.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("vesta.tutorial")

# What a chapter may run to teach itself. Read-only, every one — a tutorial
# that starts work to explain work has hijacked the session it was invited
# into. Enforced by a test, not by remembering.
SAFE = {
    "shape", "status", "does", "words", "defects", "decided", "guide",
    "projects", "contract", "used", "uses", "means", "known", "touches",
}

# Some of those read *or* write depending on what follows them: bare `contract`
# shows what was agreed, `contract --sign` agrees to it. A whitelist keyed on
# the verb alone cannot tell the two apart, so the flags are checked too.
#
# Listed as what is forbidden rather than what is allowed, because a new
# read-only flag appearing on some command should not silently become
# un-demonstrable — while a new flag that *acts* will be named here or caught
# by the test that no demonstration writes anything.
ACTS = {
    "--sign", "--goal", "--does", "--met", "--constraint", "--inferred",
    "--noted", "--declare", "--prepare", "--step", "--declined", "--check",
    "--edit", "--set", "--from", "--template", "--text", "--verdict",
}

# How long a demonstration may take before it is not worth waiting for. A
# chapter is a page of text; a page of text that hangs is worse than one with
# a fixed example on it.
PATIENCE = 25


class Topic(BaseModel):
    """One thing on a page: what it is called, and what it teaches."""

    label: str
    why: str
    teaches: str

    # A command run against the reader's own repository, whose output is shown
    # inside the lesson where `{}` appears. Read-only or it does not belong.
    runs: str = ""

    # How much of what the command said to show. A pane holds about ten lines,
    # and an output grouped by kind — every `domain:` before any `activity:` —
    # would otherwise be truncated to one kind, teaching the reader that their
    # vocabulary has only activities in it.
    spread: bool = False


class Chapter(BaseModel):
    """A page of the tutorial."""

    header: str
    asks: str
    topics: List[Topic] = Field(default_factory=list)


CHAPTERS: List[Chapter] = [
    Chapter(
        header="Ch 1 of 5",
        asks="Vesta — how you work with it. Arrow through to read; pick one to go on.",
        topics=[
            Topic(
                label="Companion — the default",
                why="Nothing to run. It answers and records while you work normally.",
                teaches="""# Companion mode

This is what you get by installing it. There is
nothing to switch on, and nothing to run.

You work the way you already do. Vesta:

  · answers your agent's questions about this
    repository from a resolved graph, so it asks
    instead of reading forty files

  · records what you decide, as you say it —
    "one .env for the whole of v3" is kept
    because you said it in passing, not because
    you ran a command

  · says nothing when it has nothing to say

It never takes the wheel. No contract, no
agreement to sign, no loop. If you never read
past this page you are still using it properly.""",
            ),
            Topic(
                label="Automated — opt in, once",
                why="Agree the behaviours up front, then it runs to completion.",
                teaches="""# Automated mode

You are never put in this. When you ask for a
whole project to be built, a dialog appears
offering Automated or Interactive — and if you
choose Interactive you are not asked again.

Choosing Automated:

  1. the agent works out a contract — what the
     thing does, for whom — in this session,
     where you watch it take shape
  2. you read it, and accept or decline
  3. it builds, recording each behaviour as it
     is met, and stops when every one is done

While it is driving, a request that changes an
agreed behaviour is refused rather than weighed.
You can carry on, start over, or have the change
after delivery. That is your call to make.""",
            ),
            Topic(
                label="What it costs",
                why="Your agent's own inference. No API key, nothing leaves the machine.",
                teaches="""# What it costs, and what leaves

Vesta holds no API key and makes no network
calls of its own. It runs on the inference you
are already paying for.

Which model does what is not a preference:

  · reading a definition and labelling it runs
    on haiku, because it happens once for every
    definition — a larger model at that volume
    makes the whole approach too expensive to
    be worth using

  · synthesis you will be held to, like a
    contract, runs on sonnet, once

Everything derived is kept under ~/.vesta and
can be deleted at any time. Nothing leaves your
machine.""",
            ),
        ],
    ),
    Chapter(
        header="Ch 2 of 5",
        asks="Asking about code you have not read. These are run against this repository.",
        topics=[
            Topic(
                label="What am I looking at?",
                why="What the repository is made of, before opening a single file.",
                runs="shape",
                teaches="""# Before reading anything

`vesta shape` tells you what a repository is
made of — its size, and what the rest of it
leans on — before you have opened a file.

In *this* repository, right now:

{}

The most depended-upon definitions are where a
mistake propagates furthest. That is a fact
about the graph, not an opinion about the code.""",
            ),
            Topic(
                label="Where is X done?",
                why="Ask in the words of the work; get back the words of the code.",
                runs="does 'building a graph of what refers to what'",
                teaches="""# Crossing from work to code

You know what you want the code to *do*. You do
not know what it is called. That crossing is
the whole point.

  vesta does 'building a graph of what refers
              to what'

In *this* repository:

{}

Nobody grepped for "graph". The question was
asked in ordinary words and answered in the
vocabulary of this codebase.""",
            ),
            Topic(
                label="What breaks if I change it?",
                why="Resolved through the code, so four methods sharing a name stay four.",
                teaches="""# What a change reaches

  vesta touches src/api.py
      what the change reaches, and which tests
      cover it

  vesta uses admit
      where it is, what refers to it, and what
      it refers to

Resolved through the code rather than matched
by name. Four methods called `run` stay four
methods, which is the difference between an
answer and a grep.

This one is not run here: it needs a file you
have actually changed to say anything useful.""",
            ),
            Topic(
                label="What is worth fixing?",
                why="Found without being asked, independent of anything you said.",
                runs="defects",
                teaches="""# Found without being asked

In *this* repository:

{}

Note what these are: not style, not taste. A
failure swallowed by a bare `except`, a
definition nothing refers to, a call no
resolver can follow. Each is checkable, and
each is somewhere an answer would otherwise
be quietly wrong.""",
            ),
        ],
    ),
    Chapter(
        header="Ch 3 of 5",
        asks="The words your project is described in. These are yours to change.",
        topics=[
            Topic(
                label="What the words are",
                why="What this project is about, what its code does, what it handles.",
                runs="words",
                spread=True,
                teaches="""# The vocabulary

Everything Vesta answers about *work* rather
than about syntax is answered in these words.

In *this* repository:

{}

They were read from the code, which makes them
a good first draft and a bad final answer. The
agent read your files; it did not sit in your
meetings.""",
            ),
            Topic(
                label="Changing them",
                why="Open them in your editor. A word that is wrong makes every answer wrong.",
                teaches="""# Editing the words

From a terminal:

  vesta words --edit

Opens them in $EDITOR, one per line, as
`kind: label`. Delete a line to remove a word.
Quit without saving and nothing changes.

In a session, `/vesta:words` does the same
thing through the agent.

**Removing a word removes what was attached to
it**, and putting the word back does not bring
those bindings back — they have to be read from
the code again. Vesta tells you the number
rather than passing over it.""",
            ),
            Topic(
                label="Starting from a template",
                why="Six shipped vocabularies for common domains. Words only, never bindings.",
                runs="words --templates",
                teaches="""# Templates

Shipped, for domains where the words are the
same everywhere:

{}

A template supplies **words only**. It has never
seen your repository, so it is in no position to
say which of your definitions do the work — that
stays derived from your own code, every time.

  vesta words --template security
      adds those words to yours

  vesta words --from ours.md
      any file of your own

  vesta words --set ours.md
      replaces, so deletions take effect""",
            ),
            Topic(
                label="Writing your own",
                why="Any text file. Prose is ignored, so it can explain itself.",
                teaches="""# A vocabulary of your own

A vocabulary is a text file. Lines that look
like `kind: label` are words; everything else is
a comment, so it can carry headings and
explanation.

    # How we talk about this system

    domain: settling trades before the cutoff
    activity: reconcile against the custodian
    role: an unmatched break

Three kinds: `domain` is what the project is
about, `activity` is something the code does,
`role` is something it handles.

A word naming nothing in your code is kept and
reported as unattached. That is usually true and
worth knowing — the language moved and the code
has not caught up.""",
            ),
        ],
    ),
    Chapter(
        header="Ch 4 of 5",
        asks="Contracts and driving — what automated mode actually does. Nothing here is started.",
        topics=[
            Topic(
                label="What a contract is",
                why="Behaviours, checkable without an opinion. Agreed before code exists.",
                teaches="""# The contract

Before anything is built in automated mode, the
agent writes down what it is going to build:

  · **behaviours** — what the system does and
    for whom. `a user can file a task`. Each
    checkable without an opinion. Six to twelve
    is usual.

  · **constraints** — how it must be built, and
    only ever what *you* said. `use SQLite`.

  · **everything else** — storage, layout, glue
    — inferred and recorded, never asked about.
    You can read afterwards what was chosen for
    you.

You read it and accept or decline. Nothing is
written until you accept.""",
            ),
            Topic(
                label="Why it refuses things",
                why="A contract that follows your mind is not a contract.",
                teaches="""# Refusal

While driving, asking for something that changes
an agreed behaviour is refused. Not weighed,
not scored.

That sounds unhelpful and is the point. The
behaviours were agreed before any code existed.
A loop chasing a moving target never terminates,
and "done" stops meaning anything.

You are offered three ways out, and Vesta does
not pick for you:

  · carry on to completion as agreed
  · start over, with the change in the contract
  · have it after delivery

Changes that do not touch behaviour — a library,
a layout, a rename — are simply absorbed.""",
            ),
            Topic(
                label="Knowing when it is done",
                why="Each behaviour recorded as it is met. Done is a count, not a feeling.",
                runs="contract",
                teaches="""# Done

Each behaviour is recorded as it is built and
tested, so finishing is a count reaching a
total rather than a judgement call.

In *this* repository:

{}

If nothing is shown, nothing has been agreed
here — which is the normal state for a project
being used as a companion.""",
            ),
        ],
    ),
    Chapter(
        header="Ch 5 of 5",
        asks="The rest of it — what you decided, other projects, and where things are kept.",
        topics=[
            Topic(
                label="What you decided",
                why="Rules recovered from your own corrections, and checked against the code.",
                runs="decided",
                teaches="""# Decisions

Say a rule while working — "one .env for the
whole of v3" — and it is kept because you said
it. Nothing to run, nothing to remember.

In *this* repository:

{}

  vesta decided --check
      whether the code still honours them

  /vesta:declare <a rule>
      state one outright, for a constraint you
      have simply always observed and so never
      had to correct anybody about

  vesta bears src/api.py
      whether a rule is in doubt for what you
      are about to change""",
            ),
            Topic(
                label="Other projects",
                why="How a sibling project does something, without merging the two.",
                runs="projects",
                teaches="""# Across projects

  vesta elsewhere fuzzy search --in indexer

Asks another project how it does a kind of work.
The project you are in stays authoritative; the
other is consulted, not merged.

Available here:

{}""",
            ),
            Topic(
                label="Where things are kept",
                why="Under ~/.vesta. Deletable, inspectable, yours.",
                runs="status",
                teaches="""# What is held

Everything derived lives under ~/.vesta — the
graph, the vocabulary, your decisions. Delete
any of it and it is rebuilt when needed.

In *this* repository:

{}

  vesta used
      what Vesta has been asked, and what it
      saved by answering from what it already
      knew

That last one is the honest accounting: not
what it might save, what it did.""",
            ),
            Topic(
                label="Everything at once",
                why="The reference, for when you know what you are looking for.",
                teaches="""# The reference

This tutorial walks. The guide lists.

  /vesta:help
  vesta guide
      every command, grouped by the question it
      answers

  vesta guide words
      one section of it

You can come back here with `/vesta:tutorial`,
and start anywhere: `/vesta:tutorial 3`.

That is the whole tool. Most of it you will
never type — in companion mode the agent asks
on your behalf, and you carry on working.""",
            ),
        ],
    ),
]


def _launcher() -> str:
    """The command that runs Vesta, wherever it was installed to."""
    import os

    root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if root:
        return str(Path(root) / "bin" / "vesta-run")
    return str(Path(__file__).resolve().parent.parent / "bin" / "vesta-run")


def reads(said: List[str]) -> bool:
    """Whether an invocation only reads.

    Both halves matter. `contract` shows what was agreed and `contract --sign`
    agrees to it, so the verb alone does not decide; and `words --templates`
    lists while `words --template x` writes, so the flags are matched exactly
    rather than by prefix — one letter apart, opposite answers.
    """
    if not said or said[0] not in SAFE:
        return False
    return not any(word in ACTS for word in said[1:])


def _is_advice(line: str) -> bool:
    """Whether a line tells the reader what to do rather than what is there.

    A command's closing advice is prose: unindented, and a sentence rather
    than a row. Both halves are needed — keying on the opening verb alone
    missed "A template supplies words only…", which is the same duplication
    wearing a different first word, and keying on length alone would eat a
    long result.
    """
    if line.startswith((" ", "\t")):
        return False

    said = line.strip()
    first = said.split(" ", 1)[0].lower().strip(",.")
    if first in {"add", "run", "edit", "use", "try", "start", "see", "then"}:
        return True

    # A sentence: several words, and it ends like one. A row of data almost
    # never does both.
    return said.endswith(".") and len(said.split()) > 6


def _across(lines: List[str], most: int) -> List[str]:
    """A sample that covers every kind, rather than the first N of one.

    `words` prints all the domains, then all the activities, then all the
    roles. Taking the first ten of that shows a reader ten activities and
    teaches them their vocabulary contains nothing else. So the groups are
    found, and each contributes its share.
    """
    groups: Dict[str, List[str]] = {}
    for line in lines:
        kind = line.split(":", 1)[0].strip() if ":" in line else ""
        groups.setdefault(kind, []).append(line)

    if len(groups) < 2:
        return lines[:most]

    each = max(1, most // len(groups))
    taken: List[str] = []
    for kind, group in groups.items():
        taken.extend(group[:each])
    return taken[:most]


def _ran(command: str, repo: Path, spread: bool = False) -> str:
    """What a read-only command says about this repository, indented for a pane.

    Failure is not an error here. A chapter whose demonstration could not run
    still teaches what it teaches; saying so plainly is better than an empty
    box, and far better than a tutorial that refuses to start because a graph
    has not been built yet.
    """
    try:
        import shlex

        said = shlex.split(command)
    except ValueError:
        logger.error("a chapter's command could not be read: %r", command)
        return "  (not shown)"

    if not reads(said):
        # Belt and braces. The test enforces this, and so does this line: a
        # tutorial must never be the thing that started work.
        logger.error("a chapter tried to run %r, which is not read-only", command)
        return "  (not shown)"

    try:
        done = subprocess.run(
            [sys.executable, "-m", "vesta.cli"] + said,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=PATIENCE,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.info("could not run %r for the tutorial: %s", command, exc)
        return "  (could not run this here)"

    # Stripped of blank lines, not of whitespace: `.strip()` on the whole
    # block takes the indent off the *first* line only, so a uniformly
    # indented table arrives with its first row two spaces shallower than the
    # rest and every later dedent measures against the wrong margin.
    said = (done.stdout or done.stderr or "").strip("\n")
    if not said:
        return "  (nothing yet)"

    # Every command prints which project it is talking about. In a pane beside
    # a lesson that already says "in *this* repository", that is two lines of
    # the twelve available spent restating the obvious.
    lines = [
        line
        for line in said.splitlines()
        if line.strip() and not line.startswith(("project:", "(paths below"))
    ]

    # Several commands end by telling the reader what to do next. In a pane
    # whose lesson does exactly that, in better words, it is duplication —
    # so a trailing sentence is dropped and the demonstration stays a
    # demonstration.
    while lines and _is_advice(lines[-1]):
        lines.pop()

    # A pane is narrow and a chapter is a page. Ten lines is what fits beside a
    # list of four topics without the reader having to scroll to finish a
    # sentence.
    shown = _across(lines, 10) if spread else lines[:10]
    if len(lines) > len(shown):
        shown.append(f"… and {len(lines) - len(shown)} more")

    # Drop the common indent rather than every indent. Several commands nest
    # detail under a heading, and flattening that loses which detail belongs to
    # which — but keeping a uniform margin wastes a narrow pane.
    #
    # Measured over the lines that survived rather than taken from the first
    # one: dropping a `project:` header off the top leaves a block whose first
    # row is shallower than the rest, and `textwrap.dedent` would then find no
    # common prefix and remove nothing.
    least = min(
        (len(line) - len(line.lstrip()) for line in shown if line.strip()),
        default=0,
    )
    return "\n".join(f"  {line[least:]}" if line.strip() else "" for line in shown)


def page(which: int, repo: Path | str = ".") -> Dict:
    """One chapter, ready for the agent to draw.

    Returned as data rather than prose because the agent has to put it into
    `AskUserQuestion` field by field, and asking a model to re-derive structure
    from a paragraph it was just given is how a page loses a topic.
    """
    which = max(1, min(which, len(CHAPTERS)))
    chapter = CHAPTERS[which - 1]
    root = Path(repo).expanduser().resolve()

    options = []
    for topic in chapter.topics:
        teaches = topic.teaches
        if topic.runs and "{}" in teaches:
            teaches = teaches.replace(
                "{}", _ran(topic.runs, root, spread=topic.spread)
            )
        options.append(
            {"label": topic.label, "description": topic.why, "preview": teaches}
        )

    return {
        "chapter": which,
        "of": len(CHAPTERS),
        "header": chapter.header,
        "question": chapter.asks,
        "options": options,
        "last": which >= len(CHAPTERS),
    }


def _kept() -> Path:
    from .home import home

    return home() / "tutorial.json"


def reached(which: int) -> None:
    """Remember how far somebody got, so `/vesta:learn` resumes."""
    try:
        path = _kept()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"chapter": int(which), "at": time.time()}), encoding="utf-8"
        )
    except (OSError, ValueError) as exc:  # noqa: BLE001
        logger.info("could not record tutorial progress: %s", exc)


def got_to() -> int:
    """The chapter to open. One, for somebody who has never been here."""
    try:
        held = json.loads(_kept().read_text(encoding="utf-8"))
        return max(1, min(int(held.get("chapter", 1)), len(CHAPTERS)))
    except (OSError, ValueError, TypeError):
        return 1


def instruction(which: int, repo: Path | str = ".") -> str:
    """The page, and what the agent must do with it.

    Told rather than asked: a page drawn as prose instead of as a dialog is a
    wall of text, which is the thing this exists to avoid.
    """
    drawn = page(which, repo)
    reached(drawn["chapter"])

    lines = [
        f"Draw chapter {drawn['chapter']} of {drawn['of']} of the Vesta "
        "tutorial with **AskUserQuestion**. One question, with exactly these "
        f"{len(drawn['options'])} options, in this order, verbatim.",
        "",
        "Do not summarise the previews, do not shorten them, and do not add "
        "an option of your own. The preview *is* the lesson — it renders in a "
        "pane beside the list, and the user reads it by arrowing down.",
        "",
        f"header: {drawn['header']}",
        f"question: {drawn['question']}",
        "",
    ]

    for n, option in enumerate(drawn["options"], 1):
        lines.append(f"--- option {n} ---")
        lines.append(f"label: {option['label']}")
        lines.append(f"description: {option['description']}")
        lines.append("preview:")
        lines.append(option["preview"])
        lines.append("")

    if drawn["last"]:
        lines.append(
            "This is the last chapter. Whatever they pick, say the tutorial "
            "is finished and that `/vesta:tutorial` starts it again. Do not "
            "draw another page."
        )
    else:
        lines.append(
            "Whichever option they pick, the page is read — the choice is how "
            "they turn it, not a question you must answer. Immediately run "
            f"`{_launcher()} tutorial {drawn['chapter'] + 1}` and draw the "
            "next chapter the same way. Say nothing between pages."
        )

    return "\n".join(lines)


def chapters() -> List[Tuple[str, List[str]]]:
    """Every chapter and its topics, for a test that keeps this honest."""
    return [(c.header, [t.label for t in c.topics]) for c in CHAPTERS]


def demonstrations() -> List[str]:
    """Every command the tutorial runs, for the test that they are read-only."""
    return [t.runs for c in CHAPTERS for t in c.topics if t.runs]
