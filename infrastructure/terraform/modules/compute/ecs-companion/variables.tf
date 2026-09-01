variable "resource_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "cluster_arn" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "service_connect_namespace_arn" {
  description = "ECS Service Connect HTTP namespace ARN on the shared platform cluster"
  type        = string
}

variable "service_connect_dns_name" {
  description = "DNS name for Service Connect client alias (e.g. cht-companion)"
  type        = string
}

variable "platform_backend_security_group_ids" {
  description = "Platform NestJS backend SGs allowed to call companion over Service Connect"
  type        = list(string)
}

variable "execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "log_group_name" {
  type = string
}

variable "container_image" {
  type = string
}

variable "container_port" {
  type    = number
  default = 8080
}

variable "database_secret_arn" {
  type = string
}

variable "app_secrets_arn" {
  type = string
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "desired_count" {
  type    = number
  default = 1
}

variable "min_capacity" {
  type    = number
  default = 1
}

variable "max_capacity" {
  type    = number
  default = 2
}

variable "enable_scheduled_scaling" {
  type    = bool
  default = false
}
