locals {
  prefix              = var.resource_prefix
  service_dns_name    = var.service_connect_dns_name
  container_image_tag = try(split(":", var.container_image)[1], "unknown")
  is_prod             = var.environment == "prod"
}

resource "aws_security_group" "companion" {
  name        = "${local.prefix}-sg"
  description = "Security group for cht-companion ECS tasks (Service Connect only)"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTP from platform backend via Service Connect mesh"
    from_port       = var.container_port
    to_port         = var.container_port
    protocol        = "tcp"
    security_groups = var.platform_backend_security_group_ids
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${local.prefix}-sg"
    Environment = var.environment
  }
}

resource "aws_ecs_task_definition" "companion" {
  family                   = local.prefix
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "companion"
      image     = var.container_image
      essential = true

      portMappings = [
        {
          name          = local.service_dns_name
          containerPort = var.container_port
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "PORT", value = tostring(var.container_port) },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "CHT_ENVIRONMENT", value = var.environment },
        { name = "APP_NAME", value = local.prefix },
        { name = "IMAGE_TAG", value = local.container_image_tag },
      ]

      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = "${var.database_secret_arn}:url::"
        },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "companion"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -sf http://localhost:${var.container_port}/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name        = "${local.prefix}-task"
    Environment = var.environment
  }
}

resource "aws_ecs_service" "companion" {
  name            = local.prefix
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.companion.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.companion.id]
    assign_public_ip = false
  }

  service_connect_configuration {
    enabled   = true
    namespace = var.service_connect_namespace_arn

    service {
      port_name      = local.service_dns_name
      discovery_name = local.service_dns_name

      client_alias {
        port     = var.container_port
        dns_name = local.service_dns_name
      }
    }
  }

  # Rolling deploy: min healthy 100% keeps a task up; max 200% allows the new task to start first.
  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = local.is_prod ? 50 : 100

  deployment_circuit_breaker {
    enable   = true
    rollback = local.is_prod
  }

  enable_execute_command = true

  tags = {
    Name        = "${local.prefix}-service"
    Environment = var.environment
  }
}

resource "aws_appautoscaling_target" "companion" {
  max_capacity       = var.max_capacity
  min_capacity       = var.min_capacity
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.companion.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "companion_cpu" {
  name               = "${local.prefix}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.companion.resource_id
  scalable_dimension = aws_appautoscaling_target.companion.scalable_dimension
  service_namespace  = aws_appautoscaling_target.companion.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 70.0
  }
}

resource "aws_appautoscaling_scheduled_action" "companion_scale_down" {
  count              = var.enable_scheduled_scaling && !local.is_prod ? 1 : 0
  name               = "${local.prefix}-scale-down"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.companion.resource_id
  scalable_dimension = aws_appautoscaling_target.companion.scalable_dimension
  schedule           = "cron(0 1 ? * TUE-SAT *)"

  scalable_target_action {
    min_capacity = 0
    max_capacity = 0
  }
}

resource "aws_appautoscaling_scheduled_action" "companion_scale_up" {
  count              = var.enable_scheduled_scaling && !local.is_prod ? 1 : 0
  name               = "${local.prefix}-scale-up"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.companion.resource_id
  scalable_dimension = aws_appautoscaling_target.companion.scalable_dimension
  schedule           = "cron(0 13 ? * MON-FRI *)"

  scalable_target_action {
    min_capacity = var.min_capacity
    max_capacity = var.max_capacity
  }
}
