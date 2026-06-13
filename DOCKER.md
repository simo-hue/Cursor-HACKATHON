# Docker guide (fallback dev environment)

> **You probably don't need this.** The default way to run the starter is native: `uv` + Python (see `README.md`, two commands). Use Docker only if you can't or don't want to install Python tooling on your machine. The Railway deploy does NOT use Docker either - Railway builds the app by itself (see `DEPLOY.md`).

## 1. Install Docker Desktop

Download from https://www.docker.com/products/docker-desktop/ - **no Docker account required**, skip any sign-in prompt.

Pick your build:

- **Mac**: Apple Silicon (M1/M2/M3/M4) or Intel chip - check  -> About This Mac if unsure.
- **Windows**: AMD64 (the common one) or ARM64. During install, keep the **WSL2** option enabled (default). If Docker asks to enable WSL2/virtualization, accept and reboot.
- **Linux**: Docker Desktop or plain `docker` + `docker compose` from your package manager.

After install, **start Docker Desktop** and wait for the whale icon to settle. Verify in a terminal:

```bash
docker --version
docker ps        # must not error (an empty list is fine)
```

## 2. Run the dev environment

From the starter root (where `docker-compose.dev.yml` lives):

```bash
# First time: create your env file and fill it in
cp backend/.env.example backend/.env

# Start (build happens automatically the first time)
docker compose -f docker-compose.dev.yml up -d
```

Then open http://localhost:8000 - the starter UI. API docs at http://localhost:8000/docs.

Your code is bind-mounted: edit files on your machine and the server hot-reloads inside the container.

## 3. Everyday commands

You can also just ask Cursor ("start the dev environment", "show me the backend logs") - these are the commands behind it:

```bash
docker compose -f docker-compose.dev.yml up -d        # start
docker compose -f docker-compose.dev.yml logs -f      # tail logs
docker compose -f docker-compose.dev.yml down         # stop
docker compose -f docker-compose.dev.yml up -d --build  # rebuild (after changing pyproject.toml)
docker compose -f docker-compose.dev.yml restart      # restart (hot reload misbehaving)
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Cannot connect to the Docker daemon` | Docker Desktop isn't running. Start it and wait for the whale icon. |
| Port `8000` already in use | Something else is on 8000. Stop it, or change the mapping in `docker-compose.dev.yml` to `"8001:8000"` and use localhost:8001. |
| Added a dependency but the container doesn't see it | Dependencies install at build time: `docker compose -f docker-compose.dev.yml up -d --build`. |
| Hot reload stopped working | `docker compose -f docker-compose.dev.yml restart`. |
| Windows: WSL2 errors at startup | Open PowerShell as Administrator, run `wsl --update`, reboot, restart Docker Desktop. |
| Changes to `.env` not picked up | Containers read env at start: `down` then `up -d`. |

If Docker keeps fighting you, switch to the native path (`README.md` -> Quick start): it is one `uv sync` away and a Yellow Tech mentor in the room can help.
