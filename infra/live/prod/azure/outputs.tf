output "endpoints" {
  description = "Azure OpenAI endpoint per region."
  value       = module.azure_openai.endpoints
}

output "account_names" {
  description = "Account names, for scripts/sync-azure-keys.sh."
  value       = module.azure_openai.account_names
}
