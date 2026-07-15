# skilluv-ai — Déploiement Hetzner (MVP)

> **Cible** : single-host Hetzner Cloud CX22 (2 vCPU, 4 Go RAM) ou CX32 (4/8) pour marge sur les workers média.
> **Stack** : Docker Compose, Caddy pour TLS, sops+age pour secrets, Prometheus/Grafana embarqués.
> **Rollback** : image tag pinned + volumes préservés (voir §Rollback).

Pré-requis côté opérateur :
- Compte Hetzner Cloud + `hcloud` CLI (ou console web)
- Domaine + capacité de créer des records DNS
- `age` + `sops` installés localement (secrets edition)
- Accès SSH avec clé publique

---

## 1. Provision serveur

```bash
hcloud server create \
  --name skilluv-ai-prod-1 \
  --type cx22 \
  --image debian-12 \
  --ssh-key <your-key-name> \
  --location nbg1
```

Une fois joignable :

```bash
ssh root@<ip>
# 1. Mise à jour de base
apt-get update && apt-get upgrade -y
# 2. Docker + compose plugin
curl -fsSL https://get.docker.com | sh
apt-get install -y docker-compose-plugin ufw
# 3. Firewall
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
# 4. User dédié (pas de root pour l'app)
useradd -m -s /bin/bash skilluv && usermod -aG docker skilluv
```

---

## 2. DNS

Créer 3 records A pointant sur l'IP du serveur :

| Sous-domaine | Usage |
|---|---|
| `ai.skilluv.example.com` | gRPC (via Caddy TLS) |
| `metrics.skilluv.example.com` | Endpoint /metrics + admin (auth basique) |
| `grafana.skilluv.example.com` | Dashboard |

---

## 3. TLS (Caddy)

Installer Caddy sur l'hôte :

```bash
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy
```

`/etc/caddy/Caddyfile` :

```caddy
ai.skilluv.example.com {
  reverse_proxy h2c://127.0.0.1:50051
}

grafana.skilluv.example.com {
  reverse_proxy 127.0.0.1:3000
}

metrics.skilluv.example.com {
  basicauth {
    admin <bcrypt-hash>
  }
  reverse_proxy 127.0.0.1:8000
}
```

`systemctl reload caddy`. Certificats Let's Encrypt provisionnés automatiquement.

---

## 4. Secrets (sops + age)

Local, une fois :

```bash
# Générer une clé age (à backup !)
age-keygen -o ~/.config/sops/age/keys.txt
# La clé publique va dans .sops.yaml du repo
```

`.sops.yaml` à la racine du repo :

```yaml
creation_rules:
  - path_regex: \.env\.production$
    age: age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Édition sûre :

```bash
cp .env.production.template .env.production
# Remplir les CHANGE_ME
sops -e -i .env.production   # chiffre in-place
git add .env.production      # OK à committer (chiffré)
```

Sur le serveur :

```bash
mkdir -p /etc/skilluv && chown skilluv:skilluv /etc/skilluv
# Déployer la clé age privée dans /etc/skilluv/age.key (mode 400)
# Déchiffrer au boot :
sops -d /home/skilluv/skilluv-ia/.env.production > /etc/skilluv/.env
chmod 600 /etc/skilluv/.env
```

---

## 5. Premier déploiement

Sur l'hôte, en tant que `skilluv` :

```bash
git clone https://github.com/jeremie0342/skilluv-ia.git ~/skilluv-ia
cd ~/skilluv-ia
git checkout mvp-1

# Déchiffrer secrets -> /etc/skilluv/.env (root pour ça, puis chown)
sudo sops -d .env.production > /tmp/env && \
  sudo install -o skilluv -g skilluv -m 600 /tmp/env /etc/skilluv/.env && \
  rm /tmp/env

# Pull image + start
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Vérifications :

```bash
# Health check gRPC (via grpc_health_probe dans le conteneur)
docker compose -f docker-compose.prod.yml exec skilluv-ai \
  grpc_health_probe -addr=127.0.0.1:50051

# Metrics
curl -s http://127.0.0.1:8000/metrics | grep skilluv_ai_grpc_

# Prometheus targets
curl -s http://127.0.0.1:9090/api/v1/targets | grep skilluv-ai
```

---

## 6. Smoke test post-deploy

Depuis un client ayant grpcurl et un accès réseau :

```bash
# Le healthcheck standard
grpcurl -d '{}' ai.skilluv.example.com:443 grpc.health.v1.Health/Check
# Expected: {"status": "SERVING"}

# Un vrai appel (nécessite le proto en local ou reflection activée)
grpcurl -import-path proto -proto skilluv_ai.proto \
  -d '{"submission_id":"smoke","code":"print(1)","language":"python","difficulty":1}' \
  ai.skilluv.example.com:443 \
  skilluv.ai.v2.CodeReviewService/ReviewCode
```

---

## 7. Backups

Cron sur l'hôte (`/etc/cron.daily/skilluv-backup`) :

```bash
#!/bin/bash
set -euo pipefail
DATE=$(date +%Y-%m-%d)
BACKUP_DIR=/var/backups/skilluv/$DATE
mkdir -p "$BACKUP_DIR"

# Redis snapshot
docker exec skilluv-ia-redis-1 redis-cli BGSAVE
sleep 5
docker cp skilluv-ia-redis-1:/data/dump.rdb "$BACKUP_DIR/redis.rdb"

# MinIO -> tar
docker run --rm -v skilluv-ia_minio_data:/data:ro -v "$BACKUP_DIR":/backup \
  alpine tar czf /backup/minio.tar.gz -C /data .

# Rotation : garde 14 jours
find /var/backups/skilluv -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
```

Restic ou rclone recommandé pour off-site (S3 secondaire, B2, etc.).

---

## 8. Rollback

**Scénario 1 — Bug de code repéré après déploiement de `mvp-2`** :

```bash
SKILLUV_AI_IMAGE_TAG=mvp-1 \
  docker compose -f docker-compose.prod.yml up -d skilluv-ai
```

Les volumes (Redis, MinIO) sont préservés → pas de perte de state. Downtime typique : < 30s (temps du restart + health check start_period 60s).

**Scénario 2 — Data corruption Redis** :

```bash
docker compose -f docker-compose.prod.yml stop redis
docker run --rm -v skilluv-ia_redis_data:/data alpine \
  sh -c "rm /data/dump.rdb && cp /backup/redis.rdb /data/dump.rdb"
docker compose -f docker-compose.prod.yml start redis
```

**Scénario 3 — Rollback proto (breaking change v2)** :

Ne devrait jamais arriver — les règles §0.5 de MVP.md interdisent le renumbering. Si urgence : redéployer un tag antérieur et le backend Rust bascule sur v1 (`challenge.proto`) qui reste enregistré côté serveur.

---

## 9. Monitoring alerts → destination

Prometheus alerts (voir `infra/prometheus/alerts.yml`) doivent atterrir quelque part :
- **MVP** : Alertmanager → email (`SMTP_*` env vars, sinon désactivé)
- **Post-MVP** : Slack via webhook

Config minimale `alertmanager.yml` (à ajouter au compose si besoin) :

```yaml
route:
  receiver: 'email'
receivers:
  - name: 'email'
    email_configs:
      - to: 'ops@skilluv.example.com'
        from: 'alerts@skilluv.example.com'
        smarthost: 'smtp.example.com:587'
        auth_username: '...'
        auth_password: '...'
```

---

## 10. Checklist go-live

- [ ] Serveur provisionné, firewall UP
- [ ] DNS résout sur les 3 sous-domaines
- [ ] Caddy sert du TLS valide (Let's Encrypt OK)
- [ ] `.env.production` chiffré, clé age backupée hors serveur
- [ ] Image `mvp-1` pull depuis GHCR OK
- [ ] `docker compose up -d` sans erreur
- [ ] `grpc_health_probe` répond SERVING
- [ ] `/metrics` scrape par Prometheus, dashboards Grafana peuplés
- [ ] Smoke test grpcurl OK sur ReviewCode + CheckPlagiarism
- [ ] Cron de backup installé et testé (rollback dry-run)
- [ ] Alertes email/slack reçues sur un test synthétique
