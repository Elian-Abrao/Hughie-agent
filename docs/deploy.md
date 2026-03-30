# Deploy

Este documento descreve o fluxo atual de deploy do Hughie em produção.

## Visão geral

A produção roda no `home-server`, no diretório:

```bash
/home/elian/services/hughie
```

O deploy usa:

- `docker-compose.prod.yml`
- imagens publicadas no GHCR
- GitHub Actions para CI/CD
- runner self-hosted no próprio `home-server` para executar o deploy

## Estado atual

Hoje o fluxo está assim:

1. `CI` roda no GitHub-hosted runner
2. `CD` publica as imagens `broker`, `hughie` e `frontend` no GHCR
3. o job de deploy roda no runner local `home-server`
4. o servidor faz `git pull`, `docker compose pull` e `docker compose up -d`

## Fluxo normal de release

Fluxo recomendado:

1. criar uma branch
2. fazer as alterações
3. commitar
4. dar `push`
5. abrir PR
6. esperar o `CI` ficar verde
7. fazer merge na `main`
8. esperar o `CD` terminar

Se estiver trabalhando sozinho e quiser um fluxo direto:

1. fazer a alteração local
2. commitar na `main`
3. dar `push origin main`
4. acompanhar o `CI/CD`

## O que acontece depois do merge na `main`

O workflow de CD:

1. publica as imagens no GHCR com tag do commit SHA
2. agenda o job `Deploy to Production`
3. executa o deploy no `home-server`

O deploy roda este fluxo no servidor:

```bash
cd /home/elian/services/hughie
git pull --ff-only origin main
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

## Como acompanhar um deploy

Pelo GitHub:

- abra a aba `Actions`
- acompanhe os workflows `CI` e `CD`

Pelo terminal:

```bash
gh run list --repo Elian-Abrao/Hughie-agent
gh run watch <run-id> --repo Elian-Abrao/Hughie-agent
```

## Como validar a produção

No servidor:

```bash
ssh home-server
cd /home/elian/services/hughie
docker compose ps
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:47831/v1/health
curl -I http://127.0.0.1:3000/
```

Resultado esperado:

- backend responde `200` em `/health`
- broker responde `200` em `/v1/health`
- frontend responde `200` na porta `3000`

## Como verificar qual versão está em produção

```bash
ssh home-server
cd /home/elian/services/hughie
git rev-parse HEAD
docker compose ps --format json
```

Procure:

- o commit atual do checkout
- as imagens `ghcr.io/elian-abrao/hughie-agent/...:<sha>`

## Rollback

O jeito mais seguro hoje é voltar a `main` para um commit anterior e deixar o CD redeployar.

Exemplo:

```bash
git checkout main
git log --oneline
git revert <commit>
git push origin main
```

Se precisar de rollback manual emergencial no servidor:

```bash
ssh home-server
cd /home/elian/services/hughie
git log --oneline
git checkout <commit-antigo>
docker compose -f docker-compose.prod.yml up -d --remove-orphans
```

Observação:

- esse caminho manual é útil em emergência
- depois, alinhe novamente o branch `main` no GitHub

## Runner de deploy

O runner self-hosted está instalado em:

```bash
/home/elian/actions-runner
```

Ele é gerenciado por `systemd --user`:

```bash
systemctl --user status github-actions-runner.service
```

Arquivo da unit:

```bash
~/.config/systemd/user/github-actions-runner.service
```

Comandos úteis:

```bash
systemctl --user status github-actions-runner.service
systemctl --user restart github-actions-runner.service
journalctl --user -u github-actions-runner.service -n 100 --no-pager
```

O `linger` do usuário `elian` precisa permanecer habilitado para o runner subir após reboot:

```bash
loginctl show-user elian -p Linger
```

Resultado esperado:

```bash
Linger=yes
```

## Arquivos importantes

- `/.github/workflows/ci.yml`
- `/.github/workflows/cd.yml`
- `/docker-compose.prod.yml`
- `/scripts/deploy-prod.sh`
- `/scripts/github-actions-runner.service`
- `/.env.production.example`

## Problemas comuns

`CD` falha no publish:

- confira logs em `Actions`
- valide se o submódulo `providers/llm-broker` está acessível no workflow

`CD` falha no deploy:

- confira o job `Deploy to Production`
- valide o runner `home-server`
- cheque `systemctl --user status github-actions-runner.service`

Produção subiu mas app não responde:

- cheque `docker compose ps`
- cheque os endpoints de saúde
- veja logs dos containers:

```bash
docker compose logs --tail=100 hughie
docker compose logs --tail=100 broker
docker compose logs --tail=100 frontend
```
