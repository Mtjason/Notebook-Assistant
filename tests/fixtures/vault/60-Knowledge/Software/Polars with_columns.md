---
id: n-fixture-polars
type: knowledge
kind: snippet
scope: personal
status: seed
created: 2026-03-15
updated: 2026-03-15
topic: "[[MOC - Software]]"
aliases: [with_columns]
tags: [tool/polars]
---
# Polars with_columns

Use `with_columns` to add columns. It returns a new frame.

## Chaining

![[Polars with_columns - 1.png]]

See the [diagram](../../Attachments/Polars%20with_columns%20-%201.png) and [[Python os.execv]].

```python
df.with_columns(pl.col("a") * 2)
```
