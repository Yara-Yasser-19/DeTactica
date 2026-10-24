# DeTactica

A server-rendered sports coaching app with Arabic and English interfaces.

## Tech stack

- Python 3.12 (the version declared in `.python-version` and used by Docker).
- Flask 3.1.1 with Jinja2 HTML templates, CSS, and vanilla JavaScript.
- Flask-Login 0.6.3 for authentication and Werkzeug password hashing.
- Flask-SQLAlchemy 3.1.1: SQLite by default, or PostgreSQL through Psycopg 3
  when `DATABASE_URL` is set.
- Gmail SMTP for password reset emails. No Node.js build step is required.
- Gunicorn serves the Docker deployment with one worker and four threads.

## Run with Docker Compose

Install Docker Engine and the Compose plugin on the server, or Docker Desktop
with Linux containers on Windows/macOS.

1. Copy `.env.example` to `.env`:

   ```sh
   cp .env.example .env
   ```

   In PowerShell, use `Copy-Item .env.example .env`.

2. Generate a secret and put it after `DETACTICA_SECRET_KEY=` in `.env`:

   ```sh
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   If Python is unavailable on the host:

   ```sh
   docker run --rm python:3.12-slim-bookworm python -c "import secrets; print(secrets.token_hex(32))"
   ```

3. Build and start:

   ```sh
   docker compose up -d --build
   docker compose ps
   docker compose logs -f web
   ```

Open `http://localhost:8080` locally, or `http://SERVER_IP:8080` on your server.
Change `HOST_PORT` in `.env` if needed. The service restarts automatically after
Docker restarts. `/healthz` checks HTTP and database connectivity and is used by
the image's health check. Docker marks unhealthy containers but does not restart
them merely because they become unhealthy.

Tables, subscription plans, sports, and sample exercises are created on startup.
Register through `/register`; there is no default administrator account.

## Data and databases

By default, SQLite is stored at `/app/instance/coachflow.db` in the named
`detactica_data` volume (prefixed by the Compose project name). Rebuilding the
image, recreating the container, and `docker compose down` preserve this volume.
`docker compose down -v` deletes it and all SQLite data.

For PostgreSQL, set `DATABASE_URL` to an existing database connection string.
`postgres://`, `postgresql://`, and `postgresql+psycopg://` are supported. Use the
database server's network address; `localhost` inside the container refers to
the app container. URL-encode special characters in credentials. A database URL
does not migrate existing SQLite data. This Compose file runs only the app;
it does not provision PostgreSQL.

To import an existing local SQLite database, start the service once to create
the volume, then stop it and replace the generated file:

```sh
docker compose stop web
docker compose cp ./instance/coachflow.db web:/app/instance/coachflow.db
docker compose run --rm --no-deps --user root web chown 10001:10001 /app/instance/coachflow.db
docker compose up -d
```

Make a backup first. Copy the source database only while its original app is
stopped. To back up the hosted SQLite database consistently:

```sh
docker compose stop web
docker compose cp web:/app/instance/coachflow.db ./coachflow-backup.db
docker compose start web
```

The app initializes and seeds its database when imported. Keep this deployment
to one app container and one Gunicorn worker. Scaling across workers/replicas
requires moving initialization into a separate migration/bootstrap step first.

## Public HTTPS hosting

Point your domain at the server and terminate HTTPS in a reverse proxy such as
your hosting platform's ingress. Forward requests to container port `8000`, or
host port `8080` if the proxy runs on the host.

For one trusted HTTPS proxy, set these in `.env` and recreate the service with
`docker compose up -d`:

```dotenv
DETACTICA_SECURE_COOKIES=1
DETACTICA_TRUST_PROXY=1
HOST_BIND=127.0.0.1
```

`HOST_BIND=127.0.0.1` is for a proxy running on the same host. With a containerized
proxy, connect it to the app's Docker network and route to `web:8000` instead.
The proxy must preserve the public `Host` and overwrite `X-Forwarded-For` and
`X-Forwarded-Proto`. Proxy trust assumes exactly one trusted hop. Restrict direct
access to the app when enabling it. Correct forwarded protocol handling ensures
password reset links use HTTPS. Keep secure cookies disabled for local HTTP.

For password reset emails, set `DETACTICA_GMAIL_APP_PASSWORD` to a Gmail App
Password for the existing sender `deetactica@gmail.com`. Other features run
without mail credentials. Keep the secret stable across deployments to retain
sessions and outstanding reset links. Never commit real credentials.

## Build and run without Compose

Use `.env` configured as above:

```sh
docker build -t detactica .
docker volume create detactica_data
docker run -d --name detactica --restart unless-stopped --init --env-file .env -p 8080:8000 -v detactica_data:/app/instance detactica
```

Platforms that build from a Dockerfile can use this image directly. Inject
`DETACTICA_SECRET_KEY` and either mount persistent storage at `/app/instance` or
configure PostgreSQL. If a bind mount is used, it must be writable by UID/GID
`10001:10001`. `PORT` defaults to `8000` and can be overridden by the platform;
configure routing to that same port. The image runs as an unprivileged user,
logs to stdout/stderr, and runs without Flask's development debugger.

## Deploy with Coolify

Create an application from this Git repository and select the **Dockerfile**
build pack. Set the exposed application port to `8000` and the health check path
to `/healthz`. Add `DETACTICA_SECRET_KEY` as a runtime environment variable. For
HTTPS behind one trusted proxy, also set `DETACTICA_SECURE_COOKIES=1` and
`DETACTICA_TRUST_PROXY=1`.

Add persistent storage mounted at `/app/instance`, writable by UID/GID
`10001:10001`, for SQLite; alternatively, set `DATABASE_URL` to a PostgreSQL
database. Configure the application's domain and enable automatic deployment
for the intended Git branch. A Coolify installation using **Custom (None)** as
its proxy needs a separate route in its external reverse proxy for this app.

## Local Python development

```sh
python -m venv .venv
# Activate the virtual environment for your shell.
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`. This starts Flask's development server with debug
enabled; use the Docker/Gunicorn deployment for hosting.
