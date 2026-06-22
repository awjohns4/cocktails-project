using '../main.bicep'

param location = 'westus'
param ownerTag = 'adam.johns@neudesic.com'

param postgresAdminUsername = readEnvironmentVariable('POSTGRES_ADMIN_USERNAME')
param postgresAdminPassword = readEnvironmentVariable('POSTGRES_ADMIN_PASSWORD')
param mcpApiKey = readEnvironmentVariable('MCP_API_KEY')

param acrName = 'acrcocktailagentdevwus01'
param containerAppsEnvName = 'cae-cocktailagent-dev-wus-01'
param mcpContainerAppName = 'ca-cocktailagent-mcp-dev-wus-01'
param scraperJobName = 'caj-cocktail-scraper-dev-wus-01'
param postgresServerName = 'psql-cocktailagent-dev-wus-01'
param postgresDbName = 'cocktails'
param keyVaultName = 'kvcocktaildevwus01'
param logAnalyticsName = 'log-cocktailagent-dev-wus-01'
param appInsightsName = 'ai-cocktailagent-dev-wus-01'

// Replace image tags in CI/CD or before manual deploy.
param mcpApiImage = 'acrcocktailagentdevwus01.azurecr.io/cocktail-mcp-api:latest'
param scraperImage = 'acrcocktailagentdevwus01.azurecr.io/cocktail-scraper:latest'
