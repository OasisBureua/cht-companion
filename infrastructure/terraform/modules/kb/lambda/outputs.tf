output "lambda_function_name" {
  value = aws_lambda_function.kb.function_name
}

output "lambda_function_arn" {
  value = aws_lambda_function.kb.arn
}

output "kb_ingest_queue_url" {
  value = aws_sqs_queue.kb_ingest.url
}

output "kb_ingest_queue_arn" {
  value = aws_sqs_queue.kb_ingest.arn
}

output "security_group_id" {
  value = aws_security_group.kb_lambda.id
}
