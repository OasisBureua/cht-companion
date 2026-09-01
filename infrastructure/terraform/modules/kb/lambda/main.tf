locals {
  prefix = var.resource_prefix
}

resource "aws_cloudwatch_log_group" "kb" {
  name              = "/aws/lambda/${local.prefix}-kb"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn

  tags = {
    Name        = "${local.prefix}-kb-logs"
    Environment = var.environment
  }
}

resource "aws_security_group" "kb_lambda" {
  name        = "${local.prefix}-kb-sg"
  description = "Security group for cht-companion-kb Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.prefix}-kb-sg"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "kb_ingest" {
  name                       = "${local.prefix}-kb-ingest"
  visibility_timeout_seconds = var.lambda_timeout_seconds * 6
  message_retention_seconds  = 1209600
  kms_master_key_id          = var.kms_key_arn

  tags = {
    Name        = "${local.prefix}-kb-ingest"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "kb_ingest_dlq" {
  name                      = "${local.prefix}-kb-ingest-dlq"
  message_retention_seconds = 1209600
  kms_master_key_id         = var.kms_key_arn

  tags = {
    Name        = "${local.prefix}-kb-ingest-dlq"
    Environment = var.environment
  }
}

resource "aws_sqs_queue_redrive_policy" "kb_ingest" {
  queue_url = aws_sqs_queue.kb_ingest.id
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.kb_ingest_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_function" "kb" {
  function_name = "${local.prefix}-kb"
  role          = var.lambda_role_arn
  package_type  = "Image"
  image_uri     = var.container_image
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.kb_lambda.id]
  }

  environment {
    variables = {
      CHT_ENVIRONMENT = var.environment
      DATABASE_SECRET_ARN = var.database_secret_arn
      KB_INGEST_QUEUE_URL = aws_sqs_queue.kb_ingest.url
    }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.kb.name
  }

  tags = {
    Name        = "${local.prefix}-kb"
    Environment = var.environment
  }
}

resource "aws_lambda_event_source_mapping" "kb_sqs" {
  event_source_arn = aws_sqs_queue.kb_ingest.arn
  function_name    = aws_lambda_function.kb.arn
  batch_size       = 1
  enabled          = true
}

resource "aws_cloudwatch_event_rule" "kb_scheduled" {
  name                = "${local.prefix}-kb-schedule"
  description         = "Scheduled KB corpus refresh (captions/embeddings)"
  schedule_expression = var.schedule_expression

  tags = {
    Name        = "${local.prefix}-kb-schedule"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_event_target" "kb_scheduled" {
  rule      = aws_cloudwatch_event_rule.kb_scheduled.name
  target_id = "kb-lambda"
  arn       = aws_lambda_function.kb.arn

  input = jsonencode({
    source  = "eventbridge.schedule"
    action  = "scheduled_refresh"
  })
}

resource "aws_lambda_permission" "kb_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.kb.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.kb_scheduled.arn
}
