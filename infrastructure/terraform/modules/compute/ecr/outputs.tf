output "companion_repository_url" {
  value = aws_ecr_repository.companion.repository_url
}

output "companion_kb_repository_url" {
  value = aws_ecr_repository.companion_kb.repository_url
}
