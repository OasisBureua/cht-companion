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
  type    = number
  default = 1
}

variable "backup_retention_period" {
  type    = number
  default = 14
}
