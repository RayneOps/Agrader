# AGRADER

Decision-support web app for our field team. Operators record a smallholder farm's history,
the crops the farmer wants to grow this season and a soil reading. The app then ranks the
farmer's own shortlist and explains why. Farmers never sign in; only the team uses the app.

The product name comes from the `PRODUCT_NAME` setting (default `AGRADER`).

## Stack

Python 3.14 (pinned in `.python-version`), Django 5.2, server-rendered templates, plain CSS and
a little vanilla JS. SQLite for local development and PostgreSQL in production. Production
runs on Vercel.

## Local setup

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate      macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # then edit .env (see below)
python manage.py migrate
python manage.py seed_admins     # needs the four ADMIN_PW_* variables
python manage.py seed_crops      # draft crop knowledge, safe to re-run
python manage.py runserver
```

Open http://127.0.0.1:8000/login and sign in with one of the admin emails.

## Environment variables

### Needed in production

Set these in Vercel → Project → Settings → Environment Variables.

| Variable | Purpose |
| --- | --- |
| `DJANGO_SECRET_KEY` | A long random string. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(50))"`. The build needs it too, because Vercel imports the settings to run `collectstatic`. |
| `DATABASE_URL` | The hosted PostgreSQL URL. Include `?sslmode=require` if your provider needs it. Without this variable, production refuses to start rather than fall back to SQLite. |
| `DJANGO_ALLOWED_HOSTS` | Your custom domain or domains, comma-separated, e.g. `agrader.example.org`. Vercel's own `*.vercel.app` hosts are added automatically. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | The same domains with `https://`, e.g. `https://agrader.example.org`. Without it, sign-in fails with a CSRF error on a custom domain. |
| `LLM_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL` | Needed from phase 6. Alternatively, set `LLM_PROVIDER=claude` with `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL`. |

Leave `DJANGO_DEBUG` unset; it defaults to `false`. Never set it to `true` in production.

### Optional

| Variable | Default | Purpose |
| --- | --- | --- |
| `PRODUCT_NAME` | `AGRADER` | The name shown in the UI. |
| `PUBLIC_CONTACT` | empty | The email or phone shown on the public landing page. The Contact section is hidden while this is empty. |
| `ALLOW_UNAPPROVED_RULES` | `false` | Use crop rules the Crop Scientist has not approved yet. Recommendations then show a draft banner. |
| `DB_POOLED` | `false` | Set to `true` if `DATABASE_URL` goes through a transaction-mode pooler, such as PgBouncer, a Neon `-pooler` host, or Supabase on port 6543. |
| `DB_CONN_MAX_AGE` | `0` | Seconds to keep a database connection open. Keep it at `0` on serverless. |
| `LOG_LEVEL` | `INFO` | Logs go to stdout, which Vercel's log viewer shows. |
| `DJANGO_HSTS_SECONDS` | `3600` | The HSTS max-age. Raise it once the domain is settled. |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` | Redirect HTTP to HTTPS. |

### Only on your machine, never in Vercel

These are used by `seed_admins` and `prod_setup`.

| Variable | Purpose |
| --- | --- |
| `ADMIN_PW_USMAN`, `ADMIN_PW_ISHAQ`, `ADMIN_PW_SAMANTHA`, `ADMIN_PW_APEH` | Initial passwords for the four super admins, at least 10 characters each. |
| `RULE_APPROVER_EMAIL` | The admin allowed to approve crop rules. Empty means nobody can. Re-run `seed_admins` after changing it. |
| `AGRADER_ENV_FILE` | Load settings from this file instead of `.env`. See the deployment section. |
| `AGRADER_DIRECT_DB` | Set to `true` to use `DATABASE_URL_UNPOOLED` instead of `DATABASE_URL`, for migrations. |
| `DJANGO_DEBUG` | Set to `true` for local development. |

## Deploying to Vercel

Vercel does the following on each deploy:

1. It finds `manage.py` and reads `WSGI_APPLICATION`.
2. It installs `requirements.txt` using the Python version in `.python-version`.
3. It runs `collectstatic` and serves `/static/` from its CDN.

`vercel.json` gives each request up to 60 seconds and keeps the tests and docs out of the
bundle.

To deploy:

1. Set the production variables above for the **Production** environment. If you use Preview
   deployments, give Preview its own `DJANGO_SECRET_KEY` and its own database. A Preview
   deployment that shares the production `DATABASE_URL` writes to production data.
2. Prepare the production database from your machine, as described in the next section.
3. Deploy. On every later deploy that adds migrations, repeat step 2 **before** promoting the
   deployment, so the new code never meets an old schema.

### Running migrate, seed_crops and seed_admins against production

Serverless functions can't run management commands. The build must not run migrations either,
because Preview builds would run them too. Run them from your machine instead:

```bash
# 1. Pull the production variables into a git-ignored file.
#    This needs the Vercel CLI, logged in and linked to the project.
vercel env pull .env.production --environment=production

# 2. First run only: add the admin passwords and the approver, to that file or to your shell.
#    ADMIN_PW_USMAN=...  ADMIN_PW_ISHAQ=...  ADMIN_PW_SAMANTHA=...  ADMIN_PW_APEH=...
#    RULE_APPROVER_EMAIL=samantha@agrader.hq

# 3. Run the setup. It prints the database it will change and asks you to type its host.
AGRADER_ENV_FILE=.env.production python manage.py prod_setup
#    PowerShell:  $env:AGRADER_ENV_FILE=".env.production"; python manage.py prod_setup

#    On later deploys with new migrations, once the admins exist:
AGRADER_ENV_FILE=.env.production python manage.py prod_setup --skip-admins

# 4. Delete the file when you are done. It holds production secrets.
rm .env.production
```

`prod_setup` runs `migrate`, then `seed_crops`, then `seed_admins`. All three are safe to
repeat. It has two safeguards:
- It refuses to run against the local SQLite file.
- If `AGRADER_ENV_FILE` names a file that doesn't exist, it stops instead of falling back to
  `.env`.

If your provider gives a direct (unpooled) URL as `DATABASE_URL_UNPOOLED`, add
`AGRADER_DIRECT_DB=true` so that migrations skip the pooler.

### What behaves differently on a serverless host

- **No lasting disk.** Anything written to the filesystem disappears. The app stores
  everything in PostgreSQL and refuses to start without `DATABASE_URL`. Don't add file uploads
  without object storage.
- **No management commands on the host.** Use `prod_setup` from your machine instead.
- **Database connections.** Each function instance opens its own connection. Use your
  provider's pooled URL with `DB_POOLED=true`, and keep `DB_CONN_MAX_AGE=0`.
- **60-second request limit,** set in `vercel.json`. The LLM call in phase 6 will have its own
  shorter timeout, with the retry and fallback inside that limit. Don't raise the limit to
  hide a slow call.
- **No shared memory between requests.** Function instances come and go, so anything held in
  memory is lost. For that reason, the device rate limit in phase 7 will be stored in the
  database.
- **No background jobs or schedules.** Nothing in the app needs them today. Anything that runs
  outside a request, such as retrying pending recommendations, would need Vercel Cron or
  Queues.
- **Cold starts.** The first request after a quiet spell is slower while Django loads.
- **The build imports the settings.** `DJANGO_SECRET_KEY` and `DATABASE_URL` must be set for
  every environment that builds. A missing variable fails the build with a message that names
  it. That is what happened on the first deploy.
- **Local `.env` files are never read on Vercel** (when `VERCEL_ENV` is `production` or
  `preview`), and `.vercelignore` keeps them out of uploads. A stray `DJANGO_DEBUG=true`
  therefore can't reach production.

## Admin accounts

`python manage.py seed_admins` creates `usman@`, `ishaq@`, `samantha@` and `apeh@agrader.hq`
as super admins. It checks every password before it creates anyone. If any password is
missing or weak, it stops without changing anything. Running it again leaves existing admins
alone. Add `--reset-passwords` to set their passwords from the environment again.

These addresses cannot receive mail, so there is no email password reset. Another admin sets
a new password from the Admins screen (phase 8).

## Crop knowledge

`python manage.py seed_crops` loads 12 crops, their requirements, pair rules, rotation rules and
score settings, all as unapproved drafts. Running it again only adds what is missing and never
changes existing records.

Only the admin named by `RULE_APPROVER_EMAIL` can approve rules. They may approve their own
edits, but always as a separate click. Editing a requirement creates a new version. Editing any
other rule or setting clears its approval.

## Audit log

Every model inherits `core.models.BaseModel`, which gives it a UUID primary key, `created_at`
and `updated_at`. Every create, update and delete on these models writes an `AuditLog` row
automatically. The row records the admin who made the change and the before and after values
as JSON. Changes made from management commands or the device API have no admin attached and
show as "System".

Two limits apply. `QuerySet.update()` and `bulk_create()` skip Django signals, so code that
needs auditing must save records one at a time. Password hashes and `last_login` are never
logged.

## Tests

```bash
python manage.py test
```

## Decisions

Product decisions made after the original brief are recorded in [docs/DECISIONS.md](docs/DECISIONS.md).

## Build status

- [x] Phase 1: settings, custom user, login, `seed_admins`, audit log, base template and styles
- [x] Phase 2: farmers, farms, seasons
- [x] Phase 3: crop knowledge and `seed_crops`
- [x] Phase 4: manual soil readings and the new season wizard
- [x] Phase 5: hard rules, fit score, mixed cropping
- [ ] Phase 6: LLM adapter, validator, Recommendation screen
- [ ] Phase 7: device API and Devices screen
- [ ] Phase 8: trend charts, Overview, Activity, Admins
