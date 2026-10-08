# Adaptive Honeypot Environment

This repository currently contains a partial implementation of the fake environment layer. AI/ML, the deception decision engine, MITRE mapping, awareness scoring, and the React dashboard are out of scope.

## Run

```bash
test -f .env || cp .env.example .env
docker compose up --build -d
docker compose ps
```

The host-facing test services bind to loopback using the ports in `.env` (`COWRIE_PORT`, `FAKE_HTTP_PORT`, and `FAKE_DB_PORT`). Defaults are SSH on `127.0.0.1:2222`, HTTP on `127.0.0.1:8080`, and the fake DB responder on `127.0.0.1:3306`.

After adding a trail through the control API, its generated files are served under `/sessions/{session_id}/` on fake HTTP. For example, the generated app config is available at `/sessions/123/opt/app/.env` for session `123`.

```bash
curl -i http://127.0.0.1:8080/
ssh -o StrictHostKeyChecking=no -p 2222 root@127.0.0.1
```

The fake DB speaks the MySQL wire protocol and authenticates credentials generated for a session. Run the protocol integration test to create a `db_trail`, authenticate with its generated credentials, and query the synthetic `users` and `orders` tables:

```bash
docker compose exec -T backend pytest -q tests/test_fake_db.py
```

The backend API listens only on the internal Docker network; its port is not published to the host. Use the container-based test command below to validate API behavior.

## Test

```bash
docker compose exec -T backend pytest -q
```

Recent verification: 9 tests passed. The fake HTTP endpoint returned HTTP 200, the SSH client reached Cowrie's authentication prompt, and a PyMySQL client authenticated with a generated session credential and queried the generated `users` and `orders` tables. A `db_trail` added through the control API was served successfully from the generated session directory.

## Completion Status

- Phase 0: complete.
- Phase 1: partial. Cowrie, FastAPI fake HTTP, and a real MySQL wire-protocol responder run in separate containers. The generator creates seeded users, credentials, users/orders rows, and trail files; generated DB credentials authenticate and the fake HTTP service can serve the session files. Cowrie still uses its stock filesystem, so generated users/files/trails are not visible in its SSH shell. Host/LAN egress isolation also still requires host firewall enforcement.
- Limited Phase 2: partial. The backend control API, fake HTTP, and fake DB write structured events to the shared JSONL volume. Honeypot events are not yet consistently inserted into Postgres, and Cowrie output is not yet normalized to the required event schema.
- Limited Phase 6: partial. Control routes exist, but terminate does not destroy a service container or close its attacker connection; reset regenerates files rather than replacing a container.
- Phase 8: not complete. There is no `attacker_sim.py` yet.

## Isolation Limitations

Postgres and the backend have no published host ports and use the internal network. Attacker-facing ports bind to loopback, and masquerading is disabled on the exposed bridge. However, this Compose configuration alone does not block all access from honeypot containers to host services or LAN routes. Apply and verify host firewall rules before using this stack with untrusted traffic. See [docs/isolation.md](docs/isolation.md).

Stop the stack with `docker compose down`. Named database and log volumes are retained unless removed separately.