variable "resource_prefix" {
  type = string
}

variable "environment" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "kms_key_arn" {
  type = string
}

variable "secret_arns" {
  type = list(string)
}
