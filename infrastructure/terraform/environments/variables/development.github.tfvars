# Non-secret infra for GitHub Actions deploy-dev.yml (committed).

environment = "development"
aws_region  = "us-east-1"

# Platform stack (cht-platform-tool dev) — pin IDs so subnet lookup does not depend on Tier tags
platform_vpc_id = "vpc-095c20b7e874013f2"
platform_private_subnet_ids = [
  "subnet-02ec72146e3abf115",
  "subnet-0a9d1329fbf64dbfb",
]

platform_vpc_name                    = "cht-dev-vpc"
ecs_cluster_name                     = "cht-dev-cluster"
platform_backend_security_group_name = "cht-dev-backend-sg"
platform_backend_security_group_ids  = ["sg-0363efdc457aa7341"]
service_connect_namespace_name       = "cht-dev.local"

companion_ecr_repository_name = "cht-dev-companion"
kb_ecr_repository_name        = "cht-dev-companion-kb"

companion_image = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-dev-companion:dev-latest"
kb_image        = "233636046512.dkr.ecr.us-east-1.amazonaws.com/cht-dev-companion-kb:dev-latest"

db_instance_class          = "db.t4g.small"
db_engine_version          = "16.9"
db_allocated_storage       = 20
db_multi_az                = false
db_backup_retention_period = 1

companion_task_cpu                 = 512
companion_task_memory              = 1024
companion_desired_count            = 1
companion_min_capacity             = 1
companion_max_capacity             = 2
companion_enable_scheduled_scaling = true

kb_schedule_expression = "rate(1 day)"
