output "service_name" {
  value = aws_ecs_service.companion.name
}

output "service_arn" {
  value = aws_ecs_service.companion.id
}

output "security_group_id" {
  value = aws_security_group.companion.id
}

output "service_connect_dns_name" {
  value = var.service_connect_dns_name
}
