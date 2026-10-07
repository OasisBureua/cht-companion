variable "resource_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "kms_key_arn" {
  type = string
}

variable "lambda_role_arn" {
  type = string
}

variable "container_image" {
  description = "Embed worker image (kb/Dockerfile)"
  type        = string
}

variable "enqueue_container_image" {
  description = "Catalog enqueue image (kb/Dockerfile.enqueue)"
  type        = string
}

variable "database_secret_arn" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "lambda_timeout_seconds" {
  type    = number
  default = 900
}

variable "lambda_memory_mb" {
  type    = number
  default = 1024
}

variable "platform_catalog_url" {
  description = "cht-platform-tool public catalog API base (ContentHub proxy), e.g. https://devapp.communityhealth.media/api/catalog"
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge schedule for periodic KB refresh"
  type        = string
  default     = "rate(1 day)"
}
