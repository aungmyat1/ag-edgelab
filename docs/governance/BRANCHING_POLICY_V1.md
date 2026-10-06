# Branching Policy V1

## Names

Name branches `<type>/<scope>`, where `<type>` is one of `feat`, `fix`,
`chore`, `research`, `structure`, or `governance`. Keep the scope concise and
recognizable.

## Limits and lifecycle

- Keep no more than two open branches per agent lane.
- Delete merged branches within 24 hours, after creating and pushing an
  `archive/<branch-name>` tag at the branch tip.
- Merge or archive every `arena/*` branch within 72 hours. An archive tag must
  be pushed before deleting its remote branch.
- Never delete a branch with an open pull request. Verify pull request state
  through authenticated GitHub access before any deletion; if state cannot be
  verified, do not delete.

## Reporting

The branch hygiene workflow is report-only. It inventories remote branches and
open pull requests; it does not create tags, merge, or delete branches.