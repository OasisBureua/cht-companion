variable "resource_prefix" {
  description = "Name prefix, e.g. cht-companion"
  type        = string
}

variable "environment" {
  type = string
}

variable "role" {
  description = "primary (writer, creates the global cluster) or secondary (read-only cluster in another region)"
  type        = string

  validation {
    condition     = contains(["primary", "secondary"], var.role)
    error_message = "role must be primary or secondary"
  }
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "secret_replica_regions" {
  description = "Regions to replicate the database secret to (primary only)"
  type        = list(string)
  default     = []
}

variable "kms_key_arn" {
  description = "KMS key in this region for storage, Performance Insights and the database secret"
  type        = string
}

variable "instance_class" {
  description = "Aurora instance class. Global databases need db.serverless (Serverless v2) or an r-class."
  type        = string
  default     = "db.serverless"
}

variable "serverless_min_capacity" {
  description = "Serverless v2 minimum ACUs (1 ACU ~ 2 GiB). Global databases can't pause at 0."
  type        = number
  default     = 1

  validation {
    condition     = var.serverless_min_capacity >= 0.5
    error_message = "serverless_min_capacity must be at least 0.5 for a global database"
  }
}

variable "serverless_max_capacity" {
  description = "Serverless v2 maximum ACUs"
  type        = number
  default     = 8
}

variable "instance_count" {
  type    = number
  default = 1

  validation {
    condition     = var.instance_count >= 1 && var.instance_count <= 15
    error_message = "instance_count must be between 1 and 15"
  }
}

variable "engine_version" {
  description = "Aurora PostgreSQL version (pgvector is available on 15.x)"
  type        = string
  default     = "15.17"
}

variable "database_name" {
  description = "Initial database name (primary only)"
  type        = string
  default     = "companion"
}

variable "master_username" {
  description = "Master username (primary only)"
  type        = string
  default     = "companion_admin"
}

variable "backup_retention_period" {
  type    = number
  default = 14
}

variable "global_cluster_identifier" {
  description = "Global cluster to join (secondary only)"
  type        = string
  default     = ""
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "enhanced_monitoring_interval" {
  description = "Enhanced Monitoring interval in seconds (0 disables)"
  type        = number
  default     = 60

  validation {
    condition     = contains([0, 1, 5, 10, 15, 30, 60], var.enhanced_monitoring_interval)
    error_message = "enhanced_monitoring_interval must be 0, 1, 5, 10, 15, 30, or 60"
  }
}
