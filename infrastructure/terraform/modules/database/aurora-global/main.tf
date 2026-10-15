# Aurora PostgreSQL Global Database, same layout as cht-platform-tool and
# cht-content-hub: primary (writer) in us-east-1, read-only secondary in
# us-east-2. pgvector needs no parameter; backend/db/migrations/001 runs
# CREATE EXTENSION vector on first start, and the secondary replicates it.

locals {
  name                          = "${var.resource_prefix}-aurora-${var.role}"
  database_secret_name          = "${var.resource_prefix}-database-secrets"
  enhanced_monitoring_role_name = "${var.resource_prefix}-aurora-enhanced-monitoring"
}

resource "aws_db_subnet_group" "aurora" {
  name       = "${local.name}-subnet"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name        = "${local.name}-subnet"
    Environment = var.environment
  }
}

# Ingress is added by the environment (aws_vpc_security_group_ingress_rule),
# so ECS/Lambda security groups don't create a cycle with this module.
resource "aws_security_group" "aurora" {
  name        = "${local.name}-sg"
  description = "cht-companion Aurora PostgreSQL (${var.role})"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.name}-sg"
    Environment = var.environment
  }
}

resource "random_password" "master" {
  count = var.role == "primary" ? 1 : 0

  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_rds_cluster_parameter_group" "aurora" {
  count = var.role == "primary" ? 1 : 0

  name        = "${var.resource_prefix}-aurora-postgres15"
  family      = "aurora-postgresql15"
  description = "Aurora PostgreSQL 15 cluster parameters for ${var.resource_prefix}"

  parameter {
    name  = "log_connections"
    value = "1"
  }

  parameter {
    name  = "log_disconnections"
    value = "1"
  }

  tags = {
    Name        = "${var.resource_prefix}-aurora-params"
    Environment = var.environment
  }
}

resource "aws_rds_global_cluster" "this" {
  count = var.role == "primary" ? 1 : 0

  global_cluster_identifier = "${var.resource_prefix}-global"
  engine                    = "aurora-postgresql"
  engine_version            = var.engine_version
  storage_encrypted         = true
  deletion_protection       = var.deletion_protection
}

resource "aws_rds_cluster" "this" {
  cluster_identifier = local.name
  engine             = "aurora-postgresql"
  engine_version     = var.engine_version
  engine_mode        = "provisioned"

  global_cluster_identifier = var.role == "primary" ? aws_rds_global_cluster.this[0].id : var.global_cluster_identifier

  database_name   = var.role == "primary" ? var.database_name : null
  master_username = var.role == "primary" ? var.master_username : null
  master_password = var.role == "primary" ? random_password.master[0].result : null

  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]
  kms_key_id             = var.kms_key_arn
  storage_encrypted      = true

  backup_retention_period      = var.backup_retention_period
  preferred_backup_window      = "03:00-04:00"
  preferred_maintenance_window = "mon:04:00-mon:05:00"

  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = var.environment != "prod"
  final_snapshot_identifier       = var.environment == "prod" ? "${local.name}-final" : null
  enabled_cloudwatch_logs_exports = ["postgresql"]
  copy_tags_to_snapshot           = true

  db_cluster_parameter_group_name = var.role == "primary" ? aws_rds_cluster_parameter_group.aurora[0].name : null

  lifecycle {
    precondition {
      condition     = var.role == "primary" || var.global_cluster_identifier != ""
      error_message = "A secondary needs global_cluster_identifier. Apply us-east-1 with db_engine = \"aurora\" first."
    }

    ignore_changes = [
      master_password,
      # AWS sets these on global secondary members; "correcting" them on a
      # later apply would detach the cluster from the global database.
      global_cluster_identifier,
      replication_source_identifier,
    ]
  }
}

resource "aws_iam_role" "enhanced_monitoring" {
  count = var.enhanced_monitoring_interval > 0 && var.role == "primary" ? 1 : 0

  name = local.enhanced_monitoring_role_name

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "monitoring.rds.amazonaws.com" }
    }]
  })

  tags = {
    Name        = local.enhanced_monitoring_role_name
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "enhanced_monitoring" {
  count = var.enhanced_monitoring_interval > 0 && var.role == "primary" ? 1 : 0

  role       = aws_iam_role.enhanced_monitoring[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

# IAM is account-wide: the secondary reuses the role the primary created.
data "aws_iam_role" "enhanced_monitoring" {
  count = var.enhanced_monitoring_interval > 0 && var.role == "secondary" ? 1 : 0

  name = local.enhanced_monitoring_role_name
}

locals {
  enhanced_monitoring_role_arn = var.enhanced_monitoring_interval > 0 ? (
    var.role == "primary" ? aws_iam_role.enhanced_monitoring[0].arn : data.aws_iam_role.enhanced_monitoring[0].arn
  ) : null
}

resource "aws_rds_cluster_instance" "this" {
  count = var.instance_count

  identifier         = "${local.name}-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.this.id
  instance_class     = var.instance_class
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version

  publicly_accessible             = false
  auto_minor_version_upgrade      = true
  performance_insights_enabled    = true
  performance_insights_kms_key_id = var.kms_key_arn
  monitoring_interval             = var.enhanced_monitoring_interval
  monitoring_role_arn             = local.enhanced_monitoring_role_arn

  tags = {
    Name        = "${local.name}-${count.index + 1}"
    Environment = var.environment
  }

  # auto_minor_version_upgrade moves engine_version in AWS; don't reboot to
  # "correct" it on every apply.
  lifecycle {
    ignore_changes = [engine_version]
  }
}

# Same secret name and JSON shape as modules/database/companion-db, so the ECS
# task (DATABASE_URL = <arn>:url::), the KB Lambdas and IAM need no change.
resource "aws_secretsmanager_secret" "database" {
  count = var.role == "primary" ? 1 : 0

  name                    = local.database_secret_name
  description             = "cht-companion database connection (Aurora writer endpoint)"
  recovery_window_in_days = var.environment == "prod" ? 30 : 0
  kms_key_id              = var.kms_key_arn

  tags = {
    Name        = local.database_secret_name
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "database" {
  count = var.role == "primary" ? 1 : 0

  secret_id = aws_secretsmanager_secret.database[0].id
  secret_string = jsonencode({
    username = var.master_username
    password = random_password.master[0].result
    host     = aws_rds_cluster.this.endpoint
    port     = aws_rds_cluster.this.port
    dbname   = var.database_name
    url      = "postgresql://${var.master_username}:${urlencode(random_password.master[0].result)}@${aws_rds_cluster.this.endpoint}:${aws_rds_cluster.this.port}/${var.database_name}"
  })
}
