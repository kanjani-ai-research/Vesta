"""What Vesta is, and what a user can do with it.

Written down rather than generated. A user asking what a tool does should not
wait for inference, pay for it, or wonder whether the answer was invented — and
a guide a model writes fresh each time is a guide that can quietly describe a
command that does not exist.

**Organised by what someone wants, not by what the software has.** Nobody opens
a tool wanting to call `propagate.from_files`; they want to know what breaks if
they change a file. So each section is a question a person actually has, with
the one line that answers it.

**Every snippet here is run by the tests.** A guide that drifts from the
commands is worse than none, because it is believed. The test extracts each
`vesta …` line and checks the subcommand exists.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# Each section: the question someone has, and how Vesta answers it. The snippet
# is the whole answer — a user who reads only the snippet has lost nothing.
SECTIONS: List[Tuple[str, str, List[Tuple[str, str]]]] = [
    (
        "How do I use this at all?",
        "Two ways, and the first needs nothing from you. As a companion Vesta "
        "answers and records while you work normally — there is nothing to "
        "start. Automated mode is offered when you ask for a whole project to "
        "be built, and only then; choosing to work interactively means you "
        "are not asked again.",
        [
            ("/vesta:tutorial", "learn it a page at a time, on this repository"),
            ("vesta guide", "this, the reference"),
        ],
    ),
    (
        "Where does this repository do X?",
        "Ask in the words of the work. Vesta answers in the words of the code, "
        "which are usually different — that crossing is the point.",
        [
            ("vesta does 'retrying a failed request'", "definitions that do that work"),
            ("vesta means Graph.referenced_by", "what one definition is for"),
            ("vesta known Graph.resolve", "what earlier sessions already worked out about it"),
        ],
    ),
    (
        "What breaks if I change this?",
        "Resolved through the code rather than matched by name, so four methods "
        "sharing a name stay four methods.",
        [
            ("vesta touches src/api.py", "what a change reaches, and which tests cover it"),
            ("vesta uses admit", "where it is, what refers to it, what it refers to"),
        ],
    ),
    (
        "What am I even looking at?",
        "Before opening a file: what the repository is made of, and whether "
        "Vesta can answer about it yet.",
        [
            ("vesta shape", "composition, before reading anything"),
            ("vesta status", "whether the graph is built, and what it holds"),
            ("vesta status --prepare", "start building it, in the background"),
        ],
    ),
    (
        "How did we do this in the other project?",
        "Name another project by name or by path. The project you are in stays "
        "authoritative; the other is consulted, not merged.",
        [
            ("vesta elsewhere fuzzy search --in indexer", "how that project does it"),
            ("vesta projects", "what can be referred to, and what currently is"),
        ],
    ),
    (
        "What did I already decide?",
        "Say a rule in the course of working — \"one .env for the whole of "
        "v3\" — and it is recorded as you say it. Nothing to run, nothing to "
        "remember. These commands are for reviewing what was kept.",
        [
            ("vesta decided", "every rule this project keeps"),
            ("vesta decided --check", "whether the code still honours them"),
            ("vesta bears src/api.py", "whether a rule is in doubt for what you are about to change"),
            ("vesta learn", "candidates recovered from older sessions, if any"),
        ],
    ),
    (
        "What is worth fixing?",
        "Found without being asked, and independent of anything you have said.",
        [
            ("vesta defects", "things worth fixing, most consequential first"),
        ],
    ),
    (
        "What words is my project described in?",
        "Everything answered about the work rather than the syntax is answered "
        "in these. They are read from your code, which makes them a good first "
        "draft and a bad final answer — so they are yours to change. Removing "
        "a word removes what was attached to it, and putting it back does not "
        "restore those bindings.",
        [
            ("vesta words", "the vocabulary this project uses"),
            ("vesta words --edit", "open it in $EDITOR, one word per line"),
            ("vesta words --templates", "shipped vocabularies for common domains"),
            ("vesta words --template security", "add one; it supplies words, never bindings"),
            ("vesta words --set ours.md", "replace them from a file, so deletions take effect"),
        ],
    ),
    (
        "What was agreed, and is it built yet?",
        "Automated mode only. The behaviours are agreed before any code "
        "exists and do not move: while driving, a request that changes one is "
        "refused rather than weighed, and you choose whether to carry on, "
        "start over, or have it after delivery.",
        [
            ("vesta contract", "what was agreed, and how much of it is done"),
            ("vesta drive", "whether it is driving, and what is left"),
        ],
    ),
    (
        "What has it actually saved me?",
        "The honest accounting, kept as it happens: not what it might save, "
        "what it did — questions answered from what was already known rather "
        "than by reading the repository again.",
        [
            ("vesta used", "what Vesta was asked, and what answering cost"),
            ("vesta used --since 60", "the last hour of it"),
        ],
    ),
    (
        "What is it keeping on my disk?",
        "A graph, a vocabulary, your rules and notes, for every repository it "
        "has been used in, all under ~/.vesta. Nothing is deleted unless you "
        "ask — but a repository that no longer exists is holding space for an "
        "answer nobody can ever want again.",
        [
            ("vesta held", "what is held, per repository, biggest first"),
            ("vesta held --reclaim", "remove what belongs to repositories that are gone"),
        ],
    ),
]

# What Vesta is, in the fewest words that are still true.
PURPOSE = """Vesta answers structural questions about a repository from a
resolved graph of what refers to what, an ontology of what the work is called,
and what earlier sessions already worked out — so an agent can ask instead of
reading, and you do not pay twice for the same understanding.

Both halves are learned from the repository itself. The vocabulary comes from
what this code is for, and the rules from the corrections its own users have
made. A template can lend you words for a specialised domain, but never which
of your definitions do the work — that is read from your code every time.

You do not have to run any of it. As a companion Vesta answers your agent's
questions and records what you decide while you work normally. Automated mode,
where it agrees a contract and builds to it, is offered only when you ask for a
whole project and is never entered on your behalf."""

# Said once, at the end, because it is the thing users most often ask about a
# tool that reads their code.
STANDING = """Vesta runs on your agent's own inference. It holds no API key and
makes no network calls of its own. Everything it derives is kept under
~/.vesta and can be deleted; nothing leaves your machine."""


# Terminals are narrower than source files. A guide that runs off the right of
# the window is a guide nobody finishes reading.
WIDTH = 76


def _wrapped(text: str, indent: str = "  ") -> List[str]:
    import textwrap

    return textwrap.wrap(
        " ".join(text.split()),
        width=WIDTH,
        initial_indent=indent,
        subsequent_indent=indent,
    )


def _snippet(command: str, what: str) -> str:
    return f"  {command}\n      {what}"


def guide(topic: str = "") -> str:
    """The guide, or one section of it.

    A topic matches loosely on purpose: somebody typing `vesta guide rules`
    means the section about what they decided, and being told "no such topic"
    for a word that plainly names one is the kind of correctness nobody wants.
    """
    wanted = topic.strip().lower()
    sections = SECTIONS
    if wanted:
        sections = [
            entry
            for entry in SECTIONS
            if wanted in entry[0].lower()
            or wanted in entry[1].lower()
            or any(wanted in c.lower() or wanted in w.lower() for c, w in entry[2])
        ]
        if not sections:
            known = "\n".join(f"  {title}" for title, _, _ in SECTIONS)
            return f"Nothing in the guide about {topic!r}. It covers:\n{known}"

    lines: List[str] = []
    if not wanted:
        lines.append("Vesta")
        lines.append("")
        # Paragraph by paragraph: wrapping the whole thing at once runs two
        # separate points together into one block nobody finishes.
        for paragraph in PURPOSE.split("\n\n"):
            lines.extend(_wrapped(paragraph, ""))
            lines.append("")

    for title, why, snippets in sections:
        lines.append(title)
        lines.extend(_wrapped(why))
        lines.append("")
        for command, what in snippets:
            lines.append(_snippet(command, what))
        lines.append("")

    if not wanted:
        lines.extend(_wrapped(STANDING, ""))
    return "\n".join(lines).rstrip() + "\n"


def commands() -> List[str]:
    """Every command the guide shows, for a test that keeps it honest."""
    return [command for _, _, snippets in SECTIONS for command, _ in snippets]
