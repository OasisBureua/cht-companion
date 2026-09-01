variable "resource_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "internal_api_secret" {
  description = "Shared secret for platform BFF -> companion calls (set via TF_VAR or GitHub secret)"
  type        = string
  sensitive   = true
}
