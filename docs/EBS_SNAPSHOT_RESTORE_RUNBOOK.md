# EBS snapshot restore drill (Postgres)

**Do not run this against production.** This restores a *copy* of the
root disk onto a throwaway instance, then starts a disposable Postgres
container from `breachreplay_pgdata` only. Never attach the snapshot
volume as the live instance's root device. Never point
`docker-compose.prod.yml` at the restore.

A backup nobody has restored from is not a trustworthy backup. Run this
drill once the daily DLM policy has produced at least one real snapshot,
then quarterly.

## Backup source (created by hand, not IaC)

The daily snapshots come from **EC2 Data Lifecycle Manager**, created
**manually in the AWS Console** (not Terraform / CDK / a repo file).
To change schedule, retention, or tags, edit the policy in the same
place — do not look for it in this repo.

| | |
|---|---|
| Account | `469320018919` |
| Region | `us-east-1` (N. Virginia) |
| DLM policy | `policy-0a235e4e35f007629` |
| Type | EBS snapshot policy, **Enabled** |
| Target | instance tag `Name=breachreplay-prod` |
| Schedule | daily **09:00 UTC** (AWS starts within that hour) |
| Retention | 14 snapshots |
| Console | EC2 → Elastic Block Store → Lifecycle Manager |

## What we are restoring

| | |
|---|---|
| Prod instance | `i-0b33d84fe18ea2c77` (`Name=breachreplay-prod`) |
| Root volume | `vol-00bbd770f45cc773d` (`/dev/xvda`, AZ `us-east-1c`) |
| Postgres data | `/var/lib/docker/volumes/breachreplay_pgdata/_data` |
| Image | `pgvector/pgvector:pg16` |

The snapshot is the **whole 30G root disk** (OS, Docker, `.env.prod`,
issued-packs, uploads). Treat the throwaway box as secret-bearing.
We only *use* the Postgres directory.

## 0. Note live counts first (read-only)

On prod, from a laptop, not as part of this file's history:

```
docker exec breachreplay-db-1 psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT (SELECT count(*) FROM users) AS users,
          (SELECT count(*) FROM action_runs) AS action_runs,
          (SELECT count(*) FROM scenarios) AS scenarios;"
```

Write those three numbers down. The restore must match the snapshot's
point in time, not "whatever prod is now" if the snapshot is hours old.

## 1. Find the latest snapshot

Console (account `469320018919`, region **N. Virginia**):

1. EC2 → Elastic Block Store → **Snapshots**.
2. Filter **Volume ID** = `vol-00bbd770f45cc773d` (or tag
   `Name=breachreplay-prod` if Copy tags was enabled on the DLM policy).
3. Sort by **Started** descending. Take the newest `completed` snapshot.
   DLM-managed ones usually show `dlm:managed` / a lifecycle-policy tag.

CLI (needs `ec2:DescribeSnapshots` — `ClaudeCli-BreachReplay` does not
have this today):

```
aws ec2 describe-snapshots --region us-east-1 --owner-ids 469320018919 \
  --filters Name=volume-id,Values=vol-00bbd770f45cc773d \
  --query "reverse(sort_by(Snapshots,&StartTime))[0].[SnapshotId,StartTime,State,Encrypted]"
```

If the newest snapshot is still `pending`, wait. Do not drill a partial.

## 2. Create a new volume from it

Still `us-east-1`, **same AZ as prod: `us-east-1c`**.

1. Snapshots → select that snapshot → **Create volume from snapshot**.
2. Availability Zone: `us-east-1c`. Size 30 GiB (or the snapshot's size).
3. Do **not** delete or modify `vol-00bbd770f45cc773d`.
4. Name the new volume `breachreplay-restore-drill` so it is obvious.

Note the new volume id (`vol-…`). That is the only volume this drill
is allowed to delete at the end.

## 3. Attach it to a throwaway instance

1. Launch a disposable Amazon Linux 2023 **t3.micro** in `us-east-1c`
   (same VPC as prod is fine; public SSH or SSM either works).
   Do **not** use `i-0b33d84fe18ea2c77`.
2. EC2 → Volumes → `breachreplay-restore-drill` → **Attach volume**.
   Instance = the throwaway. Device `/dev/xvdf` (it will show up as
   `/dev/nvme1n1` on the guest).
3. SSH/SSM in. Install Docker only if you want the verify container
   on this box (`dnf install -y docker && systemctl start docker`).

```
lsblk
sudo mkdir -p /mnt/restore
sudo mount -o ro /dev/nvme1n1p1 /mnt/restore
# Confirm this is the snap, not the throwaway's own root:
ls /mnt/restore/var/lib/docker/volumes/breachreplay_pgdata/_data
```

`ro` is deliberate. We copy out; we do not write the snap volume.

## 4. Copy only Postgres data into a disposable container

```
sudo mkdir -p /tmp/pgdata-restore
sudo cp -a /mnt/restore/var/lib/docker/volumes/breachreplay_pgdata/_data/. \
  /tmp/pgdata-restore/
# Existing PGDATA already has users; read names from the snap, do not paste
# secrets into chat or this repo:
sudo grep -E '^(POSTGRES_USER|POSTGRES_DB)=' \
  /mnt/restore/home/ec2-user/breachreplay/.env.prod
sudo docker run -d --name pg-restore-drill \
  -e POSTGRES_HOST_AUTH_METHOD=reject \
  -v /tmp/pgdata-restore:/var/lib/postgresql/data \
  pgvector/pgvector:pg16
```

`POSTGRES_HOST_AUTH_METHOD=reject` is ignored once PGDATA exists; the
container just starts Postgres against the copied files. Wait until
`docker logs pg-restore-drill` shows ready.

## 5. Verify row counts

```
sudo docker exec -e PGUSER=<POSTGRES_USER from the snap> pg-restore-drill \
  psql -d <POSTGRES_DB from the snap> -c \
  "SELECT (SELECT count(*) FROM users) AS users,
          (SELECT count(*) FROM action_runs) AS action_runs,
          (SELECT count(*) FROM scenarios) AS scenarios;"
```

Pass if those three match the §0 notes for that snapshot's age.
Optionally spot-check one known `action_runs.id` you already have.

Fail if Postgres refuses to start, counts diverge from the snapshot
window, or `breachreplay_pgdata` is missing on the mount.

## 6. Tear down (every time)

Order matters. Stop before unmount; delete only the drill volume.

1. `sudo docker rm -f pg-restore-drill`
2. `sudo rm -rf /tmp/pgdata-restore`
3. `sudo umount /mnt/restore`
4. Console: **Detach** `breachreplay-restore-drill` from the throwaway.
5. **Terminate** the throwaway instance.
6. **Delete** volume `breachreplay-restore-drill` only.
7. Leave the snapshot and `vol-00bbd770f45cc773d` alone.

The snap contains `.env.prod`. Terminating the throwaway is part of
the drill, not optional cleanup.
