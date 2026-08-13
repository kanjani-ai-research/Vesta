# How to run the trial

Two runs, one plugin each. Each is an ordinary Claude Code session — you paste
the brief and let it work.

Copy-paste everything in the boxes.

---

## Before you start

```
mkdir -p /tmp/trial/control /tmp/trial/vesta
```

---

## Arm 1 — the control (ralph-loop)

**1.** Open a new terminal:

```
cd /tmp/trial/control
claude
```

**2.** In that session, turn Vesta off and the control on:

```
/plugin disable vesta@vesta-local
```
```
/plugin enable ralph-loop@claude-plugins-official
```

Restart when prompted, then `cd /tmp/trial/control && claude` again.

**3.** Paste this, exactly:

> Build a command-line todo list.
>
> I want to be able to add a task, see my tasks, mark one done, and delete one.
> Tasks should survive between runs. Give each task a tag so I can filter by it.
>
> Python, no dependencies outside the standard library.

**4.** Let it run. Answer nothing unless it stops and asks. When it says it is
finished, type `/exit`.

**Note the time you started and finished** — the transcript gives wall clock,
but a sanity check is worth having.

---

## Arm 2 — Vesta

**1.** New terminal:

```
cd /tmp/trial/vesta
claude
```

**2.** Swap the plugins back:

```
/plugin disable ralph-loop@claude-plugins-official
```
```
/plugin enable vesta@vesta-local
```

Restart when prompted, then `cd /tmp/trial/vesta && claude` again.

**3.** Paste the **same brief**, exactly as above.

**4.** Vesta will show you a contract and wait — a short list of what it will
build. Read it.

If it says what you asked for, agree to it:

```
/vesta:agree
```

If it does not, say what is wrong in your own words and it will rewrite it.
Nothing is fixed until you agree.

**5.** Then turn driving on:

```
/vesta:drive on
```

**6.** Let it run. It will not stop until the behaviours are built and tested,
the tests pass, and nothing is outstanding. When it stops, type `/exit`.

---

## Scoring

Back in this repository:

```
cd /Users/rf/Developer/causum/v3/vesta
```

For each arm:

```
.venv/bin/python trial/probe.py /tmp/trial/control
.venv/bin/python trial/score.py /tmp/trial/control
.venv/bin/python trial/spent.py /tmp/trial/control
```

```
.venv/bin/python trial/probe.py /tmp/trial/vesta
.venv/bin/python trial/score.py /tmp/trial/vesta
.venv/bin/python trial/spent.py /tmp/trial/vesta
```

Paste all six outputs back and I will put the comparison together.

---

## If something goes wrong

- **The Vesta arm never shows a contract** — tell me. It means the spec agent
  did not fire, which is the thing that has never been tested live.
- **Either arm stops early saying it is done when it is not** — that is a
  result, not a problem. Note it and carry on to scoring.
- **An arm runs away** — Ctrl-C, note how long it ran, and score what it built.
