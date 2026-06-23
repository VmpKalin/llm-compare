Output ONLY valid YAML, no commentary, no code fences. Represent this:
A service named "auth-api", version 2, listening on port 8080, with two environment variables: LOG_LEVEL set to "info" and TIMEOUT set to 30. It depends on two services: "postgres" and "redis".
Use keys: name, version, port, env (a map), depends_on (a list).
