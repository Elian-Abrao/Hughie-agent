# Hughie Agent

Hughie é um agente pessoal persistente com backend em Python, memória semântica em Postgres + pgvector, API FastAPI e frontend React/Vite.

## Desenvolvimento local

Backend:

```bash
python -m venv .venv
source .venv/bin/activate
pip install ./providers/codex-bridge-sdk
pip install ".[serve]"
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

Testes e build:

```bash
./.venv/bin/pytest tests/unit -q
cd frontend && npm run build
```

## Produção

O repositório mantém dois caminhos de compose:

- `docker-compose.yml`: desenvolvimento/local, com `build` direto do código-fonte.
- `docker-compose.prod.yml`: produção, usando imagens publicadas no GHCR.

O deploy de produção passa a usar o script `scripts/deploy-prod.sh`, que:

```bash
git pull --ff-only origin main
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

Além disso, ele valida os endpoints de saúde do backend, broker e frontend.

### `.env` de produção

Use `.env.production.example` como base para o `.env` no servidor.

## CI/CD

### CI

O workflow `.github/workflows/ci.yml` roda:

- testes unitários do backend
- build do frontend

### CD

O workflow `.github/workflows/cd.yml`:

1. publica as imagens `broker`, `hughie` e `frontend` no GHCR
2. acessa o servidor por SSH
3. atualiza o checkout com `git pull --ff-only`
4. executa o deploy remoto usando `docker-compose.prod.yml`

### Secrets esperados no GitHub

Para o workflow de deploy, configure estes secrets:

- `PROD_SSH_HOST`
- `PROD_SSH_PORT`
- `PROD_SSH_USER`
- `PROD_SSH_PRIVATE_KEY`
- `PROD_APP_DIR`
- `GHCR_USERNAME`
- `GHCR_TOKEN`

Sugestão de valores no ambiente atual:

- `PROD_SSH_HOST`: `home-server`
- `PROD_SSH_PORT`: `22`
- `PROD_SSH_USER`: seu usuário no servidor
- `PROD_APP_DIR`: `/home/elian/services/hughie`

## Fluxo recomendado

1. Abrir PR
2. Aguardar CI verde
3. Fazer merge na `main`
4. Deixar o workflow de CD publicar as imagens e executar o deploy

Com isso, a produção deixa de depender de rebuild manual no host e passa a ter deploy rastreável por commit SHA.
