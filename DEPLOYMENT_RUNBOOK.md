# ANJASI — Deployment Runbook

**Target:** DigitalOcean Droplet + Managed PostgreSQL, Bangalore (BLR1)
**Stack:** Ubuntu 24.04 · Python 3.12 · gunicorn · nginx · certbot
**First tenant:** Setu Yoga Studio

Companion document: `ANJASI_INFRA_STATUS.md` (what is built, what is pending,
and why each design decision was made). Read §0 of this file before starting —
the ordering in §6 is not optional.

---

## 0. Before you touch a server

These have lead times. Start them first or you will sit idle later.

| # | Item | Owner | Lead time | Blocks |
|---|---|---|---|---|
| 1 | **AWS SES production access** (sandbox exit) | ANJASI | 24–48h | Invite onboarding |
| 2 | DNS for `app.anjasi.com` (A record, ready to point) | ANJASI | minutes | TLS |
| 3 | SPF + DKIM records for the sending domain | ANJASI | hours | Email deliverability |
| 4 | Razorpay KYC + live keys | Setu Yoga | days | Member payments |
| 5 | MSG91 account + DLT registration | Setu Yoga | days–weeks | SMS |
| 6 | Meta Business verification → WABA → template approval | Setu Yoga | days–weeks, sequential | WhatsApp |

**Only 1–3 block go-live.** Items 4–6 block individual channels; the studio can
operate on email alone while they clear.

> **SES sandbox:** in sandbox, SES delivers only to *verified* addresses. Invite
> links go to brand-new studio owners, so invite onboarding does not work until
> the sandbox exit lands. Everything else is unaffected.

---

## 1. Provision DigitalOcean resources

| Resource | Spec | Notes |
|---|---|---|
| Droplet | Ubuntu 24.04, 2 vCPU / 4 GB, BLR1 | Add your SSH key at creation |
| Managed PostgreSQL | 1 vCPU / 2 GB, PG 16, BLR1 | Same region as the droplet |
| Spaces bucket | BLR1, e.g. `anjasi-media` | For tenant logos/favicons |
| Droplet backups | Enable (+20%) | Weekly snapshots |

After creating the database:

1. **Databases → Settings → Trusted Sources → add the droplet.** Without this
   the droplet cannot connect, and the error is a bare timeout.
2. Note the connection details. DO managed Postgres **requires TLS**, so
   `DB_SSLMODE=require` is mandatory (§5).
3. Create a database named `anjasi` and a non-superuser role for the app.

---

## 2. Server bootstrap

```bash
ssh root@<droplet-ip>

adduser --disabled-password --gecos "" anjasi
usermod -aG sudo anjasi
rsync --archive --chown=anjasi:anjasi ~/.ssh /home/anjasi/

apt update && apt upgrade -y
apt install -y python3.12 python3.12-venv python3-pip \
               nginx git ufw postgresql-client libpq-dev build-essential

ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

# Harden SSH: set PermitRootLogin no and PasswordAuthentication no
nano /etc/ssh/sshd_config && systemctl restart ssh
```

Confirm you can log in as `anjasi` **in a second terminal** before closing the
root session.

---

## 3. Get the code

```bash
su - anjasi
mkdir -p /home/anjasi/app && cd /home/anjasi/app
git clone https://github.com/sureshbantupalli/saas-platform-clean.git .
git checkout fix/mvp-bugs      # or main, once the PR is merged
```

---

## 4. Python environment

```bash
cd /home/anjasi/app
python3.12 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
```

> `psycopg2-binary` needs `libpq-dev` and `build-essential`, installed in §2.

---

## 5. Environment file

```bash
cp .env.example .env
chmod 600 .env          # contains the DB password and SES credentials
nano .env
```

Minimum for production — `.env.example` documents every variable:

```ini
DJANGO_ENV=production
SECRET_KEY=<paste from the command below>

ALLOWED_HOSTS=app.anjasi.com
CSRF_TRUSTED_ORIGINS=https://app.anjasi.com
SITE_URL=https://app.anjasi.com

DB_NAME=anjasi
DB_USER=<db user>
DB_PASSWORD=<db password>
DB_HOST=<private-host>.db.ondigitalocean.com
DB_PORT=25060
DB_SSLMODE=require

EMAIL_HOST=email-smtp.ap-south-1.amazonaws.com
EMAIL_HOST_USER=<SES SMTP username>
EMAIL_HOST_PASSWORD=<SES SMTP password>
DEFAULT_FROM_EMAIL=ANJASI <no-reply@anjasi.com>

MEDIA_STORAGE_BACKEND=spaces
AWS_STORAGE_BUCKET_NAME=anjasi-media
AWS_S3_ENDPOINT_URL=https://blr1.digitaloceanspaces.com
AWS_S3_REGION_NAME=blr1
AWS_ACCESS_KEY_ID=<Spaces key>
AWS_SECRET_ACCESS_KEY=<Spaces secret>

PAYMENTS_ENCRYPTION_KEY=<paste from the command below>
```

Generate the two secrets:

```bash
./venv/bin/python -c "import secrets; print(secrets.token_urlsafe(64))"
./venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> ⚠️ **`PAYMENTS_ENCRYPTION_KEY` cannot be rotated casually.** It encrypts both
> `TenantPaymentConfig` and `TenantMessagingConfig` secrets. Change it and every
> stored credential becomes unreadable. Back it up somewhere other than the
> droplet, and use the *same* key in staging only if you also copy the data.

> SES SMTP credentials are **not** your AWS access keys — generate them in the
> SES console.

---

## 6. Initialise the database — order matters

```bash
cd /home/anjasi/app
export $(grep -v '^#' .env | xargs)     # or rely on the systemd unit later

./venv/bin/python manage.py migrate
./venv/bin/python manage.py createcachetable
./venv/bin/python manage.py collectstatic --noinput

# 1. Permissions MUST exist before any tenant is created.
./venv/bin/python manage.py seed_permissions
./venv/bin/python manage.py seed_role_permissions

# 2. ANJASI's own tenant, then its message templates.
./venv/bin/python manage.py ensure_platform_tenant
./venv/bin/python manage.py seed_platform_comms

./venv/bin/python manage.py createsuperuser
```

> **Why the order is not arbitrary:** `TenantService.create_tenant()` grants role
> permissions by iterating `PermissionAction.objects.all()`. If that table is
> empty, tenants are created with **no permissions at all** and the failure is
> silent — everyone can log in and see nothing. Seed permissions before
> provisioning any studio.
>
> `seed_platform_comms` likewise requires the platform tenant to exist, and will
> refuse with a clear error if it does not.

Verify before moving on:

```bash
./venv/bin/python manage.py check --deploy      # expect no issues
```

---

## 7. Gunicorn service

`/etc/systemd/system/anjasi.service`:

```ini
[Unit]
Description=ANJASI Django application
After=network.target

[Service]
Type=notify
User=anjasi
Group=www-data
WorkingDirectory=/home/anjasi/app
EnvironmentFile=/home/anjasi/app/.env
ExecStart=/home/anjasi/app/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/run/anjasi/gunicorn.sock \
    --timeout 60 \
    --access-logfile - \
    --error-logfile - \
    config.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
RuntimeDirectory=anjasi
Restart=on-failure
RestartSec=5s

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now anjasi
sudo systemctl status anjasi
```

> **Worker count:** `(2 × cores) + 1` is the usual rule — 5 on 2 vCPU. Start at
> **3**: each worker holds its own DB connections, and the managed database has
> a connection cap. Raise it only if you see requests queueing.
>
> `--timeout 60` is deliberate. The SES, MSG91 and Meta adapters each cap their
> own HTTP calls at 10s, so a 60s worker timeout leaves room without letting a
> hung request pin a worker indefinitely.

---

## 8. nginx

`/etc/nginx/sites-available/anjasi`:

```nginx
upstream anjasi_app {
    server unix:/run/anjasi/gunicorn.sock fail_timeout=0;
}

server {
    listen 80;
    server_name app.anjasi.com;

    client_max_body_size 10M;      # tenant logo uploads

    location /static/ {
        alias /home/anjasi/app/staticfiles/;
        # Files are content-hashed by WhiteNoise's manifest storage,
        # so a long cache is safe.
        expires 1y;
        add_header Cache-Control "public, immutable";
        access_log off;
    }

    location / {
        proxy_pass http://anjasi_app;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        # REQUIRED: production.py sets SECURE_PROXY_SSL_HEADER and
        # SECURE_SSL_REDIRECT. Without this header Django cannot tell the
        # request arrived over HTTPS and redirects forever.
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/anjasi /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

> `/media/` is intentionally **not** served by nginx: media lives in Spaces
> (§5). If you ever set `MEDIA_STORAGE_BACKEND` back to local disk, add a
> `location /media/` block or uploads will 404.

---

## 9. TLS

Point the DNS A record at the droplet, wait for it to resolve, then:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d app.anjasi.com
sudo systemctl status certbot.timer     # auto-renewal
```

`production.py` already sets HSTS for one year with `preload`. Only submit to
the HSTS preload list once you are certain every subdomain will be HTTPS
forever — it is difficult to undo.

---

## 10. Cron

```bash
crontab -e -u anjasi
```

```cron
APP=/home/anjasi/app
PY=$APP/venv/bin/python
# Times are IST — TIME_ZONE is Asia/Kolkata.

# Renewals: detect due memberships and fire reminders.
0 9 * * *    cd $APP && $PY manage.py run_renewals            >> /var/log/anjasi/cron.log 2>&1

# Membership state transitions (active → expiring → expired).
30 0 * * *   cd $APP && $PY manage.py run_lifecycle_updates   >> /var/log/anjasi/cron.log 2>&1

# Revenue nudges for at-risk members.
0 10 * * *   cd $APP && $PY manage.py run_nudges              >> /var/log/anjasi/cron.log 2>&1

# Follow-ups that have come due.
15 9 * * *   cd $APP && $PY manage.py emit_followup_due       >> /var/log/anjasi/cron.log 2>&1

# Retry FAILED communications. Frequent, because a transient SMS/SMTP
# failure should not wait a day.
*/30 * * * * cd $APP && $PY manage.py retry_failed_messages   >> /var/log/anjasi/cron.log 2>&1
```

```bash
sudo mkdir -p /var/log/anjasi && sudo chown anjasi:anjasi /var/log/anjasi
```

Add to `/etc/logrotate.d/anjasi`:

```
/var/log/anjasi/*.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

> `run_retries` and `trigger_renewals` also exist but overlap with the above —
> do not schedule all of them, or renewal messages go out twice. The five
> entries here are the full recurring set.

---

## 11. Smoke test — do not skip

```bash
# 1. Service is up and serving
curl -I https://app.anjasi.com/               # expect 200 or 302, not 502

# 2. Static files are served and hashed
curl -I https://app.anjasi.com/static/css/design-system.css   # expect 200

# 3. Deployment checks pass
./venv/bin/python manage.py check --deploy

# 4. The cache is shared across processes, not per-worker
./venv/bin/python -c "
import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from django.core.cache import cache; cache.set('smoke','ok',60); print('cache:', cache.get('smoke'))"

# 5. Email actually leaves the box (to a VERIFIED address while in sandbox)
./venv/bin/python -c "
import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from django.core.mail import send_mail
send_mail('ANJASI smoke test','It works.',None,['you@yourdomain.com'])
print('sent')"

# 6. Invite flow end to end
./venv/bin/python manage.py create_tenant_invite \
    --studio "Setu Yoga" --email owner@setuyoga.com --owner-name "Suresh"
```

Then open the emailed link, set a password, and confirm the workspace is
created and you can sign in.

---

## 12. Deploying an update

```bash
cd /home/anjasi/app
git pull
./venv/bin/pip install -r requirements.txt
./venv/bin/python manage.py migrate
./venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart anjasi
```

Run `createcachetable`, `seed_permissions` and `seed_platform_comms` again only
if the release adds new permissions or platform templates. All are idempotent,
so running them is harmless.

---

## 13. Rollback

```bash
# Application code
cd /home/anjasi/app
git log --oneline -5
git checkout <previous-sha>
./venv/bin/pip install -r requirements.txt
./venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart anjasi
```

> **Migrations do not roll back automatically.** If the bad release migrated the
> database, reverse it explicitly *before* checking out the old code:
>
> ```bash
> ./venv/bin/python manage.py migrate <app> <previous_migration_number>
> ```
>
> Some migrations are not reversible. Check `manage.py showmigrations` and the
> migration file first. If it cannot be reversed, restore the database from a
> backup (§14) instead of guessing.

---

## 14. Backups and the restore drill

DigitalOcean Managed PostgreSQL takes daily backups with 7-day point-in-time
recovery. That is adequate — but **an untested backup is not a backup.**

Once, before go-live, and then quarterly:

1. Fork the production database from a backup (DO console → Databases → Fork).
2. Point a staging `.env` at the fork.
3. Run `manage.py check` and load the dashboard.
4. Confirm the row counts match roughly.
5. Destroy the fork.

Also back up, outside the droplet:

- `.env` — in particular `SECRET_KEY` and `PAYMENTS_ENCRYPTION_KEY`
- The Spaces bucket, if tenant media matters

> Losing `PAYMENTS_ENCRYPTION_KEY` means every stored Razorpay, MSG91 and
> WhatsApp credential is permanently unreadable, even with a database backup.

---

## 15. Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| **502 Bad Gateway** | gunicorn not running, or socket permissions | `systemctl status anjasi`, `journalctl -u anjasi -n 50` |
| **Infinite HTTPS redirect** | nginx not sending `X-Forwarded-Proto` | §8 — `production.py` sets `SECURE_SSL_REDIRECT` and relies on that header |
| **CSS/JS 404, site unstyled** | `collectstatic` not run, or nginx `alias` path wrong | `ls staticfiles/ \| head`, re-run collectstatic |
| **DB connection timeout** | Droplet not in the DB's Trusted Sources | DO console → Databases → Settings |
| **`no password supplied`** | `.env` not loaded by systemd | `EnvironmentFile=` present in the unit? |
| **New tenant sees nothing** | `seed_permissions` never ran | `manage.py shell` → `PermissionAction.objects.count()` |
| **Invite email not sent** | SES in sandbox, or platform templates missing | Invite row's `email_error`; run `seed_platform_comms` |
| **`notify_platform` returns False** | No TriggerRule for that event | `manage.py seed_platform_comms` |
| **Rate limit weaker than expected** | Cache table missing → per-process fallback | `manage.py createcachetable` |
| **Tenant logo vanishes after deploy** | `MEDIA_STORAGE_BACKEND` unset | §5 |
| **SMS under the wrong sender name** | Tenant has no `TenantMessagingConfig`, using global env | Search logs for `GLOBAL env credentials` |

**Logs:**

```bash
journalctl -u anjasi -f          # application
tail -f /var/log/nginx/error.log # nginx
tail -f /var/log/anjasi/cron.log # scheduled commands
```

---

## 16. Known gaps at go-live

Carried from `ANJASI_INFRA_STATUS.md`, so nobody rediscovers them at 2am:

- **No Sentry yet.** Errors go to `journalctl` only; nothing alerts you. Add
  `SENTRY_DSN` — free tier is sufficient.
- **`pytest.ini` `testpaths` is still `apps/assessments/tests`,** so a bare
  `pytest` runs 87 of 1,181 tests. Run `pytest apps` in CI.
- **Seven apps have no test module at all:** `activity`, `catalog`, `documents`,
  `expenses`, `payouts`, `platform_sessions`, `verticals`.
- **No automated deployment.** §12 is manual. Fine for one server; revisit if a
  second appears.
- **No staging environment.** Migrations reach production untested against real
  data. The backup fork in §14 is the cheapest way to close this.
