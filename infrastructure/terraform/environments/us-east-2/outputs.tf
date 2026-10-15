output "aurora_secondary_cluster_id" {
  value = module.aurora_global.cluster_id
}

output "aurora_secondary_reader_endpoint" {
  value = module.aurora_global.reader_endpoint
}

output "aurora_secondary_security_group_id" {
  description = "Add ingress here if a us-east-2 companion service is ever deployed"
  value       = module.aurora_global.security_group_id
}
