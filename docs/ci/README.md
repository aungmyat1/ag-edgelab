# CI definitions pending promotion

`crypto-mtf-smc-r0.yml` is verbatim the GitHub Actions workflow for the
ST_CRYPTO_MTF_SMC_V1 R0 guard (fixture byte-determinism + pinned-manifest sha
check + full pytest + dev-run smoke).

It is *not* active: the automation token used to push this branch lacks the
`workflows` OAuth scope, and GitHub refuses pushes that create/update files
under `.github/workflows/` without it. To enable the guard, move this file to
`.github/workflows/crypto-mtf-smc-r0.yml` in a commit authored with the
`workflows` permission (any maintainer push will do) — no other change needed.
