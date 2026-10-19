name     = "llmgw-prod-usw2"
vpc_cidr = "10.41.0.0/16"

api_allowed_cidrs = ["10.2.10.0/24"] # CI runners and the operator bastion network

admin_role_arns = [
  "arn:aws:iam::111122223333:role/platform-admin",
  "arn:aws:iam::111122223333:role/ci-terraform",
]

model_bucket_arn = "arn:aws:s3:::acme-llmgw-models"

bedrock_resource_arns = [
  "arn:aws:bedrock:*::foundation-model/amazon.nova-pro-v1:0",
  "arn:aws:bedrock:us-west-2:111122223333:inference-profile/us.amazon.nova-pro-v1:0",
]

state_bucket = "acme-llm-gateway-tfstate-111122223333"

tags = {
  CostCenter = "platform-ai"
  Owner      = "ai-platform-team"
}
