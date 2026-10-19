# Public egress ranges of the corporate network (proxies, NAT, VPN concentrators).
# The NLB admits nothing else. These are documentation ranges: replace them.
client_cidrs = ["203.0.113.0/24", "198.51.100.0/24"]

access_logs_bucket = "acme-llmgw-lb-logs-us-east-1"

state_bucket = "acme-llm-gateway-tfstate-111122223333"

tags = {
  CostCenter = "platform-ai"
  Owner      = "ai-platform-team"
}
