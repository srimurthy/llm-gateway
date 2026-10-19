output "endpoints" {
  description = "Endpoint per region, for the routing file's azure_openai providers."
  value       = { for location, account in azurerm_cognitive_account.this : location => account.endpoint }
}

output "account_names" {
  description = "Account name per region (used by scripts/sync-azure-keys.sh)."
  value       = { for location, account in azurerm_cognitive_account.this : location => account.name }
}
