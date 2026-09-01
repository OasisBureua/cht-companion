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
  type = string
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

variable "schedule_expression" {
  description = "EventBridge schedule for periodic KB refresh"
  type        = string
  default     = "rate(1 day)"
}
