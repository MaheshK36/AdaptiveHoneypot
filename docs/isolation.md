# Environment isolation notes

This environment layer follows the requested defensive posture for a fake attacker surface.

- Postgres and the backend are attached only to `adaptive-honeypot-internal` and have no published host ports.
- Cowrie, fake HTTP, and fake DB are attached to `adaptive-honeypot-internal` (for backend/database-side communication) and `adaptive-honeypot-exposed` (for host-published test ports). The internal network uses Docker's isolated IPv4 gateway mode. The exposed bridge disables IP masquerading; host port publishing is bound to loopback.
- The attacker-facing ports are published only on `HONEYPOT_BIND_ADDRESS`, which defaults to `127.0.0.1`; the service ports are configured with `COWRIE_PORT`, `FAKE_HTTP_PORT`, and `FAKE_DB_PORT` in `.env`.
- The internal network is `internal: true` with isolated gateway mode, so backend/database-side traffic stays private and has no host bridge address. The exposed bridge disables IP masquerading, limiting ordinary Internet egress, but its Docker bridge gateway is present so published port forwarding works. This means Compose alone does not block containers from connecting to host services bound to Docker bridge addresses or to LAN routes configured on the host. To enforce that boundary, the Docker host must apply firewall rules that drop new traffic from the exposed bridge subnet to host INPUT and external FORWARD destinations while allowing established replies and traffic to the internal service subnet. Published ports are explicitly bound to `HONEYPOT_BIND_ADDRESS` (default `127.0.0.1`). Do not treat this Compose configuration as complete host/LAN egress isolation until that host firewall policy is active.
- Cowrie, fake HTTP, and fake DB services are constrained with dropped capabilities, no-new-privileges, memory limits, and CPU quotas.
- The root filesystem is mostly read-only at runtime; writable state is limited to the shared log volume and evidence output.
- No host bind mounts are used except the log and evidence volumes required for forensics.
- Processes run as a non-root user where the image supports it.
- Logs are written to a shared volume for review and eventual evidence copying.

This is intentionally scoped to a controlled testing environment and not a production deployment.
