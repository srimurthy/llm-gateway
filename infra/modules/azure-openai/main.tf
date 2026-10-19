/**
 * Azure OpenAI in several regions, reachable only from the AWS NAT gateways.
 *
 * Keys stay out of Terraform outputs: scripts/sync-azure-keys.sh copies them into
 * Secrets Manager, where the gateway reads them.
 */

locals {
  deployments = {
    for pair in setproduct(var.locations, keys(var.deployments)) :
    "${pair[0]}/${pair[1]}" => merge(var.deployments[pair[1]], {
      location = pair[0]
      name     = pair[1]
    })
  }
}

resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.locations[0]
  tags     = var.tags
}

resource "azurerm_cognitive_account" "this" {
  for_each = toset(var.locations)

  name                  = "${var.name_prefix}-${each.key}"
  location              = each.key
  resource_group_name   = azurerm_resource_group.this.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "${var.name_prefix}-${each.key}"

  local_auth_enabled                 = true
  public_network_access_enabled      = true
  outbound_network_access_restricted = true

  network_acls {
    default_action = "Deny"
    ip_rules       = var.allowed_ip_ranges
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "azurerm_cognitive_deployment" "this" {
  for_each = local.deployments

  name                   = each.value.name
  cognitive_account_id   = azurerm_cognitive_account.this[each.value.location].id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "OpenAI"
    name    = each.value.model_name
    version = each.value.model_version
  }

  sku {
    name     = each.value.sku_name
    capacity = each.value.capacity
  }
}
