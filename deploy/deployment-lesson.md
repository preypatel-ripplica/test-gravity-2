# How PlugAI went from this laptop to Google Cloud

This is the deployment we did on 31 October 2026 for project `ripplicav2`.
Read it from top to bottom. Each section is one idea, then the file or command that made that idea real.

Botify was already running in the same project. Nothing in this deployment changes Botify.
Botify keeps its own Cloud Run services, its own image repository, its own load balancer, and the address `136.110.234.219`.
PlugAI uses names that start with `plugai` and the address `8.233.151.17`.

Update, same day: routing is now the simple Botify shape. `plugai.ripplica.com` sends every path to the frontend. `plugai.api.ripplica.com` sends every path to the backend. The advanced `/auth.` path rules were removed. The browser bundle calls `https://plugai.api.ripplica.com`. The sections below that describe path splitting are the first version. The host rules in `deploy/plugai-urlmap.yaml` are the current ones.

---

## 1. The problem we were solving

On your laptop the app is two processes.

- The frontend is a Vite React app. You run it with `npm run dev`. It listens on port 5173.
- The backend is a FastAPI app. You run it with uvicorn. It listens on port 8000.

The browser loads the React page from port 5173. The React code then calls paths such as `/auth.login` and `/client.list`. Those paths do not exist inside the React app. Vite, while it is in dev mode, forwards them to port 8000. That forwarding rule lives in `frontend/vite.config.js`:

```javascript
server: {
  port: 5173,
  proxy: {
    '^/(auth|user|project|client|channel|video|production|report|social|website|weekly|custom|tracker)\\..*': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
    '/health': {
      target: 'http://127.0.0.1:8000',
      changeOrigin: true,
    },
  },
}
```

`target` is the backend. `changeOrigin: true` rewrites the Host header so the backend sees the request as coming to itself.

That proxy exists only while `npm run dev` is running. `npm run build` produces static files: HTML, CSS, and JavaScript. Those files have no proxy. If you put them on a server by themselves, a call to `/auth.login` hits that server and gets the React page, or a 404, instead of FastAPI.

`frontend/src/api.js` decides the URL:

```javascript
const API_URL = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')

function url(path) {
  return `${API_URL}${path}`
}
```

`import.meta.env.VITE_API_URL` is baked in at build time. If it is empty, `url('/auth.login')` returns `/auth.login`. The browser then calls the same host that served the page.

So production needs something in front of both apps that does Vite's job: static files for pages, FastAPI for the dotted API paths. That something is a reverse proxy. We built two of them. Section 12 explains why there are two.

Google Cloud does not run `npm run dev` or a Python folder. It runs a container image. A container image is a packed filesystem plus the command that starts the process. Building that image, storing it, and running it is the first half of the deployment. Putting a public address and HTTPS in front of it is the second half.

---

## 2. Words, before the commands

**Project.** `ripplicav2` is the billing and permission boundary. Project number `952983432230` is the numeric id Google uses inside resource names. Botify and PlugAI share this project. They do not share services.

**Region.** `asia-south1` is Mumbai. Cloud Run, the image registry, and the serverless NEGs live there. The load balancer is global. A user in another country still hits the global load balancer, and the load balancer sends the request to Mumbai.

**gcloud.** The command-line client. Every later command is a Google API call made as the logged-in user `akshay@ripplica.com`.

**Image.** The output of `docker build`. It is not running yet. It is a file in a registry.

**Registry.** Artifact Registry repository `plugai`, in Mumbai. The full image name looks like this:

`asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-backend:local-20261031`

Read that from the right. `local-20261031` is the tag. `plugai-backend` is the image name. `plugai` is the repository. `ripplicav2` is the project. `asia-south1-docker.pkg.dev` is the registry host for that region.

**Cloud Run service.** A named service that runs a container. We have `plugai-backend` and `plugai-frontend`. A deploy creates a revision. Traffic points at the latest revision. The previous revision can stay in the list, but it receives no traffic after the new one is marked ready.

**Revision.** One immutable version of a service: one image, one set of environment variables, one CPU and memory size. Changing memory created revision `plugai-backend-00002-gbz`. The first deploy was `plugai-backend-00001-k5f`.

**Ingress.** Who is allowed to open a TCP connection to the service. `all` means the public internet can reach the `*.run.app` URL.

**Invoker IAM check.** A second door, after ingress. By default Cloud Run also asks "does this caller have `roles/run.invoker`?" The organization policy on this project refuses the member `allUsers`, so we could not grant the world that role. `--no-invoker-iam-check` turns that second door off. The app's own login, the JWT from `/auth.login`, is still required for protected API routes.

**Service account.** An identity for a program, not a person. `plugai-runtime` is the identity of the running containers. `plugai-deployer` is the identity GitHub Actions will use. Your user account was the identity for the first deploy from this Mac.

**Serverless NEG.** A network endpoint group whose only member is a Cloud Run service. It is the adapter a load balancer needs, because Cloud Run has no VM and no network interface you can attach yourself.

**Backend service.** A load-balancer object that points at a NEG and holds timeout and protocol settings. This is not the FastAPI backend. The names `plugai-backend-bs` and `plugai-frontend-bs` mean "load balancer backends".

**URL map.** The routing table. Host plus path decides which backend service gets the request.

**Target proxy.** The listener's brain. The HTTPS proxy owns the certificate and the URL map. The HTTP proxy owns the redirect map.

**Forwarding rule.** The thing that binds an IP address and a port to a target proxy. This is what makes `8.233.151.17:443` mean "use `plugai-https-proxy`".

**Google-managed certificate.** Google creates and renews the TLS certificate after it can see that `plugai.ripplica.com` resolves to the load balancer IP. We do not upload a certificate file to Wix.

---

## 3. Step 0. Log in

The saved login on this Mac had expired. This command started a fresh login and also refreshed Application Default Credentials, which client libraries use:

```bash
gcloud auth login --force --no-launch-browser --update-adc
```

- `--force` ignores the expired saved credential and starts a new browser flow.
- `--no-launch-browser` prints a URL instead of opening a browser on the machine running the command.
- `--update-adc` writes a second credential file used by Google client libraries.

You opened the URL, signed in as `akshay@ripplica.com`, and pasted the one-time code. Google exchanged that code for tokens stored under `~/.config/gcloud` on this Mac. The password was not stored.

Then we confirmed the project exists and billing is on:

```bash
gcloud projects describe ripplicav2
gcloud billing projects describe ripplicav2
```

`ripplicav2` is active. Billing account `015C34-41B499-867685` is linked. Cloud Run, Artifact Registry, Compute, and Cloud Build APIs were already enabled because Botify uses them. Enabling an API is project-wide. We did not disable or reconfigure Botify's use of those APIs.

Your local default project was left as `avid-atlas-509510-t8`. Every command passed `--project=ripplicav2`, so a command without that flag would still talk to the other project. When you run gcloud yourself for PlugAI:

```bash
gcloud config set project ripplicav2
```

---

## 4. Step 1. Identity for later deploys

These commands create identities. They do not deploy the app.

```bash
gcloud services enable sts.googleapis.com --project=ripplicav2
```

The Security Token Service is the API that later exchanges a GitHub token for a Google token.

```bash
gcloud artifacts repositories create plugai \
  --project=ripplicav2 \
  --location=asia-south1 \
  --repository-format=docker \
  --description="PlugAI container images. Not the botify repository."
```

This creates an empty Docker registry in Mumbai. Images pushed later land here. The existing repository named `botify` was not modified.

```bash
gcloud iam service-accounts create plugai-runtime \
  --project=ripplicav2 \
  --display-name="PlugAI Cloud Run runtime"

gcloud iam service-accounts create plugai-deployer \
  --project=ripplicav2 \
  --display-name="PlugAI GitHub Actions deployer"
```

`plugai-runtime@ripplicav2.iam.gserviceaccount.com` is attached to both Cloud Run services. The app talks to MongoDB and other APIs with keys from environment variables, so this account has no extra project roles.

`plugai-deployer@ripplicav2.iam.gserviceaccount.com` is only for GitHub Actions.

```bash
gcloud iam service-accounts add-iam-policy-binding \
  plugai-runtime@ripplicav2.iam.gserviceaccount.com \
  --project=ripplicav2 \
  --member="serviceAccount:plugai-deployer@ripplicav2.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

Cloud Run will not start a container as `plugai-runtime` unless the deployer is allowed to "act as" that account. This binding is on `plugai-runtime` only.

```bash
gcloud artifacts repositories add-iam-policy-binding plugai \
  --project=ripplicav2 \
  --location=asia-south1 \
  --member="serviceAccount:952983432230-compute@developer.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud artifacts repositories add-iam-policy-binding plugai \
  --project=ripplicav2 \
  --location=asia-south1 \
  --member="serviceAccount:plugai-deployer@ripplicav2.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

The first member is the Cloud Build identity. The first image build ran as that account. The second member is the GitHub deployer. Both can push to the `plugai` repository. This binding is on that repository, not on the `botify` repository.

```bash
gcloud projects add-iam-policy-binding ripplicav2 \
  --member="serviceAccount:plugai-deployer@ripplicav2.iam.gserviceaccount.com" \
  --role="roles/run.developer" \
  --condition='expression=resource.name.startsWith("projects/952983432230/locations/asia-south1/services/plugai-"),title=plugai-cloud-run-only,description=Deploy only plugai Cloud Run services'
```

`roles/run.developer` can deploy a new revision. The condition limits that power to Cloud Run service names starting with `plugai-` in Mumbai. A deploy of `botify-backend` does not match the condition.

Workload Identity Federation lets GitHub prove who it is without a downloaded JSON key:

```bash
gcloud iam workload-identity-pools create plugai-github \
  --project=ripplicav2 \
  --location=global \
  --display-name="PlugAI GitHub Actions"

gcloud iam workload-identity-pools providers create-oidc github \
  --project=ripplicav2 \
  --location=global \
  --workload-identity-pool=plugai-github \
  --display-name="GitHub PlugAI" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner" \
  --attribute-condition="assertion.repository=='preypatel-ripplica/test-gravity-2'"
```

The issuer is GitHub's token URL. The condition accepts tokens only from the repo `preypatel-ripplica/test-gravity-2`. The attribute mapping copies the repository name out of GitHub's token so the next binding can use it.

```bash
gcloud iam service-accounts add-iam-policy-binding \
  plugai-deployer@ripplicav2.iam.gserviceaccount.com \
  --project=ripplicav2 \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/952983432230/locations/global/workloadIdentityPools/plugai-github/attribute.repository/preypatel-ripplica/test-gravity-2"
```

That principal is allowed to impersonate `plugai-deployer`. The CD workflow uses this. The first deploy from the Mac did not. The Mac deploy used your user login.

The reserved address:

```bash
gcloud compute addresses create plugai-ip \
  --project=ripplicav2 \
  --global \
  --description="PlugAI load balancer. Not the Botify address."
```

Google assigned `8.233.151.17`. Global means the address is for a global load balancer, not for a VM in one zone. Reserving it early means the address stays yours even before the load balancer exists. Wix should point `plugai` at this address.

---

## 5. Step 2. The files we wrote

These files are the recipe. GCP does not read your Python folder until a build command uploads it.

### `.dockerignore`

Docker sends a context, which is a copy of the directory, to the builder. This file tells Docker what to leave out.

```
.git
.gcloudignore
**/.env
**/.env.*
!**/.env.example
**/node_modules
**/__pycache__
**/*.pyc
frontend/dist
backend/social_assets
backend/narration_cache
backend/reports
**/*.log
.DS_Store
.cursor
.venv
venv
```

The important line is `**/.env`. Secrets stay out of the image. They are injected later as Cloud Run environment variables. `node_modules` is omitted because `npm ci` inside the image installs Linux dependencies. Copying the Mac's `node_modules` would be wrong and large. `!**/.env.example` puts the example env file back in, because the previous lines excluded every `.env.*`.

### `deploy/backend.Dockerfile`

```dockerfile
FROM python:3.12-slim-bookworm
```

Start from the official Python 3.12 image based on Debian Bookworm, slim variant. The app's imports match this version. Slim means fewer OS packages, so the image is smaller before Playwright adds Chromium.

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
```

`PYTHONDONTWRITEBYTECODE` stops Python writing `__pycache__` inside the image. `PYTHONUNBUFFERED` makes print and log lines appear immediately in Cloud Run logs. Without it, Python buffers stdout and a crash can hide the last lines. `PIP_DISABLE_PIP_VERSION_CHECK` skips a network call that only checks whether pip is outdated.

```dockerfile
WORKDIR /app
```

Every later `COPY` and the start command use `/app` as the current directory. The Python import `backend.main.app` requires a folder named `backend` on the Python path. `/app` is that path, so the code must live at `/app/backend`.

```dockerfile
COPY backend/main/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && playwright install --with-deps chromium
```

Dependencies are copied and installed before the rest of the source. Docker caches layers. If you change application code but not `requirements.txt`, a later build reuses this layer and does not download every package again.

`--no-cache-dir` avoids storing pip's download cache in the image. `playwright install --with-deps chromium` downloads Chromium and the Debian libraries it needs. Monthly-report PDFs import Playwright. The Python process does not launch Chromium at startup. It launches Chromium only when a report render runs.

```dockerfile
COPY backend /app/backend
```

This copies the FastAPI code, routers, and prompts. It does not copy `.env`, because `.dockerignore` excluded it.

```dockerfile
EXPOSE 8080
CMD ["sh", "-c", "uvicorn backend.main.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
```

`EXPOSE` is documentation for humans. Cloud Run does not read it as the listen port. The `--port=8080` flag on the deploy command is what Cloud Run uses.

The command starts uvicorn. `backend.main.app:app` means the module `backend/main/app.py` and the variable `app` inside it. `--host 0.0.0.0` listens on every interface inside the container. `127.0.0.1` would refuse Cloud Run's health checks, because those checks come from outside the process. `${PORT:-8080}` uses Cloud Run's `PORT` variable when it is set, and 8080 otherwise.

What `app.py` does at startup matters here. The lifespan function calls `ping()` on MongoDB and `ensure_indexes()` before the process is willing to serve. If MongoDB is unreachable, the container exits and Cloud Run marks the revision unhealthy. On the first deploy, Atlas at `beacon.eeda219.mongodb.net` answered, so the revision became ready.

The same file mounts `/social_assets` as static files and registers every router. The route paths are dotted names such as `/auth.login` and `/client.list`, plus `/health`, `/docs`, `/social_assets`, and `/google.callback`. Those path prefixes are exactly what the load balancer and nginx match later.

### `deploy/frontend.Dockerfile`

This is a two-stage build. The first stage has Node and compiles the site. The second stage has only nginx and the compiled files. Node is not in the running container.

```dockerfile
FROM node:22-bookworm-slim AS build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ENV VITE_API_URL=
RUN npm run build
```

`AS build` names the stage so the next stage can copy from it. `npm ci` installs the exact versions in `package-lock.json`. `ENV VITE_API_URL=` sets an empty value. Vite inlines that into the JavaScript. Empty means `api.js` calls a relative path such as `/auth.login`. The browser will call whatever host the page came from.

`npm run build` writes `dist/`.

```dockerfile
FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

ENV PLUGAI_BACKEND_HOST=placeholder.invalid
EXPOSE 8080
```

The official nginx image listens on port 80 with a default site. We delete that site. Cloud Run sends traffic to port 8080, so our config listens on 8080.

The template is copied to `/etc/nginx/templates/`. On container start, the nginx image runs `envsubst` on every file there and writes the result to `/etc/nginx/conf.d/`. That is how `${PLUGAI_BACKEND_HOST}` becomes the real hostname. The hostname is a Cloud Run environment variable, set at deploy time, so we can point nginx at the backend without rebuilding the image.

`placeholder.invalid` is only the default if that variable is missing. The deploy command sets the real host.

`COPY --from=build` takes `dist` from the Node stage and puts it where nginx serves files.

### `deploy/nginx.conf.template`

```nginx
server {
    listen 8080;
    server_name _;
    client_max_body_size 32m;
```

One server block. `server_name _` accepts any Host header. `32m` matches Cloud Run's request body limit. A larger nginx limit would not help, because Cloud Run rejects the body first.

```nginx
    root /usr/share/nginx/html;
    index index.html;

    resolver 8.8.8.8 1.1.1.1 valid=30s ipv6=off;
    resolver_timeout 5s;
```

`root` is the built React app. The resolver is required because `proxy_pass` uses a variable. Nginx resolves variables at request time, not at startup. The backend hostname is stable, but this pattern is how nginx is willing to proxy to a name that came from the environment. `ipv6=off` keeps the lookup on IPv4. Cloud Run's public URL is reached over IPv4 from this nginx.

```nginx
    location ~ ^/(auth\.|user\.|project\.|client\.|channel\.|video\.|production\.|yt_metadata\.|report\.|social\.|social_assets|website\.|weekly\.|custom\.|tracker\.|google\.|cron/|health|docs|redoc|openapi\.json) {
        set $plugai_backend ${PLUGAI_BACKEND_HOST};
        proxy_pass https://$plugai_backend;
        proxy_ssl_server_name on;
        proxy_ssl_name $plugai_backend;
        proxy_set_header Host $plugai_backend;
```

`location ~` is a regular expression. The path must start with one of those prefixes. `/auth.` matches `/auth.login`. The dot is escaped so it is a literal dot. `/client.` matches `/client.list` and `/client.content-plan.get`. `/report.` also matches `/report.html/...` and `/report.pdf/...` because those strings start with `/report.`.

`/social.` does not match `/social_assets`, because the character after `social` is `_`, not `.`. That is why `/social_assets` is listed on its own. FastAPI serves uploaded files from that mount.

`proxy_pass https://$plugai_backend` opens an HTTPS connection to the backend Cloud Run URL and forwards the original path and method. `proxy_ssl_server_name on` sends SNI, which Cloud Run requires so it knows which service certificate to present. `Host` is set to the backend hostname. If nginx forwarded the browser's Host header (`plugai-frontend-....run.app`), Cloud Run would not recognize the request as belonging to `plugai-backend`.

```nginx
        proxy_set_header Authorization $http_authorization;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
```

`Authorization` is the user's JWT. It must be forwarded or every logged-in call looks anonymous. `X-Forwarded-For` records the client IP. `X-Forwarded-Proto` records whether the browser used http or https. HTTP/1.1 with an empty `Connection` header keeps the upstream connection available for streaming responses. `proxy_buffering off` lets progress events from long API calls reach the browser as they are produced. The read timeout is 3600 seconds so nginx itself does not cut off a long call. The load balancer in front of the domain has a shorter timeout. That difference is in section 11.

```nginx
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Any path that failed the API regex comes here. nginx looks for a real file, then a directory, then falls back to `index.html`. React Router uses paths such as `/login` and `/projects`. Those are not files. Returning `index.html` lets the React app boot and read the path itself. This is the standard single-page-app hosting rule.

This nginx config runs when the request reached the frontend container. For `https://plugai.ripplica.com`, the load balancer applies the same path split first and sends API paths straight to `plugai-backend`. Those requests never enter this nginx. The nginx copy exists so the frontend `*.run.app` URL is a working app on its own.

### `deploy/plugai-urlmap.yaml`

This file is the load balancer's routing table. It was imported with `gcloud compute url-maps import`. It is not read by Cloud Run.

```yaml
name: plugai-lb
defaultService: https://www.googleapis.com/compute/v1/projects/ripplicav2/global/backendServices/plugai-frontend-bs
```

If a request's host matches no host rule, send it to the frontend backend service. That covers a request that reaches the load balancer by raw IP.

```yaml
hostRules:
- hosts:
  - plugai.ripplica.com
  pathMatcher: plugai-paths
```

If the Host header is `plugai.ripplica.com`, use the path matcher named `plugai-paths`.

```yaml
pathMatchers:
- name: plugai-paths
  defaultService: https://www.googleapis.com/compute/v1/projects/ripplicav2/global/backendServices/plugai-frontend-bs
  routeRules:
  - priority: 1
    matchRules:
    - prefixMatch: /auth.
    service: https://www.googleapis.com/compute/v1/projects/ripplicav2/global/backendServices/plugai-backend-bs
```

Rules are checked by priority, lowest number first. `prefixMatch: /auth.` means "the path starts with `/auth.`". `/auth.login` matches. `/author` does not, because it does not have the dot. The first matching rule wins. If none match, `defaultService` is the frontend, so `/login` and `/assets/index-xxxxx.js` go to nginx and the React files.

The same shape repeats for `/user.`, `/project.`, `/client.`, `/channel.`, `/video.`, `/production.`, `/yt_metadata.`, `/report.`, `/social.`, `/social_assets`, `/website.`, `/weekly.`, `/custom.`, `/tracker.`, `/google.`, `/cron/`, `/health`, `/docs`, `/redoc`, and `/openapi.json`. All of those go to `plugai-backend-bs`.

`/health` is included so `https://plugai.ripplica.com/health` hits FastAPI and returns `{"ok":true}` once the certificate is active. `/docs` and `/openapi.json` are FastAPI's generated API docs.

### `deploy/plugai-http-redirect.yaml`

```yaml
name: plugai-http-redirect
defaultUrlRedirect:
  httpsRedirect: true
  redirectResponseCode: MOVED_PERMANENTLY_DEFAULT
```

This URL map has no backends. Every request is answered with a 301. `httpsRedirect: true` keeps the host and path and changes the scheme to https. `MOVED_PERMANENTLY_DEFAULT` is Google's name for HTTP 301. Browsers and caches may remember it.

We tested this. A request to `http://8.233.151.17` with `Host: plugai.ripplica.com` returned:

```text
HTTP/1.1 301 Moved Permanently
Location: https://plugai.ripplica.com:443/
```

The `:443` in the location is how this Google redirect is written. Browsers accept it. Botify's HTTP load balancer uses the same kind of redirect.

---

## 6. Step 3. Build the images

This Mac is Apple Silicon (`arm64`). Docker was not running. Cloud Run runs `linux/amd64`. An image built for arm64 would fail to start.

Cloud Build is a Google service that runs `docker build` on amd64 machines. The recipe was `deploy/cloudbuild.yaml`. That file has since been deleted, because the ongoing CD workflow builds on GitHub's amd64 runners and does not need Cloud Build. The first images were produced by it. This is what it did:

- Two steps, started together (`waitFor: ["-"]` means "do not wait for another step").
- Step `backend`: `docker build -f deploy/backend.Dockerfile`, tags `plugai-backend:local-20261031` and `plugai-backend:latest`.
- Step `frontend`: the same for `plugai-frontend`.
- `images:` tells Cloud Build to push those tags to Artifact Registry when the build succeeds.
- `machineType: E2_HIGHCPU_8` gives the build eight CPUs so `npm ci` and `pip install` finish sooner.
- `logging: CLOUD_LOGGING_ONLY` sends build logs to Cloud Logging.
- `timeout: 2400s` allows 40 minutes. Playwright's Chromium download is the slow part.

The command:

```bash
gcloud builds submit \
  --project=ripplicav2 \
  --region=asia-south1 \
  --config=deploy/cloudbuild.yaml \
  --substitutions=_TAG=local-20261031 \
  .
```

`gcloud builds submit` tars the current directory, skipping files in `.gcloudignore` or `.gitignore`. The archive was about 2.6 MB of source. It was uploaded to the project's existing Cloud Build bucket `gs://ripplicav2_cloudbuild`. That bucket is a staging area for source uploads. The upload did not modify Botify services. `.env` was not in the archive.

Build id `a3ed3fa4-a16e-4c61-954b-ea533368fcea` finished with status `SUCCESS`. The registry then contained:

```text
asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-backend:latest
asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-backend:local-20261031
asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-frontend:latest
asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-frontend:local-20261031
```

A tag is a pointer. `:latest` and `:local-20261031` point at the same image from that build. The next build can move `:latest` to a new image. The old tag `local-20261031` stays on the old image, which is how you know what the first deploy ran.

---

## 7. Step 4. Run the images on Cloud Run

Environment variables were written to a temporary YAML file from `backend/.env` and passed with `--env-vars-file`. The file was deleted after the deploy. The values now live in the Cloud Run service configuration. They were not baked into the image. The localhost URLs were copied through on purpose. CORS was updated afterward. Section 14 lists what is still localhost.

```bash
gcloud run deploy plugai-backend \
  --project=ripplicav2 \
  --region=asia-south1 \
  --image=asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-backend:local-20261031 \
  --service-account=plugai-runtime@ripplicav2.iam.gserviceaccount.com \
  --ingress=all \
  --allow-unauthenticated \
  --min-instances=1 \
  --max-instances=10 \
  --cpu=1 \
  --memory=2Gi \
  --timeout=3600 \
  --execution-environment=gen2 \
  --port=8080 \
  --env-vars-file=/tmp/plugai-env.yaml \
  --labels=app=plugai
```

What each flag does:

- `--image` is the registry path Cloud Run pulls.
- `--service-account` is the identity of the running process.
- `--ingress=all` publishes the `*.run.app` URL on the internet.
- `--allow-unauthenticated` tries to grant `allUsers` the invoker role. The organization policy rejected that grant. The service still deployed. We fixed public access in the next command.
- `--min-instances=1` keeps one container running when nobody is calling. You chose this. It is billed all month.
- `--max-instances=10` stops a traffic spike from scaling without a ceiling.
- `--cpu=1` gives that instance one vCPU while it is handling a request. This is not an EC2 size such as t2.micro. Cloud Run does not have instance families. You set CPU and memory directly.
- `--memory=2Gi` was the first size, chosen because Chromium is in the image. You later asked for 1Gi. That change is section 13.
- `--timeout=3600` is the maximum time one request may run on Cloud Run, in seconds. One hour.
- `--execution-environment=gen2` is the second-generation Cloud Run sandbox. It is the right environment for heavier binaries such as Chromium.
- `--port=8080` is the port Cloud Run connects to. It must match uvicorn.
- `--labels=app=plugai` is a tag for filtering in the console. It does not affect routing.

The first revision was `plugai-backend-00001-k5f`.

Public access, after `allUsers` was refused:

```bash
gcloud run services update plugai-backend \
  --project=ripplicav2 \
  --region=asia-south1 \
  --no-invoker-iam-check \
  --ingress=all
```

`--no-invoker-iam-check` disables the Google identity check. Anyone who can open the URL can make the HTTP request. FastAPI still rejects protected routes that have no valid JWT.

Frontend:

```bash
gcloud run deploy plugai-frontend \
  --project=ripplicav2 \
  --region=asia-south1 \
  --image=asia-south1-docker.pkg.dev/ripplicav2/plugai/plugai-frontend:local-20261031 \
  --service-account=plugai-runtime@ripplicav2.iam.gserviceaccount.com \
  --ingress=all \
  --no-invoker-iam-check \
  --min-instances=1 \
  --max-instances=10 \
  --cpu=1 \
  --memory=512Mi \
  --timeout=300 \
  --port=8080 \
  --set-env-vars=PLUGAI_BACKEND_HOST=plugai-backend-952983432230.asia-south1.run.app \
  --labels=app=plugai
```

512Mi is enough for nginx and static files. The timeout is 300 seconds. The only environment variable is the backend host, with no `https://` and no path. nginx adds the scheme.

Cloud Run gives every service two public hostnames. Both reached `/health` with HTTP 200:

- `https://plugai-backend-533nzc4d3a-el.a.run.app`
- `https://plugai-backend-952983432230.asia-south1.run.app`

The same pair exists for the frontend. They are one service with two names. `533nzc4d3a-el` is the older hostname style. The project-number hostname is the newer style. nginx was pointed at the project-number host. A request to the frontend URL's `/health` returned `{"ok":true}`, which proved nginx proxied that path to FastAPI. A request to `/` returned the React `index.html` with the title "Plug Internal".

---

## 8. Step 5. Serverless NEGs

A load balancer sends traffic to a backend that has an endpoint. A VM backend has an IP. Cloud Run does not give you an IP inside your VPC to attach. A serverless NEG is the object that means "the endpoint is this Cloud Run service".

```bash
gcloud compute network-endpoint-groups create plugai-backend-neg \
  --project=ripplicav2 \
  --region=asia-south1 \
  --network-endpoint-type=serverless \
  --cloud-run-service=plugai-backend

gcloud compute network-endpoint-groups create plugai-frontend-neg \
  --project=ripplicav2 \
  --region=asia-south1 \
  --network-endpoint-type=serverless \
  --cloud-run-service=plugai-frontend
```

`--network-endpoint-type=serverless` is the whole feature. The NEG must be in the same region as the Cloud Run service. You do not add IPs to it. `--cloud-run-service` is the only member.

Google's load-balancer software, after this exists, knows how to open a connection to that Cloud Run service. You do not install a proxy package for this hop. You do not write the route rules here. The NEG is only the pointer.

---

## 9. Step 6. Backend services, and the two mistakes

A backend service is the load balancer's view of one group of endpoints. It holds the protocol, the timeout, and the attached NEG.

```bash
gcloud compute backend-services create plugai-backend-bs \
  --project=ripplicav2 \
  --global \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --protocol=HTTPS

gcloud compute backend-services create plugai-frontend-bs \
  --project=ripplicav2 \
  --global \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --protocol=HTTPS \
  --timeout=30
```

`EXTERNAL_MANAGED` is the current global external Application Load Balancer. It is the same scheme Botify uses. "External" means clients on the internet. "Managed" means Google's Envoy-based proxies, not the older classic load balancer. "Global" means the forwarding rule is not tied to one region, even though the Cloud Run services are in Mumbai.

`--protocol=HTTPS` is the protocol on the hop from Google's proxy to Cloud Run. The browser's HTTPS is a different hop. It ends at the target HTTPS proxy, where the certificate is. Between the proxy and Cloud Run, Google connects to the Cloud Run service URL over HTTPS. That is why the protocol is HTTPS even though we never installed a certificate on the container.

The first attach failed:

```text
Invalid value for field 'resource.portName': 'https'.
Port name is not supported for a backend service with Serverless network endpoint groups.
```

Creating the backend service with protocol HTTPS filled in a port name of `https`. Serverless NEGs have no ports. Botify's working backend service uses protocol HTTPS and port name `http`. We matched that:

```bash
gcloud compute backend-services update plugai-backend-bs --global --port-name=http
gcloud compute backend-services update plugai-frontend-bs --global --port-name=http
```

The second attach failed because the API timeout had been set to 3600:

```text
Timeout sec is not supported for a backend service with Serverless network endpoint groups.
```

Setting the timeout back to 30 allowed the attach. Raising it to 300 after the attach was also rejected. For this type of backend, the load balancer timeout stays at 30 seconds.

```bash
gcloud compute backend-services add-backend plugai-backend-bs \
  --project=ripplicav2 \
  --global \
  --network-endpoint-group=plugai-backend-neg \
  --network-endpoint-group-region=asia-south1

gcloud compute backend-services add-backend plugai-frontend-bs \
  --project=ripplicav2 \
  --global \
  --network-endpoint-group=plugai-frontend-neg \
  --network-endpoint-group-region=asia-south1
```

After this, `plugai-backend-bs` means "send to the NEG that means the Cloud Run service `plugai-backend`". Same for the frontend.

What the 30 second limit means in practice: a request that enters through `plugai.ripplica.com` can be closed by the load balancer at 30 seconds. The same request sent directly to `https://plugai-backend-....run.app` is allowed to run until the Cloud Run timeout of 3600 seconds. Long OpenAI or PDF calls are safer on the run.app URL until this limit is solved another way.

---

## 10. Step 7. URL map, certificate, proxies, forwarding rules

Import the routing table. The backend services must already exist, because the YAML names them.

```bash
gcloud compute url-maps import plugai-lb \
  --project=ripplicav2 \
  --global \
  --source=deploy/plugai-urlmap.yaml \
  --quiet
```

Create the certificate. This does not ask Wix for anything. It records that we want a certificate for one name.

```bash
gcloud compute ssl-certificates create plugai-cert \
  --project=ripplicav2 \
  --global \
  --domains=plugai.ripplica.com
```

Status at creation was `PROVISIONING`. It stays there until public DNS for `plugai.ripplica.com` points at `8.233.151.17` and Google has checked that. Then it becomes `ACTIVE`. Google renews it after that. There is no certificate file to paste into Wix.

Attach the certificate and the URL map to an HTTPS proxy:

```bash
gcloud compute target-https-proxies create plugai-https-proxy \
  --project=ripplicav2 \
  --global \
  --url-map=plugai-lb \
  --ssl-certificates=plugai-cert
```

The HTTPS proxy is where TLS ends. It decrypts the request, then asks the URL map where to send the plain HTTP request internally.

The HTTP side is a different map and a different proxy:

```bash
gcloud compute url-maps import plugai-http-redirect \
  --project=ripplicav2 \
  --global \
  --source=deploy/plugai-http-redirect.yaml \
  --quiet

gcloud compute target-http-proxies create plugai-http-proxy \
  --project=ripplicav2 \
  --global \
  --url-map=plugai-http-redirect
```

Bind the reserved IP:

```bash
gcloud compute forwarding-rules create plugai-https \
  --project=ripplicav2 \
  --global \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --address=plugai-ip \
  --target-https-proxy=plugai-https-proxy \
  --ports=443

gcloud compute forwarding-rules create plugai-http \
  --project=ripplicav2 \
  --global \
  --load-balancing-scheme=EXTERNAL_MANAGED \
  --address=plugai-ip \
  --target-http-proxy=plugai-http-proxy \
  --ports=80
```

One IP, two ports, two proxies. Port 80 redirects. Port 443 routes. The scheme has to match the backend services. Mixing classic and managed resources in one chain is rejected.

Until the certificate is `ACTIVE`, a TLS handshake to this IP fails. That is the certificate waiting for DNS. The Cloud Run URLs keep working because they use Google's existing `run.app` certificate, which is a different certificate on a different front door.

---

## 11. How the pieces connect

This is the chain, from the name you type to the process that answers.

```text
Browser
  |
  |  DNS A record plugai.ripplica.com -> 8.233.151.17
  |  (you set this in Wix)
  v
Forwarding rule plugai-http     :80   -> target HTTP proxy  -> URL map plugai-http-redirect
Forwarding rule plugai-https    :443  -> target HTTPS proxy -> certificate plugai-cert
                                                              -> URL map plugai-lb
                                                                    |
                                                                    |  host plugai.ripplica.com
                                                                    |  path /auth. , /client. , /health, ...
                                                                    v
                                                              backend service plugai-backend-bs
                                                                    |
                                                                    v
                                                              serverless NEG plugai-backend-neg
                                                                    |
                                                                    v
                                                              Cloud Run plugai-backend
                                                                    |
                                                                    v
                                                              uvicorn, FastAPI, MongoDB

                                                                    |  any other path, such as / or /login
                                                                    v
                                                              backend service plugai-frontend-bs
                                                                    |
                                                                    v
                                                              serverless NEG plugai-frontend-neg
                                                                    |
                                                                    v
                                                              Cloud Run plugai-frontend
                                                                    |
                                                                    v
                                                              nginx serves dist/index.html
```

There is also a side door that does not use the load balancer:

```text
Browser opens https://plugai-frontend-....run.app/auth.login
  -> Cloud Run plugai-frontend
  -> nginx matches the API regex
  -> HTTPS request to plugai-backend-....run.app
  -> Cloud Run plugai-backend
```

And:

```text
Browser opens https://plugai-backend-....run.app/health
  -> Cloud Run plugai-backend directly
```

---

## 12. Where the reverse proxy is, and what Google does automatically

A reverse proxy accepts a request from a client and forwards it to another server. The client talks to the proxy's address. The client does not open a connection to the final process.

**Proxy 1 is the load balancer.** We built it. Google did not invent the routes. `deploy/plugai-urlmap.yaml` is the list of routes. Google does supply the proxy software that enforces that list. We did not install Envoy or nginx on a VM for this. `EXTERNAL_MANAGED` means those proxies already run on Google's edge. Creating the forwarding rule attaches our IP to that fleet.

The automatic part is the hop from the proxy to Cloud Run. After the NEG says `cloud-run-service=plugai-backend`, Google's proxy knows the current address of that service, opens TLS to it, and sends the original path. We do not configure that connection's IP, and it changes as Cloud Run moves instances. That is the value of a serverless NEG.

The URL map is not automatic. If a new API prefix is added in FastAPI and it is not in the URL map, `https://plugai.ripplica.com/that.new.path` falls through to the frontend. nginx on the frontend has the same list, so the frontend `*.run.app` URL would still proxy it, but the public domain would serve `index.html` for that path until the URL map is updated. When you add a new top-level path prefix, update both `deploy/plugai-urlmap.yaml` and `deploy/nginx.conf.template`, import the URL map again, and redeploy the frontend image.

**Proxy 2 is nginx** inside `plugai-frontend`. We wrote every line of it. Google does not generate it. It runs only for requests that entered the frontend container.

Local Vite is proxy 0. It is not deployed. Production does not run Vite.

CORS sits behind this. `backend/main/app.py` installs `CORSMiddleware` with the origins from `CORS_ORIGINS`. A browser enforces CORS only when the page's host and the request's host differ. On `https://plugai.ripplica.com`, the page and `/auth.login` are the same host, because the load balancer split the path after the browser sent the request. The browser does not treat that as cross-origin. The CORS list still matters if some future page on another host calls the API directly.

---

## 13. The memory change

The first backend size was 1 CPU and 2Gi. You asked for 1Gi. One command changed the live service and the CORS value together:

```bash
gcloud run services update plugai-backend \
  --project=ripplicav2 \
  --region=asia-south1 \
  --memory=1Gi \
  --update-env-vars='^@^CORS_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:5175,https://plugai.ripplica.com'
```

`^@^` changes the separator from comma to `@`, because the CORS value itself contains commas. Without that, gcloud would split the origins into broken environment variables.

This created revision `plugai-backend-00002-gbz` and moved 100 percent of traffic to it. A later describe showed memory `1Gi` and CPU `1`. `/health` still returned `{"ok":true}`.

`cd.yml` was updated to `--memory=1Gi` so the next GitHub deploy does not set 2Gi again.

Chromium for PDF reports can run out of memory at 1Gi. The API process fits. If a PDF render is killed, the size can be raised with the same update command and a new revision.

Current sizes:

| Service | CPU | Memory | Minimum instances | Maximum instances | Request timeout |
|---|---|---|---|---|---|
| plugai-frontend | 1 | 512Mi | 1 | 10 | 300 seconds |
| plugai-backend | 1 | 1Gi | 1 | 10 | 3600 seconds on Cloud Run, 30 seconds through the load balancer |

---

## 14. Environment variables and CORS

The first deploy copied `backend/.env` onto `plugai-backend`. URL-shaped values were left as they were. These are still localhost and will send OAuth and redirects to your laptop until you change them on the Cloud Run service:

- `BASE_URL`
- `FRONTEND_URL`
- `GOOGLE_REDIRECT_URI`
- `INSTAGRAM_REDIRECT_URI`
- `FACEBOOK_REDIRECT_URI`
- `PLUG_INSTA_REDIRECT_URI`
- `GBP_REDIRECT_URI`
- `GOOGLE_OAUTH_REDIRECT_URL`

Changing them does not require a new image. Either edit the variables in the Cloud Run console and deploy a new revision, or run:

```bash
gcloud run services update plugai-backend \
  --project=ripplicav2 \
  --region=asia-south1 \
  --update-env-vars=BASE_URL=https://plugai.ripplica.com
```

Use a custom separator, as in section 13, if the value contains a comma.

The Google Cloud console OAuth client, and the Meta app, also need the new redirect URLs allowed. The env var and the provider's allow-list are two different settings. Both have to match.

CORS was `http://localhost:5173`, `http://localhost:5174`, `http://localhost:5175`, and `https://app.xyz`. It was not a testgravity host. `https://app.xyz` was a placeholder in the example env. It is now `https://plugai.ripplica.com` in:

- the live Cloud Run service
- `backend/.env`
- `backend/.env.example`
- the default string in `backend/main/config.py`

Localhost remains so local `npm run dev` is still allowed by the middleware.

`cd.yml` does not pass an env file. A CD deploy updates the image and the flags written in the workflow. Environment variables that are already on the service stay.

---

## 15. CI and CD

Two files, two jobs.

### `.github/workflows/ci.yml`

```yaml
name: CI

on:
  push:
  pull_request:
```

GitHub runs this on every push and every pull request. Nobody clicks a button. It does not authenticate to Google and it does not deploy.

The frontend job checks out the repo, installs Node 22, runs `npm ci`, `npm run lint`, and `npm run build` inside `frontend/`. That proves the React app compiles. It does not build the nginx image.

The backend job installs Python 3.12, installs `backend/main/requirements.txt`, and runs `python -m compileall -q backend`. That proves the Python files parse and the dependencies resolve. It does not download Chromium and it does not start the server. Starting the server would try to ping MongoDB, which CI is not configured to do.

### `.github/workflows/cd.yml`

```yaml
on:
  workflow_dispatch:
    inputs:
      environment:
        type: choice
        default: production
        options:
          - production
```

`workflow_dispatch` means the workflow runs only when a person opens Actions, chooses CD, and clicks Run workflow. The choice input is the environment dropdown. The job also sets:

```yaml
environment: ${{ inputs.environment }}
```

GitHub records the run under the environment named `production`. You can later add reviewers on that environment in the repo settings. Until you do, selecting it and confirming is enough to start the deploy.

```yaml
permissions:
  contents: read
  id-token: write
```

`contents: read` lets the job read the repo. `id-token: write` lets the job ask GitHub for an OIDC token. That token is what Workload Identity Federation exchanges. There is no JSON key in the repo.

The auth step names the provider and the deployer service account created in section 4. `gcloud auth configure-docker` writes a Docker credential helper so `docker push` to `asia-south1-docker.pkg.dev` is allowed.

Then the job runs the same Dockerfiles we used the first time, on GitHub's Ubuntu runner, which is amd64. Tags are the git commit SHA and `latest`. The SHA tag does not move. You can roll back by deploying an older SHA.

`gcloud run deploy` uses the new image and repeats the service flags: ingress, invoker check, instance counts, CPU, memory, timeout, port, runtime service account. It does not pass `--set-env-vars` or `--env-vars-file`, so the CORS value and the localhost URLs you later edit remain on the service.

### What `deploy-plugai.yml` was

The first CD file was named `.github/workflows/deploy-plugai.yml`. It was the same manual production deploy. It was deleted when the workflow was split. The deploy job now lives in `cd.yml`. There was never a file named `deploy.yml`. `ci.yml` did not exist in that first version. It was added when the single deploy file became the CI file plus the CD file.

`deploy/cloudbuild.yaml` and `.gcloudignore` were also deleted after the first build. They belonged to `gcloud builds submit` from the Mac. CD does not call Cloud Build.

These files stay because the system still uses them:

- `deploy/backend.Dockerfile` and `deploy/frontend.Dockerfile` are what CD builds.
- `deploy/nginx.conf.template` is copied into the frontend image.
- `deploy/plugai-urlmap.yaml` and `deploy/plugai-http-redirect.yaml` are the load balancer config that was imported. The live load balancer does not re-read them on each deploy. If you change a route, you import the file again. CD does not import them.

---

## 16. What you are doing in Wix, and what happens after

In Wix, for the domain `ripplica.com`:

| Field | Value |
|---|---|
| Type | A |
| Host | plugai |
| Value | 8.233.151.17 |

Leave Botify's records on `136.110.234.219`.

After DNS is visible worldwide, Google finishes `plugai-cert`. The status moves from `PROVISIONING` to `ACTIVE`. That often takes 15 to 60 minutes and can take longer. Then this is true:

- `http://plugai.ripplica.com/...` receives a 301 to `https://plugai.ripplica.com/...`
- `https://plugai.ripplica.com/` returns the React app
- `https://plugai.ripplica.com/health` returns `{"ok":true}` from FastAPI
- `https://plugai.ripplica.com/auth.login` is handled by FastAPI

Until the certificate is active, use the Cloud Run URLs. They already work.

---

## 17. Names, in one place

| Thing | Name |
|---|---|
| Project | ripplicav2 |
| Project number | 952983432230 |
| Region | asia-south1 |
| Image repository | plugai |
| Backend image | plugai-backend |
| Frontend image | plugai-frontend |
| Cloud Run services | plugai-backend, plugai-frontend |
| Runtime service account | plugai-runtime |
| Deployer service account | plugai-deployer |
| GitHub identity pool | plugai-github, provider github |
| Serverless NEGs | plugai-backend-neg, plugai-frontend-neg |
| Load balancer backends | plugai-backend-bs, plugai-frontend-bs |
| HTTPS URL map | plugai-lb |
| HTTP redirect map | plugai-http-redirect |
| Certificate | plugai-cert |
| HTTPS proxy | plugai-https-proxy |
| HTTP proxy | plugai-http-proxy |
| Address name | plugai-ip |
| Address | 8.233.151.17 |
| Forwarding rules | plugai-https, plugai-http |
| Domain | plugai.ripplica.com |
