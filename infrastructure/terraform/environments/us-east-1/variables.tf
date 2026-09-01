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

# Container images (overridden per deploy in CI)
variable "companion_image" {
  type = string
}

variable "kb_image" {
  type = string
}

variable "companion_ecr_repository_name" {
  type = string
}

variable "kb_ecr_repository_name" {
  type = string
}

# Database
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
