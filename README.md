# AGRADER

Decision-support web app for our field team. Operators record a smallholder farm's history,
the crops the farmer wants to grow this season and a soil reading. The app then ranks the
farmer's own shortlist and explains why. Farmers never sign in; only the team uses the app.

The product name comes from the `PRODUCT_NAME` setting (default `AGRADER`).

## Stack

Python 3.12+, Django 5.2, server-rendered templates, plain CSS and a little vanilla JS.
SQLite for local development and PostgreSQL in production.

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

`psycopg` is only needed for PostgreSQL. If it fails to install locally, you can skip it
while using SQLite.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `DJANGO_DEBUG` | no (default `false`) | `true` for local development only. |
| `DJANGO_SECRET_KEY` | when debug is off | Django secret key. |
| `DJANGO_ALLOWED_HOSTS` | no | Comma-separated host names. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | production | Comma-separated origins, e.g. `https://app.example.org`. |
| `DATABASE_URL` | production | e.g. `postgres://user:pass@host:5432/agrader`. Empty means local SQLite. |
| `PRODUCT_NAME` | no (default `AGRADER`) | Name shown in the UI. |
| `ADMIN_PW_USMAN`, `ADMIN_PW_ISHAQ`, `ADMIN_PW_SAMANTHA`, `ADMIN_PW_APEH` | for `seed_admins` | Initial passwords for the four super admins. At least 10 characters. |
| `RULE_APPROVER_EMAIL` | no | The admin allowed to approve crop rules. Empty means nobody can. Re-run `seed_admins` after changing it. |
| `LLM_PROVIDER` | no (default `gemini`) | `gemini` or `claude`. Used from phase 6. |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | when provider is gemini | |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | when provider is claude | |
| `ALLOW_UNAPPROVED_RULES` | no (default `false`) | Allow crop rules not yet approved by the Crop Scientist. |

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

Only the admin named by `RULE_APPROVER_EMAIL` can approve rules, and never a version they
edited themselves. Editing a requirement creates a new version. Editing any other rule or
setting clears its approval.

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
- [ ] Phase 4: manual soil readings and the new season wizard
- [ ] Phase 5: hard rules, fit score, mixed cropping
- [ ] Phase 6: LLM adapter, validator, Recommendation screen
- [ ] Phase 7: device API and Devices screen
- [ ] Phase 8: trend charts, Overview, Activity, Admins
