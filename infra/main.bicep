targetScope = 'resourceGroup'

@description('Deployment location')
param location string = resourceGroup().location

@description('Owner tag value required by policy')
param ownerTag string = 'adam.johns@neudesic.com'

@description('ACR name (global, alphanumeric only)')
param acrName string = 'acrcocktailagentdevwus01'

@description('Container Apps environment name')
param containerAppsEnvName string = 'cae-cocktailagent-dev-wus-01'

@description('MCP API container app name')
param mcpContainerAppName string = 'ca-cocktailagent-mcp-dev-wus-01'

@description('Scraper job container app name')
param scraperJobName string = 'caj-cocktail-scraper-dev-wus-01'

@description('PostgreSQL flexible server name')
param postgresServerName string = 'psql-cocktailagent-dev-wus-01'

@description('PostgreSQL database name')
param postgresDbName string = 'cocktails'

@description('PostgreSQL admin username')
param postgresAdminUsername string

@secure()
@description('PostgreSQL admin password')
param postgresAdminPassword string

@description('Key Vault name (global unique)')
param keyVaultName string = 'kvcocktaildevwus01'

@description('Log Analytics workspace name')
param logAnalyticsName string = 'log-cocktailagent-dev-wus-01'

@description('Application Insights name')
param appInsightsName string = 'ai-cocktailagent-dev-wus-01'

@description('MCP API image in ACR')
param mcpApiImage string = 'acrcocktailagentdevwus01.azurecr.io/cocktail-mcp-api:latest'

@description('Scraper job image in ACR')
param scraperImage string = 'acrcocktailagentdevwus01.azurecr.io/cocktail-scraper:latest'

@secure()
@description('MCP API key used for private access')
param mcpApiKey string

var tags = {
  Owner: ownerTag
}

var dbConnectionString = 'postgresql://${postgresAdminUsername}:${postgresAdminPassword}@${postgresServerName}.postgres.database.azure.com:5432/${postgresDbName}?sslmode=require'
var acrPullRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var keyVaultUri = 'https://${keyVaultName}.${environment().suffixes.keyvaultDns}'
var userAssignedMiName = 'mi-cocktail-apps-dev-wus-01'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource kvSecretApiKey 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'mcp-api-key'
  properties: {
    value: mcpApiKey
  }
}

resource kvSecretDbConn 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'db-connection-string'
  properties: {
    value: dbConnectionString
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: postgresServerName
  location: location
  tags: tags
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '16'
    administratorLogin: postgresAdminUsername
    administratorLoginPassword: postgresAdminPassword
    storage: {
      storageSizeGB: 32
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: 'Enabled'
    }
  }
}

resource postgresDb 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgresServer
  name: postgresDbName
}

resource postgresAllowAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: containerAppsEnvName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

resource userAssignedMi 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: userAssignedMiName
  location: location
  tags: tags
}

resource mcpContainerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: mcpContainerAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedMi.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
      }
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: userAssignedMi.id
        }
      ]
      secrets: [
        {
          name: 'mcp-api-key'
          value: mcpApiKey
        }
        {
          name: 'db-connection-string'
          value: dbConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp-api'
          image: mcpApiImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'MCP_API_KEY'
              secretRef: 'mcp-api-key'
            }
            {
              name: 'DATABASE_URL'
              secretRef: 'db-connection-string'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
            {
              name: 'KEY_VAULT_URI'
              value: keyVaultUri
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

resource scraperJob 'Microsoft.App/jobs@2023-05-01' = {
  name: scraperJobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${userAssignedMi.id}': {}
    }
  }
  properties: {
    environmentId: containerAppsEnv.id
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 1
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: [
        {
          server: '${acrName}.azurecr.io'
          identity: userAssignedMi.id
        }
      ]
      secrets: [
        {
          name: 'db-connection-string'
          value: dbConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'scraper'
          image: scraperImage
          resources: {
            cpu: json('0.5')
            memory: '1.0Gi'
          }
          env: [
            {
              name: 'DATABASE_URL'
              secretRef: 'db-connection-string'
            }
            {
              name: 'DRINK_NAME'
              value: 'daiquiri'
            }
            {
              name: 'RESULT_SELECTOR'
              value: '1'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsights.properties.ConnectionString
            }
          ]
        }
      ]
    }
  }
}

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, userAssignedMi.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleDefinitionId
    principalId: userAssignedMi.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output mcpApiUrl string = 'https://${mcpContainerApp.properties.configuration.ingress.fqdn}'
output keyVaultUri string = keyVaultUri
output postgresHost string = '${postgresServerName}.postgres.database.azure.com'
