# Non-secret infra for GitHub Actions deploy-prod.yml (committed).

environment = "prod"
aws_region  = "us-east-1"

platform_vpc_name                    = "cht-platform-vpc"
ecs_cluster_name                     = "cht-platform-cluster"
platform_backend_security_group_name = "cht-platform-backend-sg"
service_connect_namespace_name       = "cht.local"

# Inbound auth: cht-platform-users pool, Cognito M2M tokens only.
cognito_user_pool_id = "us-east-1_whXKKxAdX"
companion_auth_mode  = "m2m"

companion_ecr_repository_name = "cht-companion"
kb_ecr_repository_name        = "cht-companion-kb"

companion_image = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-companion:1.0.0"
kb_image         = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-companion-kb:1.0.0"
kb_enqueue_image = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-companion-kb:1.0.0-enqueue"

db_instance_class          = "db.t4g.small"
db_engine_version          = "16.9"
db_allocated_storage       = 50
db_multi_az                = true
db_backup_retention_period = 14

companion_task_cpu                 = 512
companion_task_memory              = 1024
companion_desired_count            = 2
companion_min_capacity             = 2
companion_max_capacity             = 4
companion_enable_scheduled_scaling = false

kb_schedule_expression = "rate(1 day)"
kb_platform_catalog_url = "https://app.communityhealth.media/api/catalog"
