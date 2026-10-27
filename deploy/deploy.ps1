<#
Inside the Game - deploy the live web app to Azure Container Apps.

    .\deploy\deploy.ps1                       # first deployment
    .\deploy\deploy.ps1 -Location swedencentral   # if the Foundry region is not allowed

What it does:
  1. checks that the active subscription is "Azure for Students" (and stops otherwise);
  2. builds the image in the cloud from the Dockerfile and creates the Container App
     (no Docker needed on this computer);
  3. stores the Speech key as a Container Apps secret (never in the image, never printed);
  4. gives the app a managed identity and the "Azure AI User" role on the Foundry
     resource, so it calls the agents without any key;
  5. prints the public URL.

Settings are read from .env: FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL, SPEECH_KEY,
SPEECH_REGION and, optionally, SPEECH_VOICE_EN and SPEECH_GOAL_STYLE.
#>
param(
    [string]$ResourceGroup = "rg-inside-the-game",
    [string]$AppName = "inside-the-game",
    [string]$Location = "",
    [string]$Subscription = "Azure for Students"
)
$ErrorActionPreference = "Stop"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# ---------- settings from .env (values are never printed) ----------
$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) { throw ".env not found next to the project." }
$settings = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $settings[$matches[1]] = $matches[2].Trim().Trim('"').Trim("'")
    }
}
foreach ($name in "FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL", "SPEECH_KEY", "SPEECH_REGION") {
    if (-not $settings[$name]) { throw "$name is missing from .env." }
}
Write-Host "Settings found in .env: $(($settings.Keys | Sort-Object) -join ', ')"

# ---------- 1. the right subscription ----------
Step "Checking the subscription"
az account set --subscription $Subscription | Out-Null
$active = az account show --query name -o tsv
if ($active -ne $Subscription) { throw "Active subscription is '$active', expected '$Subscription'. Nothing was deployed." }
Write-Host "Using: $active"

# ---------- the Foundry resource (for its region and the role) ----------
Step "Finding the Foundry resource"
$account = ([Uri]$settings["FOUNDRY_PROJECT_ENDPOINT"]).Host.Split(".")[0]
$foundry = az resource list --name $account --resource-type "Microsoft.CognitiveServices/accounts" `
    --query "[0].{id:id, location:location}" -o json | ConvertFrom-Json
if (-not $foundry) { throw "Foundry resource '$account' not found in this subscription." }
if (-not $Location) { $Location = $foundry.location }
Write-Host "Foundry resource: $account ($($foundry.location)) | app region: $Location"

# ---------- 2. build in the cloud and create the app ----------
Step "Preparing Azure (providers and the Container Apps extension)"
az extension add --name containerapp --upgrade --only-show-errors | Out-Null
foreach ($ns in "Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.ContainerRegistry") {
    az provider register --namespace $ns --wait | Out-Null
}

Step "Building the image in the cloud and creating the app (a few minutes)"
$plain = @(
    "FOUNDRY_PROJECT_ENDPOINT=$($settings['FOUNDRY_PROJECT_ENDPOINT'])",
    "FOUNDRY_MODEL=$($settings['FOUNDRY_MODEL'])",
    "SPEECH_REGION=$($settings['SPEECH_REGION'])",
    "SPEECH_VOICE_EN=$(if ($settings['SPEECH_VOICE_EN']) { $settings['SPEECH_VOICE_EN'] } else { 'en-US-DavisNeural' })",
    "SPEECH_GOAL_STYLE=$(if ($settings['SPEECH_GOAL_STYLE']) { $settings['SPEECH_GOAL_STYLE'] } else { 'spelled' })"
)
az containerapp up --name $AppName --resource-group $ResourceGroup --location $Location `
    --source (Join-Path $PSScriptRoot "..") --ingress external --target-port 8000 `
    --env-vars $plain --only-show-errors | Out-Null

# ---------- 3. the Speech key as a secret ----------
Step "Storing the Speech key as a secret"
az containerapp secret set --name $AppName --resource-group $ResourceGroup `
    --secrets "speech-key=$($settings['SPEECH_KEY'])" --only-show-errors | Out-Null
# One replica: each match lives in the app's memory. 1 vCPU / 2 GiB is plenty.
az containerapp update --name $AppName --resource-group $ResourceGroup `
    --set-env-vars "SPEECH_KEY=secretref:speech-key" `
    --min-replicas 1 --max-replicas 1 --cpu 1 --memory 2Gi --only-show-errors | Out-Null

# ---------- 4. managed identity and the Foundry role ----------
Step "Giving the app its identity and access to Foundry"
$principal = az containerapp identity assign --name $AppName --resource-group $ResourceGroup `
    --system-assigned --query principalId -o tsv
az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
    --role "Azure AI User" --scope $foundry.id --only-show-errors | Out-Null

# ---------- 5. the URL ----------
$fqdn = az containerapp show --name $AppName --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv
Step "Done"
Write-Host "Live at: https://$fqdn" -ForegroundColor Green
Write-Host "The Foundry role can take a few minutes to apply: if the first match fails, wait 5 minutes and retry."
