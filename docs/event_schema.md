# Event schema

Events use the shared JSON log format below. The control API also inserts its events into the Postgres `events` table. HTTP and fake DB events currently go to the shared JSONL volume only; Postgres insertion for those services is not implemented yet. Cowrie's native output is not normalized to this schema yet.

Schema:

{
  "ts": "ISO-8601 timestamp",
  "session_id": "numeric session identifier, or null when the request is not associated with a generated session",
  "src_ip": "source IP seen by the service",
  "service": "cowrie|http|db|control_api",
  "event_type": "CONNECT|LOGIN_ATTEMPT|LOGIN_SUCCESS|COMMAND|FILE_ACCESS|DB_QUERY|HTTP_REQUEST|LOGOUT",
  "command": "raw command or request string",
  "detail": "free-form JSON object with service-specific context"
}

The HTTP service records `HTTP_REQUEST` events and records form submissions as `LOGIN_ATTEMPT` without storing submitted passwords. The MySQL service records `LOGIN_ATTEMPT`, `LOGIN_SUCCESS`, `CONNECT`, `DB_QUERY`, and `LOGOUT`; session IDs are resolved through the generated DB account. The control API records trail and lifecycle events and persists them to both JSONL and Postgres.
