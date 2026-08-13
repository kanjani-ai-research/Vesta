# Networked services

Words for code that answers requests it did not initiate, over a network that
sometimes drops them.

Words only. Which definitions do any of this is read from your repository —
a template has never seen your code and cannot say what it does.

domain: answering requests correctly under load and partial failure
domain: staying available while a dependency is not
domain: knowing what a running system is doing without stopping it

activity: route a request to what handles it
activity: parse and validate a request body
activity: serialise a response
activity: read from or write to a store
activity: run a schema migration
activity: call another service
activity: retry with a backoff
activity: time out a call that will not return
activity: open or close a circuit against a failing dependency
activity: queue work for later
activity: process a background job
activity: emit a metric or a trace
activity: check whether the service is healthy
activity: read configuration for an environment

role: a request or a response
role: a route or an endpoint
role: a handler
role: a middleware
role: a connection or a pool
role: a migration
role: a background job
role: a configuration value
