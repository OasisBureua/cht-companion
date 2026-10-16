# Non-secret infra for GitHub Actions deploy-prod.yml (committed).

environment = "prod"
aws_region  = "us-east-1"

platform_vpc_name                    = "cht-platform-vpc"
ecs_cluster_name                     = "cht-platform-cluster"
platform_backend_security_group_name = "cht-platform-backend-sg"
service_connect_namespace_name       = "cht.local"

# Platform Redis for /chat and /generate rate limits (db 1; the platform backend uses db 0).
platform_redis_url                 = "redis://cht-platform-redis.nwaasy.ng.0001.use1.cache.amazonaws.com:6379/1"
platform_redis_security_group_name = "cht-platform-redis-sg"

# Inbound auth: cht-platform-users pool, Cognito M2M tokens only.
cognito_user_pool_id = "us-east-1_whXKKxAdX"

companion_ecr_repository_name = "cht-companion"
kb_ecr_repository_name        = "cht-companion-kb"

# deploy-prod.yml overrides these with -var on every run (the tag it just built,
# or the image prod already runs). Only used for manual applies.
companion_image  = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-companion:prod-latest"
kb_image         = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-companion-kb:prod-latest"
kb_enqueue_image = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-companion-kb:prod-latest-enqueue"

# Aurora PostgreSQL Global: one writer here, read-only secondary in us-east-2
# (environments/us-east-2). The secondary is the only thing companion runs in
# us-east-2; images and the database secret are replicated there.
db_engine             = "aurora"
aurora_engine_version = "15.17"
aurora_instance_class = "db.serverless"
# Serverless v2 range, also the us-east-2 secondary's (environments/us-east-2 defaults).
aurora_serverless_min_capacity = 1
aurora_serverless_max_capacity = 8
aurora_instance_count          = 1
db_backup_retention_period     = 14

secrets_replica_regions = ["us-east-2"]

youtube_oauth_secret_name = "cht-companion-youtube-oauth"

companion_task_cpu                 = 512
companion_task_memory              = 1024
companion_desired_count            = 2
companion_min_capacity             = 2
companion_max_capacity             = 4
companion_enable_scheduled_scaling = false

kb_schedule_expression  = "rate(1 day)"
kb_platform_catalog_url = "https://app.communityhealth.media/api/catalog"
