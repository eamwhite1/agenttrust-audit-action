# AgentTrust AI Audit — GitHub Action

Gate a pull request with an independent AI audit. The action fetches the PR diff, pays a small fee to the AgentTrust Referee, and fails the pipeline if the code scores below your threshold.

**Fee:** 0.1 XRP or $0.10 USDC on Base per audit.

---

## Quickstart

```yaml
# .github/workflows/audit.yml
name: AI Code Audit

on:
  pull_request:
    branches: [main]

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # needed to diff against base branch

      - uses: eamwhite1/agenttrust-audit-action@main
        with:
          job_spec: |
            Review this pull request for correctness, security, and code quality.
            Pass if: no obvious bugs, no hardcoded secrets, no SQL injection risk,
            functions are well-named, logic is clear.
          threshold: 70
          payment_method: xrp
          xrp_secret: ${{ secrets.AGENTTRUST_XRP_SECRET }}
```

---

## Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `job_spec` | Yes | — | Plain-English quality rubric for this repo |
| `threshold` | No | `70` | Minimum score (0–100) to pass |
| `payment_method` | No | `xrp` | `xrp` or `usdc` |
| `xrp_secret` | If XRP | — | XRPL wallet secret (`sXXX…`) — store as a GitHub secret |
| `usdc_private_key` | If USDC | — | EVM private key (`0x…`) for a Base wallet — store as a GitHub secret |
| `max_diff_chars` | No | `12000` | Truncate diff at this length before sending |
| `referee_url` | No | `https://xrpl-referee.onrender.com` | Override if self-hosting |

## Outputs

| Output | Description |
|---|---|
| `verdict` | `PASS` or `FAIL` |
| `score` | Numeric score 0–100 |
| `summary` | Plain-English explanation from the AI referee |
| `payment_hash` | Transaction hash of the audit fee |

---

## Payment setup

### XRP (recommended)
1. Create a funded XRPL Mainnet wallet (e.g. via [Xaman](https://xaman.app))
2. Add the wallet secret as a GitHub Actions secret: `AGENTTRUST_XRP_SECRET`
3. Set `payment_method: xrp` and `xrp_secret: ${{ secrets.AGENTTRUST_XRP_SECRET }}`

Keep at least 1 XRP in the wallet as reserve. Each audit costs 0.1 XRP.

### USDC on Base
1. Fund a Base wallet with a small amount of USDC and ETH (for gas ~$0.005/tx)
2. Add the private key as a GitHub Actions secret: `AGENTTRUST_USDC_KEY`
3. Set `payment_method: usdc` and `usdc_private_key: ${{ secrets.AGENTTRUST_USDC_KEY }}`

---

## Using the audit result in later steps

```yaml
- uses: eamwhite1/agenttrust-audit-action@main
  id: audit
  with:
    job_spec: 'Review for correctness and security.'
    xrp_secret: ${{ secrets.AGENTTRUST_XRP_SECRET }}

- name: Post summary as PR comment
  if: always()
  uses: actions/github-script@v7
  with:
    script: |
      github.rest.issues.createComment({
        issue_number: context.issue.number,
        owner: context.repo.owner,
        repo: context.repo.repo,
        body: `**AgentTrust Audit** — ${{ steps.audit.outputs.verdict }} (${{ steps.audit.outputs.score }}/100)\n\n${{ steps.audit.outputs.summary }}`
      })
```

---

## Writing a good job_spec

The job spec is your rubric. Be specific — vague specs produce vague verdicts.

**Good:**
```
Review this pull request for:
- Correctness: does the logic match the stated intent?
- Security: no hardcoded secrets, no SQL injection, no XSS vectors
- Tests: new functions should have corresponding tests
- Naming: variables and functions should be clearly named
Pass if all four criteria are met with no critical issues.
```

**Too vague:**
```
Is this good code?
```

---

## Resources

- [Full setup guide](https://www.cryptovault.co.uk/github-action/)
- [API docs](https://xrpl-referee.onrender.com/docs)
- [AgentTrust](https://www.cryptovault.co.uk)
- [Smithery listing](https://smithery.ai/servers/xrpl/agent-trust)
