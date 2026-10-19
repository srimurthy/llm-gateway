subscription_id = "00000000-0000-0000-0000-000000000000"
name_prefix     = "acme-llmgw"
locations       = ["eastus2", "swedencentral"]

deployments = {
  "gpt-4o" = {
    model_name    = "gpt-4o"
    model_version = "2024-11-20"
    sku_name      = "GlobalStandard"
    capacity      = 450
  }
}

state_bucket = "acme-llm-gateway-tfstate-111122223333"

tags = {
  CostCenter = "platform-ai"
  Owner      = "ai-platform-team"
}
