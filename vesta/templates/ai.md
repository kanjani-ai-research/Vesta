# Model-backed systems

Words for code built around inference, where the expensive step is
non-deterministic, charged for, and occasionally wrong.

Words only. Which definitions do any of this is read from your repository —
a template has never seen your code and cannot say what it does.

domain: getting useful work out of a model that is sometimes wrong
domain: keeping the cost of inference proportionate to what it produces
domain: knowing what a system did and why, when the deciding step is opaque

activity: build a prompt
activity: call a model
activity: parse or validate a model's answer
activity: retry or fall back when an answer is unusable
activity: choose which model does a piece of work
activity: count or budget tokens
activity: cache a result to avoid paying for it twice
activity: embed a text
activity: retrieve by similarity
activity: chunk a document for retrieval
activity: rank or re-rank candidates
activity: expose a tool for a model to call
activity: hold a conversation's history
activity: evaluate an answer against a standard
activity: guard against an injected instruction

role: a prompt or a template
role: a model response
role: an embedding
role: a chunk or a passage
role: a tool definition
role: a conversation or a session
role: a token budget
role: an evaluation case
