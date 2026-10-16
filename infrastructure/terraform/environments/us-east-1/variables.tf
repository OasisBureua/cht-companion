variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name: development or prod"
  type        = string

  validation {
    condition     = contains(["development", "prod"], var.environment)
    error_message = "environment must be development or prod."
  }
}

# Shared platform networking (from cht-platform-tool stack)
variable "platform_vpc_id" {
  description = "Existing platform VPC ID (optional if platform_vpc_name lookup is used)"
  type        = string
  default     = ""
}

variable "platform_vpc_name" {
  description = "Name tag of the platform VPC when platform_vpc_id is empty"
  type        = string
  default     = "cht-dev-vpc"
}

variable "platform_private_subnet_ids" {
  description = "Private subnet IDs in the platform VPC"
  type        = list(string)
  default     = []
}

variable "ecs_cluster_name" {
  description = "Existing ECS cluster name (cht-dev-cluster or cht-platform-cluster)"
  type        = string
}

variable "ecs_cluster_arn" {
  description = "Optional ECS cluster ARN override"
  type        = string
  default     = ""
}

variable "platform_redis_url" {
  description = "Platform ElastiCache Redis URL for companion rate limits. Use db 1: the platform backend caches in db 0"
  type        = string
  default     = ""
}

variable "platform_redis_security_group_name" {
  description = "Platform Redis security group; companion is allowed in on 6379 when set"
  type        = string
  default     = ""
}

variable "platform_backend_security_group_name" {
  description = "Platform NestJS backend security group name when IDs are not provided"
  type        = string
  default     = "cht-dev-backend-sg"
}

variable "platform_backend_security_group_ids" {
  description = "Platform NestJS backend security group IDs allowed to reach companion"
  type        = list(string)
  default     = []
}

# Service Connect
variable "service_connect_namespace_name" {
  description = "HTTP namespace for ECS Service Connect"
  type        = string
}

variable "service_connect_dns_name" {
  description = "DNS name platform BFF uses to reach companion (e.g. cht-companion)"
  type        = string
  default     = "cht-companion"
}

# Inbound auth (Cognito M2M). Callers' app clients live in their own repos.
variable "cognito_user_pool_id" {
  description = "Shared CHT user pool that hosts the companion resource server (empty = no resource server)"
  type        = string
  default     = ""
}

# Container images (overridden per deploy in CI)
variable "companion_image" {
  type = string
}

variable "kb_image" {
  description = "Embed worker image"
  type        = string
}

variable "kb_enqueue_image" {
  description = "Catalog enqueue image"
  type        = string
}

variable "companion_ecr_repository_name" {
  type = string
}

variable "kb_ecr_repository_name" {
  type = string
}

# Database
variable "db_engine" {
  description = "rds (single RDS PostgreSQL instance, dev) or aurora (Aurora PostgreSQL Global writer, prod)"
  type        = string
  default     = "rds"

  validation {
    condition     = contains(["rds", "aurora"], var.db_engine)
    error_message = "db_engine must be rds or aurora."
  }
}

variable "aurora_engine_version" {
  type    = string
  default = "15.17"
}

variable "aurora_instance_class" {
  description = "db.serverless (Serverless v2) or an r-class like db.r6g.large"
  type        = string
  default     = "db.serverless"
}

variable "aurora_serverless_min_capacity" {
  description = "Serverless v2 minimum ACUs (1 ACU ~ 2 GiB)"
  type        = number
  default     = 1
}

variable "aurora_serverless_max_capacity" {
  description = "Serverless v2 maximum ACUs"
  type        = number
  default     = 8
}

variable "aurora_instance_count" {
  description = "Instances in the us-east-1 cluster (1 = writer only)"
  type        = number
  default     = 1
}

variable "youtube_oauth_secret_name" {
  description = "Manually created YouTube OAuth secret (cht-dev-youtube-oauth in dev, cht-companion-youtube-oauth in prod)"
  type        = string
  default     = "cht-dev-youtube-oauth"
}

variable "secrets_replica_regions" {
  description = "Regions to replicate companion-owned secrets to (Aurora database secret)"
  type        = list(string)
  default     = []
}

variable "db_engine_version" {
  type    = string
  default = "16.9"
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "db_allocated_storage" {
  type    = number
  default = 20
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "db_backup_retention_period" {
  type    = number
  default = 7
}

# ECS companion service
variable "companion_task_cpu" {
  type    = number
  default = 512
}

variable "companion_task_memory" {
  type    = number
  default = 1024
}

variable "companion_desired_count" {
  type    = number
  default = 1
}

variable "companion_min_capacity" {
  type    = number
  default = 1
}

variable "companion_max_capacity" {
  type    = number
  default = 2
}

variable "companion_enable_scheduled_scaling" {
  type    = bool
  default = false
}

# KB Lambda
variable "kb_schedule_expression" {
  type    = string
  default = "rate(1 day)"
}

variable "kb_platform_catalog_url" {
  description = "cht-platform-tool public catalog API the enqueue Lambda reads (ContentHub is only reachable through it)"
  type        = string
}
