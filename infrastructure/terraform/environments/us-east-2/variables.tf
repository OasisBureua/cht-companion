variable "environment" {
  type    = string
  default = "prod"
}

variable "primary_state_key" {
  description = "us-east-1 state that owns the Aurora global cluster"
  type        = string
  default     = "us-east-1-prod/terraform.tfstate"
}

variable "dr_vpc_name" {
  description = "Platform's us-east-2 VPC (shared with platform and ContentHub DR)"
  type        = string
  default     = "cht-platform-dr-use2-vpc"
}

variable "aurora_instance_class" {
  type    = string
  default = "db.r6g.large"
}

variable "aurora_instance_count" {
  type    = number
  default = 1
}

variable "backup_retention_period" {
  type    = number
  default = 14
}
