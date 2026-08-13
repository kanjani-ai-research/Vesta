# Security-sensitive code

Words for the parts of a system where an input is hostile until proven
otherwise, and where the difference between checking something and appearing to
check it is the whole subject.

Words only. Which definitions do any of this is read from your repository —
a template has never seen your code and cannot say what it does.

domain: deciding whether a request may do what it is asking to do
domain: keeping a secret secret while still being able to use it
domain: being able to say afterwards what happened and who did it

activity: authenticate a caller
activity: authorise an action against a policy
activity: validate an untrusted input
activity: escape or encode before handing on
activity: parse an untrusted document
activity: issue a credential or a token
activity: verify a signature or a token
activity: hash or derive a key
activity: encrypt or decrypt
activity: hold or fetch a secret
activity: rotate or revoke a credential
activity: record an audit event
activity: limit a rate or a quota
activity: redact before logging or displaying

role: a credential
role: a session
role: a principal or an identity
role: a permission or a policy rule
role: a trust boundary
role: an audit record
role: a cryptographic key
role: an untrusted input
