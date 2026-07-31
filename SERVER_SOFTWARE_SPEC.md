# ANJASI — Server Software Specification

**For:** the consultant handling deployment
**Application:** ANJASI, a multi-tenant Django SaaS for yoga/fitness studios
**First tenant:** Setu Yoga Studio, Hyderabad
**Target:** DigitalOcean Droplet + Managed PostgreSQL, Bangalore (BLR1)

Step-by-step build instructions are in **`DEPLOYMENT_RUNBOOK.md`**. This file
is the inventory: what must exist on the server, and what deliberately must
not.

---

## Summary

| | |
|---|---|
| Application runtime | **Python 3.12** |
| Web server | **nginx** → gunicorn over a UNIX socket |
| Application server | **gunicorn**, 3 workers, systemd-managed |
| Database | **PostgreSQL 16**, managed, TLS required |
| Object storage | **S3-compatible** (DO Spaces or AWS S3) |
| Outbound email | **AWS SES** over SMTP |
| Scheduler | **cron** — 5 recurring jobs |
| Long-running processes | **3** — gunicorn, nginx, cron |
| Containers / orchestration | **none** |

This is a small, conventional deployment. There is no queue worker, no
in-memory cache daemon, no build toolchain and no container runtime.

---

## 1. Operating system

**Ubuntu 24.04 LTS**, x86_64. Ships Python 3.12, which is the minimum Django
6.0 supports.

Any distribution providing Python ≥ 3.12 works; 24.04 is what the runbook is
written against.

---

## 2. OS packages (`apt`)

| Package | Purpose | Required |
|---|---|---|
| `python3.12` | Application runtime | **Yes** |
| `python3.12-venv` | Virtual environment | **Yes** |
| `python3-pip` | Installing dependencies | **Yes** |
| `nginx` | Reverse proxy, TLS termination, serves `/static/` | **Yes** |
| `certbot`, `python3-certbot-nginx` | Let's Encrypt certificates + renewal | **Yes** |
| `git` | Deployment is `git pull` | **Yes** |
| `ufw` | Firewall — allow only 22, 80, 443 | **Yes** |
| `cron` | Scheduled jobs (preinstalled on Ubuntu) | **Yes** |
| `postgresql-client` | `psql` / `pg_dump` for backups and debugging | Recommended |
| `build-essential`, `libpq-dev` | Compiling Python C extensions | **Insurance only** — see note |

> **On `build-essential` / `libpq-dev`:** every dependency below ships a
> prebuilt manylinux wheel, so nothing compiles during a normal install. These
> are worth installing anyway: if a wheel is ever unavailable for the Python
> version in use, pip falls back to building from source and fails without
> them. Roughly 200 MB, no runtime cost.

---

## 3. Python packages

Installed into a virtualenv via `pip install -r requirements.txt`.
**All 17 are version-pinned**, and the pins match exactly what the 1,181-test
suite runs against.

| Package | Version | Purpose |
|---|---|---|
| Django | 6.0.4 | Web framework |
| djangorestframework | 3.17.1 | REST API |
| asgiref | 3.11.1 | Django dependency |
| sqlparse | 0.5.5 | Django dependency |
| psycopg2-binary | 2.9.11 | PostgreSQL driver |
| gunicorn | 23.0.0 | WSGI application server |
| whitenoise | 6.8.2 | Serves hashed static files |
| django-storages | 1.14.4 | S3/Spaces media backend |
| boto3 | 1.35.36 | AWS SDK, used by django-storages |
| requests | 2.33.1 | MSG91 and Meta WhatsApp HTTP calls |
| razorpay | 2.0.1 | Payment gateway SDK |
| cryptography | 46.0.7 | Fernet encryption of stored tenant credentials |
| Pillow | 12.2.0 | Required by Django `ImageField`; migrations fail without it |
| python-dotenv | 1.2.2 | Loads `.env` |
| python-dateutil | 2.9.0.post0 | Date handling |
| six | 1.17.0 | Transitive dependency |
| tzdata | 2026.1 | Timezone data (`TIME_ZONE = Asia/Kolkata`) |

> **Do not float these versions.** `cryptography` in particular encrypts every
> stored Razorpay, MSG91 and WhatsApp credential; the pin is what makes a
> rebuild reproducible.

---

## 4. Managed services (not installed on the droplet)

| Service | Spec | Notes |
|---|---|---|
| **PostgreSQL** | v16, 1 vCPU / 2 GB, BLR1 | **TLS mandatory** → `DB_SSLMODE=require`. Add the droplet to Trusted Sources or connections silently time out |
| **Object storage** | DO Spaces (or AWS S3), BLR1 | Tenant logos and favicons. Without it they are lost on every rebuild |
| **AWS SES** | `ap-south-1`, SMTP interface | Uses **SMTP credentials generated in the SES console** — these are *not* AWS access keys. Must be out of the SES sandbox before real onboarding works |

---

## 5. Processes on the server

| Process | Supervisor | Notes |
|---|---|---|
| `gunicorn` (3 workers) | systemd — `anjasi.service` | Binds a UNIX socket, not a TCP port |
| `nginx` | systemd | Terminates TLS; must forward `X-Forwarded-Proto` |
| `cron` | systemd | 5 jobs, listed below |

**Worker count:** start at **3**, not the textbook `(2 × cores) + 1`. Each
worker holds its own database connections and the managed instance has a
connection cap. Raise only if requests are seen queueing.

### Scheduled jobs

| Schedule (IST) | Command | Purpose |
|---|---|---|
| `0 9 * * *` | `run_renewals` | Detect due memberships, fire reminders |
| `30 0 * * *` | `run_lifecycle_updates` | Membership state transitions |
| `0 10 * * *` | `run_nudges` | Revenue nudges for at-risk members |
| `15 9 * * *` | `emit_followup_due` | Follow-ups that have come due |
| `*/30 * * * *` | `retry_failed_messages` | Retry FAILED communications |

> `run_retries` and `trigger_renewals` also exist in the codebase but **overlap
> with the above**. Scheduling all seven sends renewal messages twice. The five
> here are the complete recurring set.

---

## 6. Deliberately NOT required

Listed explicitly so nobody adds them out of habit.

| Not needed | Why |
|---|---|
| **Redis / Memcached** | The Django cache is database-backed (`createcachetable`). Redis is supported via `REDIS_URL` but is not required and should only be added if profiling justifies it |
| **Celery / RabbitMQ** | No async task queue. Background work is plain cron. One commented Celery example exists in the codebase and is unused |
| **Docker / Kubernetes** | Single server, single application |
| **Node.js / npm** | No frontend build step. Django templates plus Bootstrap from CDN |
| **supervisor** | systemd handles process supervision |
| **Apache** | nginx only |
| **Elasticsearch, RabbitMQ, Nginx Unit** | Not used anywhere |
| **wkhtmltopdf, WeasyPrint, ffmpeg, ImageMagick** | Verified: no code invokes any external binary. Image handling is Pillow, in-process |

---

## 7. Network and firewall

| Port | Direction | Purpose |
|---|---|---|
| 22 | inbound | SSH — key auth only, root login disabled |
| 80 | inbound | HTTP → redirected to HTTPS by nginx |
| 443 | inbound | HTTPS |
| 25060 | outbound | Managed PostgreSQL (TLS) |
| 587 | outbound | AWS SES SMTP |
| 443 | outbound | Spaces/S3, Razorpay, MSG91, Meta Graph API |

gunicorn binds a UNIX socket and is **not** exposed on any port.

---

## 8. Required environment variables

Full documentation with per-variable notes is in **`.env.example`**. The file
must be `chmod 600` — it contains database, SES and encryption secrets.

**Mandatory:** `DJANGO_ENV=production`, `SECRET_KEY`, `ALLOWED_HOSTS`,
`CSRF_TRUSTED_ORIGINS`, `SITE_URL`, `DB_*` (including `DB_SSLMODE=require`),
`PAYMENTS_ENCRYPTION_KEY`.

**For email:** `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`,
`DEFAULT_FROM_EMAIL`.

**For media:** `MEDIA_STORAGE_BACKEND=spaces`, `AWS_STORAGE_BUCKET_NAME`,
`AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`.

> ⚠️ **`PAYMENTS_ENCRYPTION_KEY` must be backed up off the server.** It
> encrypts every stored Razorpay, MSG91 and WhatsApp credential. Lose it and
> those become permanently unreadable — **a database backup does not help.**

---

## 9. Things the consultant should be told up front

Not defects, but they will otherwise be discovered the hard way.

1. **`seed_permissions` must run before any tenant is created.** Tenant
   creation grants role permissions by iterating the `PermissionAction` table.
   If it is empty, tenants are created with **no permissions and no error** —
   users log in successfully to an empty application. The initialisation order
   in the runbook is not arbitrary.

2. **nginx must forward `X-Forwarded-Proto`.** Production settings enable
   `SECURE_SSL_REDIRECT` together with `SECURE_PROXY_SSL_HEADER`. Omit that
   header and Django cannot tell the request arrived over TLS — infinite
   redirect loop, on a configuration that looks correct.

3. **Media must not stay on local disk.** `MEDIA_STORAGE_BACKEND` unset means
   uploads go to the droplet filesystem and vanish on the next rebuild.

4. **gunicorn has never been executed.** Development is on Windows, where
   gunicorn cannot run (it requires `fcntl`). Its first ever run will be on
   this server. The WSGI entry point is `config.wsgi:application` and
   `manage.py check --deploy` passes under production settings, but the
   process itself is unproven.

5. **The application has never run outside a development machine.** No
   gunicorn, no nginx, no remote TLS database, no real SES send, no actual
   file uploaded to object storage. A staging rehearsal on a throwaway droplet
   before touching production is strongly recommended.

6. **There is no staging environment and no CI.** Deployment is manual
   (`git pull`, migrate, collectstatic, restart). Note also that a bare
   `pytest` runs only 87 of 1,181 tests because of a narrow `testpaths` in
   `pytest.ini` — the full suite is `pytest apps`.

7. **No error monitoring.** Errors go to `journalctl` only; nothing alerts.
   `SENTRY_DSN` is wired in `.env.example` but no account exists yet.

---

## 10. Verification after deployment

`DEPLOYMENT_RUNBOOK.md` §11 has the full smoke test. Minimum bar:

```bash
manage.py check --deploy          # no issues
curl -I https://<domain>/          # 200 or 302, not 502
curl -I https://<domain>/static/css/design-system.css   # 200
```

Plus: send one real email, upload one tenant logo and confirm it lands in
object storage, and complete one invite end to end.
