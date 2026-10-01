# Market Scanner (deployment)

Portable start for Market Scanner. This repo holds only the compose file and PowerShell scripts.
The application lives in [maxh8086/market-scanner](https://github.com/maxh8086/market-scanner) and the
databases and LLM server in the shared infra
[maxh8086/shared-market-research-Infra](https://github.com/maxh8086/shared-market-research-Infra).
Both are cloned for you on first start.

## Requirements
Git, Docker (Compose v2.20+), PowerShell 5.1+ or 7. An NVIDIA GPU with the container runtime for
vLLM (use `-NoLlm` without one).

## Start
```powershell
git clone https://github.com/maxh8086/market-scanner.git
cd market-scanner
./start.ps1
```
`start.ps1`, in order:
1. clones the infra into `infra/` if absent (set `MARKET_INFRA_DIR` to reuse an existing checkout shared with other projects),
2. clones the app into `app/` if absent,
3. downloads model weights on first run (about 9 GB), then runs the infra's `up.ps1 -Project market_scanner -Llm`,
   which starts Postgres, MongoDB, Neo4j and vLLM and creates this project's isolated logins,
4. builds and starts the UI and collector with docker compose.

Open http://127.0.0.1:8080. The first visit asks for the API keys (Upstox token required, others optional);
change them any time under **API keys**. Keys are kept in `app/data/secrets.env`, never in git.

| Switch | Effect |
|---|---|
| `-NoLlm` | skip vLLM (Neo4j still starts) |
| `-Update` | `git pull` the infra and app clones first |

vLLM is in the default start for now and may be replaced by OpenRouter in a later phase.

## Other scripts
- `./stop.ps1` stops the app; `./stop.ps1 -Infra` also stops the databases and vLLM. Data is kept.
- `./reset.ps1` deletes all database and app data after a `YES` prompt, then starts fresh. Weights are kept.

## Layout
```
market-scanner/   this repo: start.ps1, stop.ps1, reset.ps1, docker-compose.yml
  infra/          clone of shared-market-research-Infra (git-ignored; compose project market-infra)
  app/            clone of ATH-Scanner (git-ignored)
```
The infra stays a separate compose project on the `market-infra` network, so other projects can join it.
