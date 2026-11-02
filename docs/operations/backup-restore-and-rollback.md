# Backup, restore and rollback runbook

**Status: documentation only. Nothing in this document has been run.** No backup, restore,
migration downgrade or rollback described here has been tested against a real deployment, a real
database or a cluster. It was written by reading the repository, so each step is marked with where
the repository supports it:

| Label | Meaning |
|---|---|
| **Repo-supported** | The command, name or behaviour appears in this repository (file given). |
| **Proposed** | A standard tool invocation that fits the repository's setup but is not written anywhere in it. Confirm before relying on it. |
| **Needs confirmation** | The repository does not say. The operator or project owner must decide or check. |

Nothing here is a service-level promise. See [section 7](#7-recovery-objectives-and-limitations).

Related documents: [production-readiness.md](production-readiness.md) (migration sequence,
limitations), [infra/kubernetes/README.md](../../infra/kubernetes/README.md) (deployment order),
[ADR 012](../architecture/decisions/012-deployment-architecture.md) (deployment architecture),
[ADR 013](../architecture/decisions/013-data-isolation.md) (ownership model).

## 1. Purpose and scope

This runbook covers what an operator would need to do to:

- take a backup of the PostgreSQL database and of the uploaded document files,
- check a backup and restore it into an isolated scratch database,
- decide between an Alembic downgrade and a restore for migrations 0005 to 0008,
- roll a release back using what the existing Kubernetes manifests support.

Out of scope, because the repository gives nothing to base them on: backing up Redis (ephemeral by
design, see below), the identity provider's own data (Keycloak or another OIDC provider; the repo
only has a development realm file in `infra/keycloak/`), Kubernetes cluster state, secrets storage,
and any registry or release automation.

What is stored where, from the repository:

| Data | Where | Evidence |
|---|---|---|
| Users, organizations, identities, conversations, messages, documents, chunks, embeddings, agent memories | PostgreSQL 16 with pgvector, database `aegis`. Tables: `organizations`, `users`, `user_identities`, `conversations`, `messages`, `documents`, `document_chunks`, `chunk_embeddings`, `agent_memories` | `backend/app/domain/models/`; `docker-compose.yml` (`POSTGRES_DB: aegis`); `infra/kubernetes/postgres-statefulset.yaml` |
| Original uploaded files | Local filesystem directory `DOCUMENT_STORAGE_DIR`: `/data/uploads` in Compose (bind mount `./data/uploads`) and in Kubernetes (PVC `aegisai-backend-uploads`, 5Gi, `ReadWriteOnce`). The code default for a local run is `<repo>/data/uploads` | `backend/app/config.py` (`document_storage_dir`); `docker-compose.yml`; `infra/kubernetes/backend-pvc.yaml`; `backend-configmap.yaml`; `backend-deployment.yaml` (`mountPath: /data/uploads`) |
| Rate-limit counters | Memory of each backend process; lost on restart | ADR 014 |
| Redis data | Not persisted by design | ADR 012 "Persistence"; `redis-deployment.yaml` |

## 2. Database backup

**Approach (repo-supported):** a custom-format dump, `pg_dump -Fc`. The existing-database migration
sequence says "Back up (`pg_dump -Fc`), and verify the dump"
([production-readiness.md](production-readiness.md), "Migration readiness"), and ADR 015 requires
"explicit approval and a backup" before applying migration 0008.

The database name and role are `aegis` and `aegis` in Compose and in the Kubernetes StatefulSet
(`POSTGRES_USER` and `POSTGRES_DB`). The password is a secret: do not type it into a command line
or a document. The commands below run `pg_dump` **inside the Postgres container**, which avoids
supplying a password on the command line in the Compose development setup (**Proposed**: the
repository does not state how the container authenticates local connections; if a password prompt
appears, use your secret store and stop rather than pasting it into shell history).

**Which shell to use (read first).** A custom-format dump is binary. In Windows PowerShell (at least
version 5.1) the redirection operators `>` and `<` treat command output and input as text and
re-encode it, which silently corrupts a binary dump; `<` input redirection is not supported there at
all. **Do not use `>` or `<` for dumps or restores in Windows PowerShell.** The commands in this
runbook therefore avoid redirection: they write the dump to a file *inside* the container with
`pg_dump -f` and move it with `docker compose cp` or `kubectl cp`, which copy the bytes unchanged.
That removes the redirection problem, but the commands have not been checked in every shell: the
quoting in the `sh -c '…'` and `psql -c '\l'` examples in particular may need adjusting for your shell
(Windows PowerShell 5.1, for example, can alter nested double quotes). If you would rather use
redirection, use bash (for example Git Bash or WSL), never PowerShell.

**Replace every `<…>` placeholder before running a command; in PowerShell an unreplaced `<` is
rejected as a reserved operator.** The placeholders include `<date>`, `<namespace>` and
`<scratch-database-url>` (which itself contains `<user>` and `<password>`). Do not paste any command in
this runbook unchanged into any shell.

Everything in this section is **Proposed** and has not been run. Tool prerequisites:
`docker compose cp` needs Docker Compose v2, and `kubectl cp` needs `tar` in the container image
(**Needs confirmation**).

**Compose (development) (Proposed):**

```bash
# from the repository root
# 1. dump inside the container (no shell redirection)
docker compose exec -T postgres pg_dump -U aegis -d aegis -Fc -f /tmp/aegis-<date>.dump
# 2. copy the file out unchanged
docker compose cp postgres:/tmp/aegis-<date>.dump ./aegis-<date>.dump
```

The service is named `postgres` in `docker-compose.yml`. The copy in `/tmp` lives in the container's
writable layer, not in the `pgdata` volume, and it is sensitive: once the host copy is verified, remove
it (`docker compose exec -T postgres rm /tmp/aegis-<date>.dump`) after you have compared the size of
the host copy with the original (and a checksum, if a tool is available in your environment) and run
the readability check below, which reads the copy in `/tmp`.

**Kubernetes with the bundled StatefulSet (dev/staging only) (Proposed):** the same steps in the
Postgres pod, which the manifests name `aegisai-postgres` (container `postgres`). Replace
`<namespace>` with the namespace you deployed into (the manifests set none):

```bash
kubectl exec -n <namespace> aegisai-postgres-0 -c postgres -- pg_dump -U aegis -d aegis -Fc -f /tmp/aegis-<date>.dump
kubectl cp -n <namespace> -c postgres aegisai-postgres-0:/tmp/aegis-<date>.dump ./aegis-<date>.dump
```

The pod name `aegisai-postgres-0` follows from the StatefulSet's name and `replicas: 1`. Whether `/tmp`
is writable in that container is **Needs confirmation** (the StatefulSet manifest sets no
`readOnlyRootFilesystem`). As in Compose, remove the temporary copy from the pod after verifying the
host copy. The manifests describe the bundled Postgres as dev/staging only; for a managed database
service use that provider's backup mechanism (**Needs confirmation**: the repository names none).

**Where to keep the dump, how often, for how long, and whether it is encrypted:** **Needs
confirmation.** The repository defines no backup schedule, retention, storage location or
encryption. A dump contains user e-mail addresses, conversation text and document content; treat
it as sensitive.

**Check that a dump is readable (Proposed).** Run `pg_restore --list` *inside the container* that
holds the dump: this uses the same PostgreSQL version that wrote it, does not need `pg_restore`
installed on your machine, and the `>` below is interpreted by the container's `sh`, not by your host
shell, so it is safe from PowerShell too. A dump that exists only on the host must first be copied in
(`docker compose cp ./aegis-<date>.dump postgres:/tmp/`).

```bash
docker compose exec -T postgres sh -c 'pg_restore --list /tmp/aegis-<date>.dump > /dev/null && echo "table of contents readable"'
# Kubernetes (dev/staging bundled Postgres)
kubectl exec -n <namespace> aegisai-postgres-0 -c postgres -- sh -c 'pg_restore --list /tmp/aegis-<date>.dump > /dev/null && echo "table of contents readable"'
```

This only proves the file's table of contents can be read. **It does not prove the dump can be
restored.** Only a restore into a scratch database (section 4) shows that.

**Before a migration:** take a fresh dump first. Migrations 0005 and 0006 have downgrades that
destroy data (section 5), so a verified dump is the only way back.

## 3. Uploaded-document backup

A database backup alone does not preserve the uploaded files. The database holds the extracted text,
chunks and embeddings; the original bytes live in the storage directory. The `documents.filename`
column is the internal storage key of the file in that directory.

- **Location (repo-supported):** `DOCUMENT_STORAGE_DIR`. In Kubernetes this is the PVC
  `aegisai-backend-uploads` (`ReadWriteOnce`, 5Gi), mounted at `/data/uploads` by
  `backend-deployment.yaml`. In Compose it is the host directory `./data/uploads`.
- **Backup method:** **Needs confirmation.** The repository names no backup utility, volume
  snapshot class or object store, and `backend-pvc.yaml` sets no `storageClassName`. Choose one that
  your environment supports (for example a copy of the directory, or a volume snapshot if your
  cluster supports them) and record it here once decided. I have not invented a command.
- **Consistency:** the database and the files are two stores that change independently. Back them up
  at close to the same time, ideally with uploads quiet, and keep each pair together. Document the
  pairing you use.
- **What happens if the files are missing after a restore (Needs confirmation):** the code reads the
  stored file when a document is processed (`DocumentService._extract_normalize_and_chunk` reads
  `document.filename` from storage). I found no endpoint that returns the original file, so search
  over already-processed documents should keep working from the database, but re-processing a
  document would fail. Verify this in a scratch environment before relying on it.
- **Redis:** nothing to back up; it is ephemeral by design.

## 4. Restore and verification

Restore into an **isolated scratch database**, never over the live database. Never restore into the
database a running application is using.

**Safeguards (read before running any restore command):**

- **Never pass the live database name (`aegis`) as the restore target** (`-d` / `--dbname`). The target
  must be the scratch database and nothing else.
- **Never add `--clean` (`-c`) or `--create` (`-C`) to `pg_restore`.** As documented for PostgreSQL's
  `pg_restore` (confirm against the documentation for your version), `--clean` drops existing database
  objects before recreating them and `--create` drops and recreates databases; pointed at the live
  database, either can destroy production data.
- **Verify the target before restoring:** list the databases, and confirm the scratch database exists
  and is empty (step 1 below). If you cannot tell which database a command will touch, stop.
- **Prefer a separate scratch server.** In the Compose example the scratch database lives inside the
  same Postgres server, container, disk and role as the live database, so a mistake, or a heavy
  restore, affects production. For a real recovery rehearsal use a separate disposable PostgreSQL
  server of the same major version (the image used is `pgvector/pgvector:pg16` in both Compose and the
  Kubernetes StatefulSet). The repository provides no such setup (**Needs confirmation**).
- **Kubernetes:** the repository provides no restore procedure, and none is given here. Do not restore
  inside the live `aegisai-postgres` pod. Copy the dump (`kubectl cp`, as in section 2) to a separate
  disposable PostgreSQL instance and apply the same safeguards there.

The commands below are the **Compose development** form. They are **Proposed** and untested, and they
avoid `<` redirection (see the shell note in section 2). Replace every `<…>` placeholder before running
a command; in PowerShell an unreplaced `<` is rejected as a reserved operator. Do not assume any
command is safe to paste unchanged into every shell.

**1. Create a scratch database and verify the target (Proposed).** The name is yours;
`aegis_restore_check` below is only an example. The restore target must have the `vector` extension
available (see the image above).

```bash
docker compose exec -T postgres createdb -U aegis aegis_restore_check
# confirm the scratch database exists, and that it is empty ("Did not find any relations")
docker compose exec -T postgres psql -U aegis -d postgres -c '\l'
docker compose exec -T postgres psql -U aegis -d aegis_restore_check -c '\dt'
```

**2. Restore (Proposed).** Copy the dump into the container, then restore it by file name:

```bash
docker compose cp ./aegis-<date>.dump postgres:/tmp/restore-<date>.dump
docker compose exec -T postgres pg_restore -U aegis -d aegis_restore_check --no-owner /tmp/restore-<date>.dump
```

Read the output. Errors from `pg_restore` mean the restore is not verified. Whether
`--no-owner` is right for your role setup, and whether the `vector` extension is created by the
dump or needs to exist first, are **Needs confirmation**.

**3. Check the schema revision (repo-supported tool, Proposed use).** `alembic current` reads
`alembic_version`. `alembic/env.py` takes the database from `DATABASE_URL`
(`backend/alembic/env.py`, `get_url()`), so point it at the scratch database, not the live one:

```bash
docker compose run --rm -e DATABASE_URL=<scratch-database-url> migrate alembic current
```

`<scratch-database-url>` is a template, not a value: it has the form
`postgresql+asyncpg://<user>:<password>@postgres:5432/aegis_restore_check`, with the user and password
taken from your own secret store (never pasted into notes or shell history). The command runs inside
the Compose network, as the `migrate` service does in `docker-compose.yml`, so the host is `postgres`
and the port is `5432` (the container port), **not** `localhost:5433` (the host-published port).
Without the `-e DATABASE_URL=...` override this command reads the live Compose database. The expected
result is the same revision as the source database (`0008` at the current head).

**Prerequisite for this command:** This command builds the image from your current checkout. Before
using it, confirm the working tree is at the same commit as the deployed release and that
`backend/alembic/versions/` contains the database's current revision. (The `migrate` service has
`build: .` and `pull_policy: build` in `docker-compose.yml`, so each `docker compose run … migrate`
rebuilds the backend image from the local sources.)

**4. Compare row counts (Proposed).** Run the same query against the source and the scratch
database and compare:

```sql
SELECT 'organizations', count(*) FROM organizations
UNION ALL SELECT 'users', count(*) FROM users
UNION ALL SELECT 'user_identities', count(*) FROM user_identities
UNION ALL SELECT 'conversations', count(*) FROM conversations
UNION ALL SELECT 'messages', count(*) FROM messages
UNION ALL SELECT 'documents', count(*) FROM documents
UNION ALL SELECT 'document_chunks', count(*) FROM document_chunks
UNION ALL SELECT 'chunk_embeddings', count(*) FROM chunk_embeddings
UNION ALL SELECT 'agent_memories', count(*) FROM agent_memories;
```

Matching counts show rows were restored, not that their content is correct. Also check that
`document_chunks` and `chunk_embeddings` for a sample document are present and that a similarity
search returns results (**Proposed**; the repository has no ready-made check).

**5. Application-level check (Proposed, optional).** `/health/ready` reports whether the backend can
reach its configured database and Redis (`backend/app/api/v1/health.py`). It says nothing about
data. It is only meaningful if you start a throwaway backend whose `DATABASE_URL` points at the
scratch database, which is not a documented setup. Sign-in additionally needs the identity provider
and a provisioned user (`scripts/provision_identity.py`).

**6. Clean up (Proposed).** Drop the scratch database when finished, and remove the temporary dump
copies you placed in the container's `/tmp`.

**What has actually been tested:** none of the above. The repository does contain an automated
round trip that upgrades and downgrades a **throwaway** database
(`backend/tests/integration/test_ownership_migration.py`, run in CI with `RUN_MIGRATION_ROUNDTRIP=1`),
but it exercises migrations, not backup or restore. The CI workflow has since run green on GitHub, but
whether this opt-in test ran or was skipped has not been confirmed from the available data.

## 5. Migration rollback decision table

Alembic downgrades run in reverse order, so going from 0008 to 0005 runs the 0008, 0007 and 0006
downgrades in turn. The effects below come from the downgrade code in `backend/alembic/versions/`.
**No downgrade has been run against a real database for this document.** Take a verified backup
before any downgrade.

The repository's own pattern for one-off Alembic commands is
`docker compose run --rm migrate alembic <command>` (README, "Upgrading a database that already
holds data", in the authentication section). The
Kubernetes migration Job (`infra/kubernetes/migration-job.yaml`) runs `alembic upgrade head` only;
**no downgrade Job exists in the repository**.

> **WARNING: this command changes the live database.** `docker compose run --rm migrate alembic ...`
> runs against whatever database the `migrate` service is configured for. In `docker-compose.yml` that
> is the Compose `postgres` database (`aegis`) that the running stack uses, **unless you explicitly
> override `DATABASE_URL`** with `-e DATABASE_URL=<scratch-database-url>` (see section 4). With no
> override, `alembic downgrade ...` rewrites the live schema and, depending on the revision, destroys
> data (table below).
>
> **Prerequisite for this command:** This command builds the image from your current checkout. Before
> using it, confirm the working tree is at the same commit as the deployed release and that
> `backend/alembic/versions/` contains the database's current revision.
>
> Before **any** downgrade:
>
> 1. obtain explicit written approval from the project owner for that environment and revision;
> 2. have a verified backup, restored once into a scratch database (sections 2 and 4);
> 3. **rehearse the exact downgrade on a scratch database first** (restore the dump there, run the
>    downgrade with the `DATABASE_URL` override, then check `alembic current` and the row counts);
> 4. only then, with approval, run it against the live database, and record the result.
>
> None of this has been tested.

| Revision | What `downgrade()` does | Data consequence | Safer option |
|---|---|---|---|
| **0008** (agent memories) | Drops the index and the `agent_memories` table | **Every stored memory is lost.** Conversations, messages and documents are untouched. Upgrading again creates an empty table | A downgrade is acceptable if the memories can be thrown away. To keep them, dump that table first (**Proposed**: `pg_dump -Fc -t agent_memories`). Restore the full backup if you also need other changes undone |
| **0007** (owner required) | Drops the `NOT NULL` requirement on `owner_user_id` and `organization_id` for `conversations` and `documents` | **No data change.** Only relaxes the constraint | A downgrade is safe for data. Note the application code at head assumes owners are set; do not run code that predates ownership against the relaxed schema |
| **0006** (ownership and visibility) | Drops `owner_user_id`, `organization_id` and `visibility` from `conversations` and `documents`, their composite foreign keys, check constraints and indexes, and the `users` unique constraint | **Ownership assignments and document sharing settings are discarded.** No conversation, message or document row is deleted. Upgrading again adds nullable owner columns with every document back to `private`; migration 0007 then refuses to run until `scripts/assign_legacy_data.py` assigns every row | **Restore from a backup** if the existing assignments and sharing matter. Re-running the assignment is a human decision (the script never guesses) |
| **0005** (identity tables) | Drops `user_identities`, `users` and `organizations` | **All accounts, organizations and identity links are destroyed.** No one can sign in afterwards because users are looked up in these tables. The migration's own docstring says this is acceptable "only before real use" | **Restore from a backup.** Do not downgrade a database that has real users |
| 0001 to 0004 | Drop the vector extension, messages and conversations, documents and chunks, and chunk embeddings | **Destroy core data.** Not covered by this runbook | Never downgrade below 0005 on a database with data; restore instead |

General rules:
- If an upgrade **fails partway**: `alembic/env.py` runs the whole Alembic invocation inside one
  transaction (`context.begin_transaction()`, with no per-migration transactions configured), and
  PostgreSQL DDL is transactional, so a failed run should roll back **everything that invocation
  did** and leave the revision it started from. Note the difference from the 0007 docstring: it says a
  refusal changes nothing because "Alembic runs this migration in one transaction", which describes
  only 0007's own changes. The transaction in `env.py` is wider, so if one invocation upgrades several
  revisions at once (for example from 0005 straight to head) and 0007 refuses, the earlier revisions of
  that same invocation (0006) should be rolled back too. The documented upgrade sequence runs
  `alembic upgrade 0006` separately because the owner assignment must happen between 0006 and 0007;
  the single-invocation behaviour above is a further reason to keep the steps apart. This reading of
  the code has **not been tested**. Check with `alembic current` before doing anything else.
- Prefer a **restore** over a downgrade whenever a downgrade would discard identity, ownership or
  sharing data (0005, 0006), or when the database is in an unknown state.
- After any downgrade or restore, check `alembic current` and the row counts (section 4).
- 0007 on an existing database refuses until unowned rows are assigned. The documented upgrade
  sequence is in [production-readiness.md](production-readiness.md), "Migration readiness".

## 6. Release rollback

**What the manifests support:**
- The backend and frontend are Kubernetes Deployments with `strategy: RollingUpdate`
  (`backend-deployment.yaml`; the backend runs `replicas: 1` on purpose because uploaded files live
  on a `ReadWriteOnce` volume). Images are referenced as `aegisai-backend:REPLACE_WITH_TAG` and
  `aegisai-frontend:REPLACE_WITH_TAG`: **the operator must fill in a real tag**.
- Migrations run as a separate, explicit step: apply `migration-job.yaml`, wait for completion,
  delete the Job, then roll out the Deployments (`infra/kubernetes/README.md`, "Deployment order").
- ADR 012 "Image tagging" recommends tagging each CI build with the Git SHA and `vX.Y.Z` for releases.
  This is "documented rather than automated".

**Rolling back application code (Proposed):** redeploy the previous image tag by editing the `image:`
in the Deployment manifest and applying it again. The standard `kubectl rollout undo` also exists,
but the repository does not mention it, and it only helps if a previous revision of the Deployment is
still recorded in the cluster (**Needs confirmation**).

**Limitations, from the repository:**
- **No image is published.** CI builds the images and pushes none (`docker-build` in `ci.yml`), no
  registry is configured, and there is no release pipeline. A previous tag exists only if the
  operator pushed it somewhere. This is a prerequisite that is not currently met.
- **Migrations are forward-only in the Job.** Rolling code back does not roll the schema back.
  - Additive steps (0005, 0008) most likely tolerate older code ignoring the new tables
    (**Needs confirmation**).
  - After **0007** the owner columns are `NOT NULL`. Code that predates ownership creates rows
    without owners, which the constraint rejects. Do not run pre-ownership code on a database at 0007
    or later; roll back with a restore, not a code change alone.
  - After **0006**, queries in current code depend on the owner columns.
- **A rollout or rollback may stall (untested).** `backend-deployment.yaml` uses `RollingUpdate` with
  `maxSurge: 1` and `maxUnavailable: 0`, and the uploads PVC is `ReadWriteOnce`. The new pod is
  started while the old pod is still running and holding the volume. If the scheduler places the new
  pod on a different node, it may be unable to attach the `ReadWriteOnce` volume, and the rollout (or
  rollback) can stall. With `maxUnavailable: 0` the old pod keeps serving in that case, so this is
  expected to be a stuck rollout rather than an outage. This is reasoned from the manifest and has
  **not been tested** on any cluster; whether it happens depends on the cluster's storage and
  scheduling (**Needs confirmation**). The repository documents no workaround.
- **Rollback of data written by newer code** (for example agent memories created after 0008) is not
  addressed by redeploying an older image.

**What has actually been tested:** nothing. The manifests have only been structurally validated
(`infra/kubernetes/validate_manifests.py`, CI job `k8s-manifests`) and, per the Kubernetes README, no
manifest was ever applied to a cluster. No release automation exists.

## 7. Recovery objectives and limitations

- **RPO and RTO are not defined anywhere in the repository.** They must be decided by the project
  owner. This document sets none and implies none.
- **Not defined, and therefore not described here:** backup schedule, retention period, backup
  encryption and key management, off-site copies, who may restore, escalation contacts, and incident
  response. Do not treat any command above as a schedule or a guarantee.
- **Single points of failure documented in the repository:** single-replica backend and (in the
  bundled manifests) single-pod Postgres and Redis with local `ReadWriteOnce` volumes; files and
  database are separate stores; per-process rate limits and in-memory counters are lost on restart.
- **Untested:** every procedure in this document. The first real use should be a rehearsal in a
  non-production environment, with the result written back into this file.
- **Audit logs** are ordinary log lines (ADR 014); backing them up depends on your log shipping,
  which the repository does not define.

## 8. Preflight checklist

Before **any** real backup, restore, downgrade or rollback, obtain and record:

- [ ] Explicit written approval from the project owner, naming the environment and the action.
- [ ] The target environment is confirmed (development, staging or production) and the connection
      target is verified **not** to be the live database when a scratch database is intended.
- [ ] A recent database dump exists, its table of contents has been checked with `pg_restore --list`,
      and it has been restored once into a scratch database with matching `alembic current` and row
      counts.
- [ ] A matching copy of the uploaded files exists for the same point in time (method chosen and
      recorded; none is defined in the repository).
- [ ] The current revision is recorded (`alembic current`) together with the running image tag.
- [ ] Credentials come from the operator's secret store; none are typed into commands, files or
      tickets.
- [ ] The backup location, its access control and its encryption have been decided and recorded
      (the repository defines none).
- [ ] For a downgrade: the data-loss column in section 5 has been read for **every** revision that
      will be passed through, and a restore is not the safer choice.
- [ ] For a code rollback: the previous image tag exists in a registry the cluster can pull from, and
      the schema revision is compatible with that code (section 6).
- [ ] Users have been told about any downtime or data loss, and a maintenance window is agreed
      (**Needs confirmation**: the repository defines no communication process).
- [ ] Someone other than the operator knows what is being done and how to stop (the repository
      defines no escalation contacts).
- [ ] The outcome (what ran, what was verified, what failed) is written down and any correction to
      this runbook is made afterwards.
