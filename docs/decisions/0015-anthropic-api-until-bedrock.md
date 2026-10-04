# 0015: The demo uses the Anthropic API until Bedrock quota is granted

- Date: 2026-10-04
- Owner: Tarik
- Status: accepted

## Context

The plan was Bedrock with the server's role, so no key would exist on the demo server. The account is new: its Claude quota on Bedrock is 0 tokens a minute, and AWS declined a quota increase on 4 October 2026 ("account history, usage patterns; may change as time passes"). Waiting would leave the demo without a public link for weeks.

## Decision

The demo calls the Anthropic API directly (`model_provider = "anthropic"` in Terraform, the default for now). The key lives only in Parameter Store as a SecureString (`/upchirp/anthropic-api-key`), created by hand in the console, so it is never in the repo, the release archive or Terraform state. The server's role may read that one parameter and nothing else; `server-setup.sh` reads it at deploy time into the root-only env file the container uses. When Bedrock quota arrives, `model_provider = "bedrock"` swaps the parameter permission for the Bedrock one, and the key is deleted.

## Alternatives considered

| Option | Why not |
| --- | --- |
| Wait for Bedrock | No public link for weeks; the reply gave no date |
| Local model on a bigger server | A 7B model needs about 8 GB of memory: roughly $30 to $60 a month, over the $20 account limit |
| Key in the env file in the repo or in Terraform variables | A secret in git or in state |

## Consequences

A key now exists, so it can leak: it sits in the container's environment and in a root-only file on the server. Controls: one parameter readable by one role; the demo's daily spend cap ($1, `api/guard.py`) and the Anthropic account's own spend limit bound the damage; rotate the key if the server is ever suspected. Revisit when the Bedrock quota is granted.
