from arq.connections import RedisSettings

from src.config import settings


def get_redis_settings() -> RedisSettings:
    """Parse l'URL Redis pour ARQ."""
    # redis://localhost:6379/0 → host, port, database
    url = settings.redis_url.replace("redis://", "")
    parts = url.split("/")
    host_port = parts[0]
    database = int(parts[1]) if len(parts) > 1 else 0
    host, port_str = host_port.split(":") if ":" in host_port else (host_port, "6379")
    return RedisSettings(host=host, port=int(port_str), database=database)
