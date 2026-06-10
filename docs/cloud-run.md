# Cloud Run deployment

This service runs the Telegram bot with long polling and starts a tiny HTTP
health server when Cloud Run provides the `PORT` environment variable.

Cloud Run requires the ingress container to listen on `0.0.0.0:$PORT`. The bot
does that through `app.health` and exposes:

- `/`
- `/healthz`

Both endpoints return `200 OK` with `ok`.

## Required runtime variables

Set these in Cloud Run:

```text
BOT_TOKEN=<telegram bot token>
APP_ENV=production
RISKUA_DEBTORS_BROWSER_HEADLESS=true
```

Cloud Run sets `PORT` automatically. Do not set
`RISKUA_DEBTORS_BROWSER_CHANNEL=msedge` in Cloud Run, because the Linux image
uses Playwright Chromium.

For a local Docker run, the image defaults to `PORT=8080`.

## Build and deploy example

Replace `PROJECT_ID`, `REGION`, and `REPOSITORY` with your Google Cloud values.

```bash
gcloud builds submit \
  --tag REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY/riskua-kontragent-bot:latest

gcloud run deploy riskua-kontragent-bot \
  --image REGION-docker.pkg.dev/PROJECT_ID/REPOSITORY/riskua-kontragent-bot:latest \
  --region REGION \
  --set-env-vars APP_ENV=production,RISKUA_DEBTORS_BROWSER_HEADLESS=true \
  --set-secrets BOT_TOKEN=BOT_TOKEN:latest \
  --min-instances 1 \
  --no-cpu-throttling
```

For Telegram long polling, `--min-instances 1` keeps one bot instance warm and
`--no-cpu-throttling` lets background polling keep running while no HTTP
request is active.
