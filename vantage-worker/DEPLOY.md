# Deploy VantageAI Worker to Cloudflare

Run these commands in order — takes about 5 minutes total.

## 1. Install dependencies
```bash
cd vantage-worker
npm install
```

## 2. Create D1 database
```bash
npm run db:create
```
Copy the `database_id` from the output and paste it into `wrangler.toml`:
```toml
[[d1_databases]]
database_id = "PASTE_ID_HERE"
```

## 3. Create KV namespace
```bash
npm run kv:create
```
Copy the `id` from the output and paste it into `wrangler.toml`:
```toml
[[kv_namespaces]]
id = "PASTE_ID_HERE"
```

## 4. Run database migrations
```bash
# Local (for dev):
npm run db:migrate

# Remote (production):
npm run db:migrate:remote
```

## 5. Set secrets
```bash
wrangler secret put SUPABASE_SERVICE_KEY
# paste your Supabase service_role key when prompted
```

## 6. Deploy
```bash
npm run deploy
```

Your Worker will be live at:
`https://vantage-api.<your-account>.workers.dev`

## 7. Update frontend API base
After deploying, paste your Worker URL into the dashboard Settings:
- Open `https://vantageai.pages.dev/app.html`
- Click ⚙ Settings
- Set API Base to your Worker URL

Or set it via URL param:
`https://vantageai.pages.dev/app.html?api_base=https://vantage-api.YOUR-ACCOUNT.workers.dev`
