# The Witness Record

**Version 1. Status: draft.**

A witness is a compact record of one invocation, its one output, and whether the
reasoning that produced it was sound. It exists so that a party who did not run
the process, cannot see the repository, and does not trust the environment can
still judge the quality of a decision.

This document specifies what a witness must contain for that judgement to be
possible, what may be added, and what the record cannot establish however
complete it is.

---

## 1. What a witness is for

A reader receiving a witness for a decision that turned out badly must be able
to attribute the failure. Four attributions are possible and the record exists
to separate them:

| | attribution | owner |
|---|---|---|
| **A** | the specifications in force, the arrangement selecting them, or the vocabulary were inadequate | whoever supplied and certified them |
| **B** | the narrowing was insufficient | the deployment |
| **C** | the process was sound; the outcome was wrong in a way nothing could catch | nobody |
| **D** | the environment was degraded — the inputs did not describe the subject | the deployment's environment |

A field is **required** if removing it makes one of these attributions
impossible. A field that improves a reader's confidence without changing which
attribution they can reach is **optional**.

That test is the whole of this specification's design rationale. Where a
requirement below seems severe, it is because a reader who cannot make one of
these four distinctions has a record that reads as evidence and is not.

### 1.1 What a witness is not

A witness does not establish that a decision was **correct**. A process can be
sound in every respect specified here and reach a wrong conclusion. What it
establishes is conformance: that the decision was reached in a checkable shape,
against specifications stated in advance, and — read according to its mode
(§3.3) — arrived where those specifications said it should.

A witness is also not the reasoning. It is a verdict on the reasoning, computed
while the reasoning was in hand and retained in its place (§7).

---

## 2. Terms

**Decision space** — the set of candidate subjects a decision could have
concerned, at some moment. For a change to code, the definitions that could be
the one changed.

**Narrowing** — a sequence of contractions of the decision space, each with
recorded reasons.

**Step** — one measurement of the decision space: how many candidates remained,
how many outputs were still admissible, and the judgements that ruled the rest
out.

**Judgement** — one candidate excluded, demoted, or left undecided, with a
reason and a basis.

**Basis** — what a judgement rests on, and therefore whether re-running it means
anything. See §5.

**Specification** — one indivisible unit of work, function, or intention,
stated as content a person can certify (§8.1). The **specifications in force**
for a decision are the ones governing it — selected directly, or by a program.
Their authority rests on having been stated before the decision they are
applied to; whether they were is asserted rather than evidenced, except where
§4.5 applies.

**Program** — an arrangement of specifications: references to them by content
digest, selection among them by the context of a decision, and resolution of
conflicts between them. A program is itself a specification (§8.8).

**Predicted region** — where the specifications in force, crossed with the
stated intent, say the decision belongs. Computed **before** the narrowing and
from a different source. See §4.

**Mode** — how the narrowing related to the predicted region: **blind**, never
shown it, so that its landing is evidence; or **guided**, steered by it, so
that departures are addressed at the step they occur and the signal moves to
the interventions. See §3.3, §6.6.

**Intervention** — one occasion, in guided mode, on which guidance reduced a
candidate's standing against the evidence-based disposition of that candidate,
recorded at the step it occurred. See §3.7, §5.3.

**Friction** — the frequency of interventions relative to judgements; the
guided mode's correctness signal. See §6.6.

**Vocabulary** — the terms a subject is described in, and their bindings to
parts of the subject. The predicted region is read through it.

**Adjudication** — a person's attestation that they checked the work a
specification will cause to be carried out. See §8.

---

## 3. Required content

A conforming witness carries the following. Each entry states what attribution
becomes impossible without it.

### 3.1 `format_version` — integer

The version of this specification the record follows.

*Without it:* a reader applying a later version's checks to an earlier record
cannot distinguish a check that **failed** from one that **did not exist**. This
mis-attributes systematically and silently, which is worse than an absent
record.

### 3.2 `intent` — string

What was asked, in the words it was asked in.

*Without it:* attribution **A** is unaskable. A specification's adequacy is
always adequacy *for some request*; with no request there is nothing to judge
it against.

### 3.3 `mode` — one of `guided`, `blind`

Whether the narrowing was steered by the predicted region or never shown it.

The two modes carry their correctness signal in different elements, and neither
may be read through the other's instrument. A blind landing inside the region
is the agreement of two independent derivations — evidence. A guided landing is
partly by construction, and its signal is the friction and the out-of-region
survivors instead (§6.6).

A blind-mode record MUST NOT carry interventions: there is nothing to intervene
with, and their presence marks the record malformed.

*Without it:* a guided landing borrows evidential weight it has not earned, and
friction figures are uninterpretable — blind mode never generates any.

### 3.4 `narrowed` — sequence of integers

The size of the decision space after each step, in order.

Required as a **sequence**, not as endpoints. `[900, 899]` and `[900, 3]` are
different deployments, and any single ratio conflates them.

*Without it:* attribution **B** collapses into **C**. There is no trajectory, so
no way to say the narrowing was poor rather than the problem merely hard.

### 3.5 `population` — integer

The size of the decision space before anything was applied.

*Without it:* `narrowed` is uninterpretable. Contracting 900 candidates to 3 in a
subject of 900 and in a subject of 900,000 are different facts.

### 3.6 `predicted` — integer

The size of the predicted region (§4).

*Without it:* the bounds check is uninterpretable, which is the largest blind
spot available to a reader. Specifications whose predicted region covers the
entire population admit any landing; ones covering a single candidate admit
almost none. **Both record identically without this count, and both pass every
other check.** This is demonstrated, not hypothetical.

### 3.7 `interventions` — count, and a record per intervention

Required where the mode is `guided`; MUST be absent where it is `blind` (§3.3).

Each intervention records: the step at which it occurred, the identity of the
candidate, the evidence-based disposition that guidance overrode, and the
action taken. The interventions are few when the specifications and the
subject's evidence agree, and they are precisely the informative events.

*Without it:* guided mode's attributions are unreachable. Friction is the
guided-mode signal (§6.6), and the A-versus-B question — did the specifications
drag the decision wrongly, or did the narrowing resist sound guidance — is
answered from the intervention records or not at all.

### 3.8 `specifications` — one entry per specification in force

For each specification in force: a digest of its content as it stood when the
decision was made, and the adjudication in force for it at that time — the
type, and whether the certification was direct or inherited (§8).

*Without the digests:* attribution **A** is unfalsifiable in both directions. A
supplier may edit a specification after a bad outcome and claim the deployment
misread it; a deployment may claim the specification said something it did not.

*Without the snapshots:* the assurance behind the governing content is
invisible, and re-adjudication after the fact silently changes what an old
record appears to claim (§8.7).

*Compatibility:* an implementation predating this element that records a single
`standard_digest` conforms at Level 1 where exactly one specification is in
force directly, with no program; the plural element supersedes it.

### 3.9 `program` and `conflicts`

Where an arrangement selected the specifications in force: a digest of the
program's content, and, for every conflict detected among the specifications in
force, the conflict and the resolution applied. Where a single specification
governs directly, the record states that no program was in force — a recorded
absence, per §3.14, not an empty digest.

*Without the program digest:* the governing arrangement of the decision is
unreconstructible, and a failure of the arrangement — a wrong selection, a
wrong precedence — cannot be attributed to the arrangement's owner as distinct
from a component's.

*Without the conflict records:* a conflict between certified specifications is
silently resolved, destroying exactly the information their owners need. A
conflict is a fact about the specifications, not an inconvenience of the run.

### 3.10 `vocabulary` — string

A digest of the vocabulary's content as it stood when the decision was made.

The digest must be **content-derived**, over the terms themselves, and stable
under reordering. A vocabulary edited by hand — a term removed, another
rephrased — is a different vocabulary at the same size, and that is precisely
the edit somebody makes when they disagree with what was derived.

*Without it:* "the specification was wrong" cannot be separated from "the
specification was sound but the vocabulary interpreting it had drifted". Those
have different owners.

### 3.11 `inputs_digest` — string

A digest of the inputs the narrowing actually ran over — for code, the resolved
graph of definitions and references.

This must bind the **inputs**, not a proxy for them. A version-control revision
is not sufficient: a working tree may differ from any committed revision, and a
cached or partially-built input set differs from both.

*Without it:* two records over different inputs are indistinguishable, so no
statement about the narrowing can be tied to what it ran over.

A digest binds *which* inputs were used. It does not say whether they were
**complete**, and a reader has nothing to compare a digest against — which is
why §3.12 is required beside it.

### 3.12 `inputs_resolved`, `inputs_unresolved` — integers

How much of the subject the inputs describe: the units successfully resolved,
and the units that could not be.

*Without it:* attribution **D** is unreachable. A deployment that narrowed
badly over sound inputs and one that narrowed faithfully over inputs missing
half the subject produce records that differ only in a digest a reader cannot
interpret. The second is not a bad decision; it is a decision made in the dark,
and the distinction has a different owner.

This is a required field precisely because the failure is silent: an input set
that resolved nothing yields a decision space that looks small and a narrowing
that looks decisive.

### 3.13 `findings` — sequence of findings

Each finding names a check (§6), whether it held, and a detail.

Required in full rather than reduced to an overall verdict: *which* check failed
determines which attribution is implicated. A failed bounds check points at
**A** or **B**; a failed accounting check points at **B**; a failed authority
check points at **B** specifically. A single sound/unsound verdict points
nowhere.

### 3.14 Absent inputs are not satisfied inputs

A field required above MUST NOT be recorded empty in place of the thing it
names. An implementation that cannot supply one MUST record the witness as
having been made without it, and a reader MUST NOT read a soundness verdict on
such a record as covering the missing input.

*Demonstrated:* a witness carrying no specifications and no vocabulary at all
passes every check in §6, because §6.6 holds vacuously where nothing was
predicted (§4.4). Nothing else in this document would stop it certifying clean.
A record that establishes nothing must not be indistinguishable from one that
establishes something, and the absence must be legible in the verdict rather
than only in an empty field a reader may not think to look at.

---

## 4. The predicted region

This is the mechanism by which a witness says anything about correctness rather
than only about shape, and its requirements are correspondingly strict.

### 4.1 It must be derived before the narrowing

The region is where the specifications in force, crossed with the intent, say
the decision belongs. Its entire evidential value rests on being **prior** — a
region derived after the fact, from the result, is a restatement of the result.

### 4.2 It must be derived from a different source

The prediction is read from the specifications' own words against the
vocabulary. The narrowing runs over the inputs. Two derivations from two
sources agreeing is evidence; a chain checked against its own inputs is not.

### 4.3 It must not be expanded

Where the narrowing traverses relationships in the inputs, the prediction must
not. A prediction that expands into the same neighbourhood the narrowing reaches
puts both sides in the same region, where agreement is guaranteed by
construction.

*Measured:* on one subject, a region of 60 named definitions became 355 after a
single hop of expansion — nearly half that subject, and loose enough to admit
almost any landing. And a region admitting everything occasions no
interventions, so in guided mode the friction signal dies with the
discrimination.

### 4.4 An absent prediction is not a violation

Where the specifications' vocabulary reaches nothing in the subject, they
predict nothing. A record must distinguish **no prediction** from **an empty
prediction**: the first says the specifications have nothing to say about this
work, which is frequently true; the second says the decision belongs nowhere,
which almost never is.

Treating an absent prediction as a failed bounds check reports an inapplicable
specification as a violated one.

### 4.5 Under distrust, the prediction should be recomputable

§4.1 is an ordering claim, and no field can carry it: a reader has only the
deployment's word that the region was derived in advance.

Where a reader can **recompute** the prediction from the specification digests
(§3.8), the program digest (§3.9), `vocabulary`, and `inputs_digest`, the
prediction stops being an assertion and becomes a check. Implementations
intended for use under distrust SHOULD make the derivation reproducible from
those digests alone. This is the single most valuable property a conforming
implementation can add, and it is what makes the bounds check meaningful to a
reader who trusts nothing.

### 4.6 Provision to the narrowing does not breach derivation

In guided mode the region is provided to the narrowing. This does not violate
§4.2 — the *derivation* remains independent of the narrowing in both direction
and time — but it changes what the final correspondence evidences, which is why
the mode is a required element (§3.3) and why §6.6 states two readings.

---

## 5. Basis

Every judgement MUST record what it rests on. The set is closed, and each member
states exactly what re-running it establishes.

Where an implementation defaults an unstated basis, it MUST default to the
weakest — the one claiming that nothing can be re-run. A basis nobody stated is
not one to infer on their behalf, and defaulting the other way lets a record
imply that reasoning is checkable when it is not.

| basis | re-running establishes |
|---|---|
| `structural` | whether the property still holds — a predicate over the inputs |
| `byte` | whether the content is unchanged — a comparison against a recorded digest |
| `evaluated` | whether it **still evaluates the same way** — not whether it holds |
| `asserted` | nothing; no record of what was considered exists |

The distinction between the last two is the evidence. An evaluated judgement
carries what it was shown, so a reader may argue with the inputs; an asserted one
carries nothing, so a reader may only take it or leave it.

### 5.1 Pooled judgement is bounded

Where a judgement is `evaluated` — reached by consulting an authority rather than
by computation — it MUST NOT be permitted to exclude a candidate from the
decision space. It may lower a candidate's standing; it may not remove it.

The reason is that an evaluated verdict is never certain: the same authority over
the same evidence may reach a different view on another occasion. Permitting one
to exclude would let a wrong judgement silently remove the right answer with no
route back.

That a run honoured this bound is itself checkable (§6.4), which makes it the
strongest available check on the part of the reasoning that cannot be
re-verified.

### 5.2 A record states its own pooled share

A witness MUST state how its reasoning divides across the four bases — how much
was computed, how much evaluated against an authority, and how much merely
asserted.

Stating only the pooled share is insufficient. **Demonstrated:** a witness in
which *every* judgement is `asserted` — nothing re-runnable, nothing recorded of
what was considered — passes every check in §6 and reports a pooled share of
zero, which reads as though nothing were pooled. The least verifiable record
possible is indistinguishable from the most verifiable one unless all four
counts are present.

A reader MUST NOT read a soundness verdict as evidence about reasoning that is
`asserted`. The checks in §6 establish that a narrowing had a sound *shape*; they
say nothing about judgements whose grounds were never recorded.

### 5.3 Guidance is bounded

In guided mode, an intervention rests on the predicted region — on what the
specifications say — and it is bounded exactly as pooled judgement is: it MUST
NOT exclude a candidate from the decision space. It may lower a candidate's
standing; it may not remove it.

The rationale is parallel and the parallel is the point. A specification's
adequacy is precisely what attribution **A** exists to question; were guidance
permitted to exclude, an inadequate specification would remove the *correct*
answer irrecoverably while producing a clean-looking record. Bounded to
demotion, a wrong specification costs rankings — and a candidate whose evidence
survives the demotion becomes the record's strongest flag (§6.6).

Together, §5.1 and §5.3 state one principle: **only a judgement resting on
deterministic evidence about the subject — `structural` or `byte` — may exclude
a candidate. Every other authority may re-rank; none may remove.** That a run
honoured the whole principle is checkable (§6.4, §6.7).

---

## 6. Checks

A conforming implementation MUST run these against the completed narrowing and
record each result in `findings`. Each is arithmetic over the narrowing's shape;
none is a judgement about the subject, and none may require re-running the
decision.

### 6.1 The space contracted

The decision space must be materially smaller at the end than at the start.

**Materially** is required. A check satisfied by any decrease is satisfied by a
deployment that rules out one candidate of nine hundred — demonstrated to pass
every other check while deciding nothing.

Implementations MUST define a minimum contraction as a share of `population` and
MUST record the threshold used in the witness. The threshold is deliberately not
fixed here: what counts as material depends on the subject, and a value chosen
in this document would be wrong for somebody's. **The consequence is that
witnesses from implementations using different thresholds are not comparable on
this check**, and a reader comparing across deployments MUST read the recorded
thresholds before treating two held checks as equivalent.

### 6.2 Every narrowing was accounted for

Every candidate that left the space must have a recorded judgement that removed
it.

The check MUST compare **identities**, not counts. Comparing counts alone is
satisfied by a step that records eighty exclusions naming arbitrary candidates
while eighty different candidates vanish — demonstrated.

### 6.3 Nothing excluded returned

A candidate soundly excluded MUST NOT reappear in the space. Reappearance means
either the exclusion was wrong or the space was rebuilt from elsewhere, and a
reader must be able to tell which they are looking at.

Every exclusion MUST carry a recoverable identity for the candidate it removed.
A check that can only compare candidates it can name passes vacuously over
exclusions that name nothing — so an implementation that omits identities does
not fail this check, it evades it.

### 6.4 No pooled judgement closed the space

No `evaluated` judgement excluded a candidate (§5.1).

### 6.5 The output rests on what survived

Something MUST have remained admissible for the output to rest on. A conclusion
drawn from an empty space came from outside the narrowing — the shape of an
answer decided elsewhere and narrated afterwards.

This check is deliberately weak: it catches only the case where *nothing*
survived. It does not establish that the output concerns what survived, which
would require interpreting the output and is beyond what arithmetic over a
narrowing can do. An implementation able to bind the output to particular
surviving candidates SHOULD do so, and a reader MUST NOT read this check as
establishing that binding.

### 6.6 The narrowing stayed within the predicted region

Every surviving candidate MUST lie inside the predicted region (§4).

Where no region was predicted, this check holds and MUST record that no
specification predicted a region — not that the narrowing conformed.

**The check has two readings, and the mode (§3.3) says which applies.** In
blind mode, a held check is the agreement of two independent derivations and is
the record's primary correctness signal. In guided mode, a held check is partly
by construction and MUST NOT be presented with blind-mode weight; the guided
signals are instead the **friction** — interventions relative to judgements,
where a low figure is the same two-source concurrence observed through a
different instrument — and any **out-of-region survivor**: a candidate whose
evidence outlasted guidance's demotions, which is the strongest single flag the
guided mode can raise, and which exists only because §5.3 forbade guidance to
remove it.

A reader can re-run this check only against the region's **members**, which
`predicted` (§3.6) does not carry. An implementation whose witnesses are
intended to be re-checked rather than read MUST carry the membership, or make
it recomputable under §4.5. Carrying only the count leaves the check
re-readable and not re-checkable, and the difference is the whole distance
between a record and evidence.

### 6.7 Guidance stayed within its bound

In guided mode: no intervention excluded a candidate (§5.3), and every
departure from the region was either intervened upon at its step or is
accounted for by a recorded out-of-region survivor. In blind mode this check
holds and MUST record that the mode was blind — not that guidance behaved.

---

## 7. The narrowing itself is not carried

A witness records the verdict on the reasoning, not the reasoning.

The checks in §6 are computed while the narrowing is complete and in hand. What
is retained is the finding and the facts supporting it. A conforming
implementation MAY retain the full narrowing locally, and if it does the witness
MAY carry a reference to it, but no property specified here may depend on that
reference being resolvable.

The interventions of §3.7 are part of the witness, not of the chain: they are
few when the process is healthy, and they are precisely the informative events.
Carrying them does not reintroduce the chain.

*Rationale, measured on one subject.* Retaining every judgement produced a record
of **303kb** for a single invocation — 730 judgements carrying three distinct
reasons between them, one repeated 710 times, with 91% of the record being the
judgements. Compressing that redundancy brought it to 93kb, which is a smaller
record of the wrong thing. Retaining the verdict and its supporting facts instead
came to **4.2kb**, with the full narrowing kept separately at 78kb for anyone who
wanted it.

A record too large to keep is a record nobody keeps, and a trail nobody keeps
answers nothing.

---

## 8. Adjudication

Adjudication is a mechanism over the vocabulary and specifications. It is
**independent of the witness**: it exists, and is useful, whether or not any
decision is ever recorded. A witness carries its result.

### 8.1 The unit is a specification

The adjudicated unit is one indivisible unit of work, function, or intention. It
may be simple or complex; it may be a single aspect of a vocabulary or a
combination of aspects and slices of several.

The unit is **functional, not structural**. Its boundary is what a person can
meaningfully certify: nobody can attest to a term in isolation, but a person can
attest to a way of doing a kind of work.

Indivisibility is therefore a property of the certification, not of the content,
and this document gives no structural test for it. The operative question is
whether a certifier could check *half* of the unit and have that mean anything;
where they could, it is two units. This places the judgement with the owner, who
is the only party positioned to make it, and an implementation MUST NOT infer
unit boundaries from the structure of a vocabulary.

### 8.2 Specifications may fork

One unit may exist in several versions, reflecting several ways of performing
the same function. Forks are of the same thing and are independently
adjudicable. Forks may conflict; where forks or distinct specifications are
jointly in force, conflicts between them are detected and recorded (§3.9), not
silently resolved.

### 8.3 Adjudication is certification

Adjudication is not approval of a document. It is a person attesting that **they
checked the work the specification will cause to be carried out**. That is why
its result travels into a witness: the record then states not merely that a
specification existed, but that a qualified party certified this way of working.

### 8.4 Adjudication is typed

The type states how much authority backs the certification, and corresponds to
the topology of the deployment:

| type | typical deployment |
|---|---|
| single member | one machine, one person |
| single expert | shared, a designated authority for a team |
| consensus of experts | distributed, agreement required |
| multi expert | distributed, several independent certifications |
| multi authority | distributed, several authorities required |
| key ceremony | certification in the presence of the parties at the time of use |

A reader weighing a specification needs the type: one certified by a single
person on a laptop and one certified under ceremony by three experts are
different levels of assurance about the same words.

### 8.5 Inheritance is defined by the owner and marked by the system

A fork may inherit adjudication rather than receive its own. Whether it does is
the owner's decision. **That it did MUST be recorded.**

A reader must always be able to distinguish a direct certification from an
inherited one. Silently equating them overstates assurance, and the overstatement
is invisible.

### 8.6 Certification should be anonymous and verifiable

A certifier's identity is usually not the reader's business; that a qualified
party certified is. Implementations intended for use under distrust SHOULD permit
a reader to verify that certification occurred, and by a party holding a stated
authority, without disclosing which party.

### 8.7 A witness carries a snapshot

A witness carries the adjudication in force for the specifications it relied on,
**as it stood at the time**. Re-adjudicating later must not silently change what
an existing record claimed.

### 8.8 A program is itself a specification

An arrangement of specifications — selecting among them by context, sequencing
them, resolving conflicts between them — expresses one unit of intention and is
therefore itself a specification, with everything that entails.

It is adjudicable in its own right, and must be: **certifying the components
does not certify the arrangement**, which is new intention that no component
certifier examined. It may fork, and inherit with marking (§8.5). It references
its components **by content digest**, so a change to any component is a new
version of the program, for which a prior certification does not stand — the
same rule as any edited specification.

The witness carries the program's digest and, per component in force, the
digest and adjudication snapshot (§3.8–3.9), so the governing arrangement of
every decision is exactly reconstructible and its failures attributable to the
arrangement's owner or a component's.

---

## 9. Circulation

A witness is intended to be read by a party who did not produce it. The
properties below follow from that and from nothing else; an implementation whose
records never leave the machine that wrote them may omit them.

### 9.1 Tamper evidence

A reader must be able to detect that a witness, or the decision it describes, has
been altered since it was written.

The digests in §3.8–3.11 provide part of this: they bind a record to its
specifications, its program, its vocabulary, and its inputs, so an alteration
to any of those is detectable. They do not protect the record itself. An
implementation intended for circulation MUST bind the witness's own content so
that alteration is evident.

### 9.2 Tamper evidence must not be brittle

A verification that fails for benign reasons — reformatting, re-serialisation,
field reordering — teaches readers to disregard verification, which is worse than
having none. What is bound MUST be the record's content, not its byte
representation.

An implementation MUST specify the canonical form it binds, and two
implementations claiming interoperability MUST agree on it. This document does
not fix one: doing so would embed a serialisation choice in a specification about
evidence, and the wrong choice is harder to withdraw than an unmade one. The
requirement is that the form be *stated*, not that it be any particular form —
an unstated canonicalisation is the brittleness this clause exists to prevent,
arriving one layer down.

### 9.3 Circulation requires access control

Posting a witness, and acquiring one, require a party to be identified as
entitled to do so. An implementation intended for circulation MUST specify how a
deployment is authorised to post and how a reader is authorised to acquire.

These are not independent features. A repository of decisions exists so that
parties who were not present can rely on them; reliance requires tamper evidence;
tamper evidence requires binding content to keys; keys require an access
mechanism. Each is load-bearing for the next.

---

## 10. Optional module: sources and acquisition

The sections above assume one input set describing one subject. This module
extends the format to a plurality of **sources** — of candidates, of knowledge,
and of context — without changing any mechanism in kind. It is optional at
every conformance level; a witness MUST record whether it is in effect, per
§3.14's rule that an absence must be legible.

### 10.1 Sources, and the two roles

A source serves one or both of two roles, which enter the mechanism at
different points and MUST NOT be conflated: a **candidate source** contributes
members to the decision space; an **evidence source** supplies material
consulted during judgement — what is placed before an evaluated consultation,
or checked deterministically.

Each source is registered with: an identity and a content digest — or, for a
live source, a digest taken at each use; its declared role or roles; its form
(§10.2); its own `resolved`/`unresolved` completeness measures; and its
provenance.

### 10.2 Forms; encodings optional

A source's material may be **structured** — a property graph of parts and
relations; **raw**; or **partitioned into chunks with vector encodings**. No
mechanism in this document requires any particular form, and none requires
vector encodings — this format has a reduction to practice whose only sources
are a resolved property graph and structurally mined session history, holding
no encoding model. Neither is the encoded form excluded: an encoded store may
serve as an evidence source, its acquisition procedure being the query
evaluated against it.

The history of the deployment's own operation, and its artifacts — code
structured as a property graph of definitions and references; files and stated
intentions structured as a property graph of knowledge — are admissible
sources, under the same registration as any other.

### 10.3 The mapping is specification content

The vocabulary and specifications MAY bind meaning not only to parts of a
subject but to **individual sources** and to **acquisition procedures** against
them — associations between terms or intents and (source, query) pairs,
expressed as natural-language instructions or as mappings between the
vocabulary's metadata and the source's metadata.

Such a mapping is specification content, and inherits the whole of §8: it is
certifiable, forkable, inheritable with marking, and it lapses with its digest.
Under a certified mapping, what must be retrieved, and from where, is part of
the certified way of working rather than an implementation habit.

### 10.4 Acquisition is recorded

Each acquisition procedure applied MUST be recorded with the judgement it
informed. An evaluated judgement later found wrong thereby becomes disputable
down to the query that fetched its inputs — a wrong mapping, a degraded source,
and a wrong consultation are separable failures with separate owners, and a
record without the query cannot separate them.

### 10.5 Accounting generalizes per source

Under this module the witness generalizes element-wise: `inputs_digest` (§3.11)
carries a digest **per source**, and the completeness measures (§3.12) are
carried **per source** — so attribution **D** names *which* source was
degraded rather than reporting the inputs inadequate in aggregate.

Where candidates derive from several candidate sources, a predicted region is
derived per source through that source's bindings and joined under a recorded
treatment; §4.3's non-expansion applies within each source.

---

## 11. Conformance

**Level 1 — recordable.** §3, §5, §6, §7. A witness a reader can use to
attribute a bad outcome, given that they trust the environment that produced it.

**Level 2 — adjudicated.** Level 1, plus §8. Certification of the specifications
relied on, typed, with inheritance marked.

**Level 3 — circulating.** Level 2, plus §4.5 and §9. A witness a reader can use
without trusting the environment that produced it.

The **mode is orthogonal to the levels**: either mode may run at any level, and
the mode element (§3.3) governs how §6.6 is read wherever the record travels.
The **sources module (§10) is optional at any level**, and its presence or
absence is recorded.

An implementation MUST state which level it claims, and a witness MUST record the
level it was written at, alongside `format_version` (§3.1). A reader applying a
higher level's expectations to a lower-level record must not mistake an absent
property for a failed one — the same failure §3.1 exists to prevent, at the scale
of the whole document.

**§6.6 at Level 1 is present, not meaningful.** A Level 1 implementation runs the
bounds check against a prediction it asserts was derived in advance, and a reader
has only its word (§4.1, §12). The check becomes evidence rather than assertion
only at Level 3, where §4.5 makes the prediction recomputable. Implementations
claiming Level 1 MUST NOT present a held bounds check as establishing that the
narrowing conformed to its specifications — only that it conformed to a region
the implementation reported. And in guided mode the check is additionally partly
by construction at *every* level (§6.6): the friction and the out-of-region
survivors carry the guided signal.

---

## 12. Stated limits

A conforming implementation must not claim more than the following.

**Conformance, not correctness.** Everything specified here establishes that a
decision was reached in a checkable shape against specifications stated in
advance. A specification that is wrong about its subject predicts the wrong
region confidently, and a narrowing that lands there conforms. Attribution
**A** exists precisely because this is possible.

**A guided landing is not evidence of agreement; friction is.** In guided mode
the narrowing was steered, and its arrival in-region must never be given the
evidential weight of a blind landing. The mode element enforces the
distinction; the intervention records and any out-of-region survivors carry the
guided mode's signal.

**Pooled judgement re-evaluates; it does not re-verify.** Where a judgement is
`evaluated`, asking again may yield a different view with nothing having changed.
A discrete representation — conditions that evaluate to true or false rather than
to a view — would make such judgements re-verifiable. Its requirements are
substantially heavier: little of what a specification asks for reduces to a
decidable condition over a subject's structure, so requiring one yields a small
set of trivially checkable conditions and silently discards everything else.
That is narrower rigour wearing the appearance of more. An implementation
needing the stronger property needs the discrete representation, and that is a
different system than this one.

**Ordering is asserted unless recomputable.** §4.1 requires the prediction to
precede the narrowing, and no field can evidence it. Only §4.5 converts the claim
into a check.

**Vocabulary adequacy is partly unquantified.** A reader can see the share of the
subject a specification's region covered, and the share the vocabulary names at
all. Whether those figures are comparable **between** subjects is not
established: a subject organised behind a narrow interface may legitimately bind
less of itself than one that is not.

Nor is within-subject comparison established. It is *plausible* that the same
subject's coverage rising or falling over time means something, and one
observation is consistent with it — a vocabulary covering 12% of a subject
predicted regions that missed work the subject demonstrably performed, and at
56% it did not. One observation is not a finding.

Implementations SHOULD report these figures and MUST NOT present either
cross-subject or within-subject comparison as established.
