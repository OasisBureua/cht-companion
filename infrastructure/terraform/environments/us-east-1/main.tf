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
    # State key: pass via -backend-config=../backends/us-east-1-{development|prod}.hcl
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "cht-companion"
      Environment = var.environment
      Region      = var.aws_region
      ManagedBy   = "Terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  is_prod          = var.environment == "prod"
  resource_prefix  = local.is_prod ? "cht-companion" : "cht-dev-companion"
  log_retention_days = local.is_prod ? 365 : 7
  vpc_id             = var.platform_vpc_id != "" ? var.platform_vpc_id : data.aws_vpc.platform[0].id
  private_subnet_ids = length(var.platform_private_subnet_ids) > 0 ? var.platform_private_subnet_ids : data.aws_subnets.private[0].ids
  cluster_arn        = var.ecs_cluster_arn != "" ? var.ecs_cluster_arn : data.aws_ecs_cluster.platform[0].arn
  cluster_name       = var.ecs_cluster_name
  platform_backend_security_group_ids = length(var.platform_backend_security_group_ids) > 0 ? var.platform_backend_security_group_ids : [data.aws_security_group.platform_backend[0].id]
}

data "aws_vpc" "platform" {
  count = var.platform_vpc_id == "" ? 1 : 0

  filter {
    name   = "tag:Name"
    values = [var.platform_vpc_name]
  }
}

data "aws_subnets" "private" {
  count = length(var.platform_private_subnet_ids) == 0 ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [local.vpc_id]
  }

  filter {
    name   = "tag:Name"
    values = ["*private*"]
  }
}

data "aws_ecs_cluster" "platform" {
  count        = var.ecs_cluster_arn == "" ? 1 : 0
  cluster_name = var.ecs_cluster_name
}

data "aws_security_group" "platform_backend" {
  count = length(var.platform_backend_security_group_ids) == 0 ? 1 : 0
  name  = var.platform_backend_security_group_name
}

resource "aws_kms_key" "companion" {
  description             = "KMS key for cht-companion ${var.environment}"
  deletion_window_in_days = local.is_prod ? 30 : 7
  enable_key_rotation     = true

  tags = {
    Name = "${local.resource_prefix}-kms"
  }
}

resource "aws_kms_alias" "companion" {
  name          = "alias/${local.resource_prefix}"
  target_key_id = aws_kms_key.companion.key_id
}

resource "aws_cloudwatch_log_group" "companion" {
  name              = "/ecs/${local.resource_prefix}"
  retention_in_days = local.log_retention_days
  kms_key_id        = aws_kms_key.companion.arn

  tags = {
    Name = "${local.resource_prefix}-logs"
  }
}

resource "aws_service_discovery_http_namespace" "companion" {
  name        = var.service_connect_namespace_name
  description = "Service Connect namespace for cht-companion (${var.environment})"

  tags = {
    Name = var.service_connect_namespace_name
  }
}

module "ecr" {
  source = "../../modules/compute/ecr"

  resource_prefix           = local.resource_prefix
  environment               = var.environment
  companion_repository_name = var.companion_ecr_repository_name
  kb_repository_name        = var.kb_ecr_repository_name
}

module "companion_db" {
  source = "../../modules/database/companion-db"

  resource_prefix         = local.resource_prefix
  environment             = var.environment
  vpc_id                  = local.vpc_id
  private_subnet_ids      = local.private_subnet_ids
  kms_key_arn             = aws_kms_key.companion.arn
  engine_version          = var.db_engine_version
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_storage
  multi_az                = var.db_multi_az
  backup_retention_period = var.db_backup_retention_period
}

module "iam" {
  source = "../../modules/security/iam"

  resource_prefix = local.resource_prefix
  environment     = var.environment
  aws_region      = var.aws_region
  aws_account_id  = data.aws_caller_identity.current.account_id
  kms_key_arn     = aws_kms_key.companion.arn
  secret_arns = [
    module.companion_db.database_secret_arn,
  ]
}

module "ecs_companion" {
  source = "../../modules/compute/ecs-companion"

  resource_prefix                     = local.resource_prefix
  environment                         = var.environment
  aws_region                          = var.aws_region
  vpc_id                              = local.vpc_id
  private_subnet_ids                  = local.private_subnet_ids
  cluster_arn                         = local.cluster_arn
  cluster_name                        = local.cluster_name
  service_connect_namespace_arn       = aws_service_discovery_http_namespace.companion.arn
  service_connect_dns_name            = var.service_connect_dns_name
  platform_backend_security_group_ids = local.platform_backend_security_group_ids
  execution_role_arn                  = module.iam.ecs_execution_role_arn
  task_role_arn                       = module.iam.ecs_task_role_arn
  log_group_name                      = aws_cloudwatch_log_group.companion.name
  container_image                     = var.companion_image
  database_secret_arn                 = module.companion_db.database_secret_arn
  task_cpu                            = var.companion_task_cpu
  task_memory                         = var.companion_task_memory
  desired_count                       = var.companion_desired_count
  min_capacity                        = var.companion_min_capacity
  max_capacity                        = var.companion_max_capacity
  enable_scheduled_scaling            = var.companion_enable_scheduled_scaling
}

module "kb_lambda" {
  source = "../../modules/kb/lambda"

  resource_prefix     = local.resource_prefix
  environment         = var.environment
  vpc_id              = local.vpc_id
  private_subnet_ids  = local.private_subnet_ids
  kms_key_arn         = aws_kms_key.companion.arn
  lambda_role_arn     = module.iam.lambda_kb_role_arn
  container_image     = var.kb_image
  database_secret_arn = module.companion_db.database_secret_arn
  log_retention_days  = local.log_retention_days
  schedule_expression = var.kb_schedule_expression
}

resource "aws_security_group_rule" "rds_from_companion" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = module.companion_db.security_group_id
  source_security_group_id = module.ecs_companion.security_group_id
  description              = "PostgreSQL from companion ECS"
}

resource "aws_security_group_rule" "rds_from_kb_lambda" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = module.companion_db.security_group_id
  source_security_group_id = module.kb_lambda.security_group_id
  description              = "PostgreSQL from KB Lambda"
}
