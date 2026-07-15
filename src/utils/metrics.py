from prometheus_client import Counter, Gauge, Histogram

# Compteur de jobs par type et statut
jobs_total = Counter(
    "skilluv_ai_jobs_total",
    "Nombre total de jobs traités",
    ["job_type", "status"],
)

# Durée de traitement des jobs
jobs_duration_seconds = Histogram(
    "skilluv_ai_jobs_duration_seconds",
    "Durée de traitement des jobs en secondes",
    ["job_type"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0],
)

# Jobs en cours
jobs_in_progress = Gauge(
    "skilluv_ai_jobs_in_progress",
    "Nombre de jobs en cours de traitement",
    ["job_type"],
)

# Erreurs externes
external_errors_total = Counter(
    "skilluv_ai_external_errors_total",
    "Erreurs d'appels à des services externes",
    ["service"],  # "claude_api", "minio", "redis"
)

# gRPC — latence par méthode (M5.1)
grpc_request_duration_seconds = Histogram(
    "skilluv_ai_grpc_request_duration_seconds",
    "Latence des appels gRPC en secondes",
    ["method"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# gRPC — compteur total, ventilé par status
grpc_requests_total = Counter(
    "skilluv_ai_grpc_requests_total",
    "Nombre total d'appels gRPC",
    ["method", "status"],  # status: 'ok' | 'error'
)
