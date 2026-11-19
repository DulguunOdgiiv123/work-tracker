
## Work tracker (every session)

My live task board is https://dulguunodgiiv123.github.io/work-tracker/ . Update it with the
`wt` command (`wt --help`); the data is encrypted and `wt` handles that.

- Starting real work on something I track (a report, pipeline, deck, study block): find it with
  `wt list -q "<words>"`, then `wt set <id> --status doing` (or `--progress N`). If nothing matches
  and the work is more than a one-off answer: `wt add "<short title>" --project "<project>" --status doing`.
  Reuse project names already shown by `wt list --all`.
- When that work is finished and verified: `wt set <id> --status done`.
- At the end of every request that changed something (files, reports, data, config, a sent message):
  `wt log "<what changed, about 15 words>" --project "<project>"`. Plain English, concrete. Never put
  passwords, tokens or customers' personal data in it.
- Skip all of this for pure questions, explanations and read-only investigation.
- If `wt` fails (offline, not set up on this PC), say so in one line and carry on. Never block my task on it.
- Mention the update in at most one short line at the end.
