# us-east-2: read-only Aurora secondary for disaster recovery. The companion
# service, KB Lambdas and the writer stay in environments/us-east-1.
# Apply us-east-1 prod first; this reads its global cluster ID from state.

terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "s3" {
    bucket       = "cht-companion-terraform-state"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
    # State key: -backend-config=../backends/us-east-2-prod.hcl
  }
}

provider "aws" {
  region = "us-east-2"

  default_tags {
    tags = {
      Project     = "cht-companion"
      Environment = var.environment
      Region      = "us-east-2"
      Purpose     = "DisasterRecovery"
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "primary" {
  backend = "s3"

  config = {
    bucket = "cht-companion-terraform-state"
    key    = var.primary_state_key
    region = "us-east-1"
  }
}

data "aws_vpc" "dr" {
  filter {
    name   = "tag:Name"
    values = [var.dr_vpc_name]
  }
}

data "aws_subnets" "dr_private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.dr.id]
  }

  filter {
    name   = "tag:Name"
    values = ["*private*"]
  }
}

locals {
  resource_prefix   = var.environment == "prod" ? "cht-companion" : "cht-${var.environment}-companion"
  global_cluster_id = data.terraform_remote_state.primary.outputs.aurora_global_cluster_id
}

resource "aws_kms_key" "companion" {
  description             = "${local.resource_prefix} Aurora secondary (us-east-2)"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = {
    Name = "${local.resource_prefix}-use2"
  }
}

resource "aws_kms_alias" "companion" {
  name          = "alias/${local.resource_prefix}-use2"
  target_key_id = aws_kms_key.companion.key_id
}

module "aurora_global" {
  source = "../../modules/database/aurora-global"

  role                      = "secondary"
  resource_prefix           = local.resource_prefix
  environment               = var.environment
  vpc_id                    = data.aws_vpc.dr.id
  private_subnet_ids        = data.aws_subnets.dr_private.ids
  kms_key_arn               = aws_kms_key.companion.arn
  engine_version            = data.terraform_remote_state.primary.outputs.aurora_engine_version
  instance_class            = var.aurora_instance_class
  instance_count            = var.aurora_instance_count
  global_cluster_identifier = local.global_cluster_id
  backup_retention_period   = var.backup_retention_period
  deletion_protection       = true
}
