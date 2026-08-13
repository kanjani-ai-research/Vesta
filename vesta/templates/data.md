# Data pipelines

Words for code that moves data from where it is produced to where it is used,
where a fault is usually silent and found later.

Words only. Which definitions do any of this is read from your repository —
a template has never seen your code and cannot say what it does.

domain: moving data without losing or duplicating any of it
domain: knowing whether a number is right and where it came from
domain: being able to rerun yesterday and get the same answer

activity: extract from a source
activity: parse a supplied file or feed
activity: validate a record against a schema
activity: reject or quarantine a bad record
activity: transform or derive a field
activity: join two sources
activity: aggregate over a window
activity: deduplicate
activity: load into a destination
activity: partition or bucket for storage
activity: schedule or trigger a run
activity: backfill a past period
activity: check a freshness or volume expectation
activity: record the lineage of a value

role: a source or a feed
role: a record or a row
role: a schema
role: a partition
role: a run or an execution
role: a watermark or a cursor
role: a dead-letter or quarantine store
role: a data quality check
