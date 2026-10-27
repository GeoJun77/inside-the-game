<#
Inside the Game - deploy the live web app to Azure Container Apps.

    .\deploy\deploy.ps1                       # first deployment
    .\deploy\deploy.ps1 -Location swedencentral   # if the Foundry region is not allowed
    .\deploy\deploy.ps1 -Image <registry>/inside-the-game:<tag>   # reuse an image built before

What it does:
  1. checks that the active subscription is "Azure for Students" (and stops otherwise);
  2. builds the image with Docker Desktop on this computer (Azure for Students blocks cloud
     builds), pushes it to a container registry and creates the Container App;
  3. stores the Speech key as a Container Apps secret (never in the image, never printed);
  4. gives the app a managed identity and the "Azure AI User" role on the Foundry
     resource, so it calls the agents without any key;
  5. prints the public URL.

Settings are read from .env: FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL, SPEECH_KEY,
SPEECH_REGION and, optionally, SPEECH_VOICE_EN and SPEECH_GOAL_STYLE.
#>
param(
    [string]$ResourceGroup = "rg-inside-the-game",
    [string]$AppName = "inside-the-game-live",
    [string]$EnvName = "inside-the-game-standard",
    [string]$Location = "",
    [string]$Subscription = "Azure for Students",
    [string]$Image = ""          # an image already built and tagged on this computer: no rebuild
)
$ErrorActionPreference = "Stop"

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }
# az is an external program: PowerShell does not stop on its errors by itself, so every
# call is checked and the script stops at the first failure (nothing half-done after it)
# "does it exist?" questions: a "not found" answer (or an extension warning) on stderr is
# not an error here, so PowerShell must not stop on it
function AzQuery { $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try { $out = & az @args 2>$null } finally { $ErrorActionPreference = $old }
    $global:LASTEXITCODE = 0; return $out }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (see the message above). Stopped here." } }

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
Check "Selecting the subscription"
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
    Check "Registering $ns"
}

Step "Building the image on this computer (Docker) and sending it to Azure"
# Azure for Students does not allow cloud builds (ACR Tasks), so the image is built here
# with Docker Desktop and pushed to a container registry in the resource group.
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker Desktop is needed (Azure for Students blocks cloud builds). Install it, start it, then run this script again."
}
docker info --format "{{.ServerVersion}}" | Out-Null
Check "Reaching Docker (is Docker Desktop started?)"
$acr = az acr list --resource-group $ResourceGroup --query "[0].name" -o tsv
if (-not $acr) {
    $acr = "itg" + (Get-Random -Minimum 10000000 -Maximum 99999999)
    az group create --name $ResourceGroup --location $Location --only-show-errors | Out-Null
    Check "Creating the resource group"
    az acr create --name $acr --resource-group $ResourceGroup --sku Basic --location $Location --only-show-errors | Out-Null
    Check "Creating the container registry"
}
az acr update --name $acr --admin-enabled true --only-show-errors | Out-Null
Check "Enabling registry access for the app"
$server = az acr show --name $acr --query loginServer -o tsv
Write-Host "Registry: $server"
az acr login --name $acr
Check "Signing in to the registry"
if ($Image) {
    $image = $Image
    Write-Host "Using the image already built: $image"
} else {
    $image = "$server/inside-the-game:$(Get-Date -Format 'yyyyMMdd-HHmm')"
    docker build --platform linux/amd64 -t $image (Join-Path $PSScriptRoot "..")
    Check "Building the image"
}
# a home connection can drop during a long upload: try again (layers already sent are skipped)
for ($try = 1; $try -le 4; $try++) {
    docker push $image
    if ($LASTEXITCODE -eq 0) { break }
    if ($try -eq 4) { Check "Sending the image to Azure" }
    Write-Host "Upload interrupted, trying again ($($try + 1)/4)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 5
    az acr login --name $acr | Out-Null
}
# the registry credentials go straight to the app, never printed
$regUser = az acr credential show --name $acr --query username -o tsv
$regPass = az acr credential show --name $acr --query "passwords[0].value" -o tsv

Step "Creating the app (a few minutes)"
$plain = @(
    "FOUNDRY_PROJECT_ENDPOINT=$($settings['FOUNDRY_PROJECT_ENDPOINT'])",
    "FOUNDRY_MODEL=$($settings['FOUNDRY_MODEL'])",
    "SPEECH_REGION=$($settings['SPEECH_REGION'])",
    "SPEECH_VOICE_EN=$(if ($settings['SPEECH_VOICE_EN']) { $settings['SPEECH_VOICE_EN'] } else { 'en-US-DavisNeural' })",
    "SPEECH_GOAL_STYLE=$(if ($settings['SPEECH_GOAL_STYLE']) { $settings['SPEECH_GOAL_STYLE'] } else { 'spelled' })",
    "SPEECH_KEY=secretref:speech-key"
)
# A STANDARD Container Apps environment: the "express" kind (what "az containerapp up" may
# create) does not support a managed identity, and the app needs one to reach Foundry.
$envExists = AzQuery containerapp env show --name $EnvName --resource-group $ResourceGroup --query name -o tsv --only-show-errors
if (-not $envExists) {
    az containerapp env create --name $EnvName --resource-group $ResourceGroup --location $Location `
        --logs-destination none --only-show-errors | Out-Null
    Check "Creating the Container Apps environment"
}
$exists = AzQuery containerapp show --name $AppName --resource-group $ResourceGroup --query name -o tsv --only-show-errors
if ($exists) {
    # a re-deployment: the Speech key, then the new image and settings
    az containerapp secret set --name $AppName --resource-group $ResourceGroup `
        --secrets "speech-key=$($settings['SPEECH_KEY'])" --only-show-errors | Out-Null
    Check "Storing the Speech key"
    az containerapp update --name $AppName --resource-group $ResourceGroup --image $image `
        --set-env-vars $plain --only-show-errors | Out-Null
    Check "Updating the app to the new image"
} else {
    # one replica (each match lives in the app's memory), 1 vCPU / 2 GiB, the Speech key as
    # a secret (never in the image, never printed), and a system-assigned managed identity
    az containerapp create --name $AppName --resource-group $ResourceGroup --environment $EnvName `
        --image $image --registry-server $server --registry-username $regUser --registry-password $regPass `
        --ingress external --target-port 8000 --min-replicas 1 --max-replicas 1 --cpu 1 --memory 2Gi `
        --secrets "speech-key=$($settings['SPEECH_KEY'])" --env-vars $plain `
        --system-assigned --only-show-errors | Out-Null
    Check "Creating the app"
}

# ---------- managed identity and the Foundry role ----------
Step "Giving the app access to Foundry"
$principal = AzQuery containerapp show --name $AppName --resource-group $ResourceGroup --query identity.principalId -o tsv --only-show-errors
if (-not $principal) {
    $principal = az containerapp identity assign --name $AppName --resource-group $ResourceGroup `
        --system-assigned --query principalId -o tsv
    Check "Assigning the managed identity"
}
# the role names differ between tenants and Foundry versions: give the ones that exist
# ("Azure AI User" on the new Foundry, "Azure AI Developer" and the Cognitive Services
# user roles otherwise); at least one must succeed
$granted = @()
foreach ($role in "Azure AI User", "Azure AI Developer", "Cognitive Services User", "Cognitive Services OpenAI User") {
    if (-not (az role definition list --name $role --query "[0].id" -o tsv)) { continue }
    if (az role assignment list --assignee $principal --role $role --scope $foundry.id --query "[0].id" -o tsv) {
        $granted += $role; continue                       # already given (a re-deployment)
    }
    az role assignment create --assignee-object-id $principal --assignee-principal-type ServicePrincipal `
        --role $role --scope $foundry.id --only-show-errors | Out-Null
    if ($LASTEXITCODE -eq 0) { $granted += $role }
}
if (-not $granted) { throw "No Foundry role could be given to the app. Stopped here." }
Write-Host "Roles given on Foundry: $($granted -join ', ')"

# ---------- the URL ----------
$fqdn = az containerapp show --name $AppName --resource-group $ResourceGroup `
    --query properties.configuration.ingress.fqdn -o tsv
Step "Done"
Write-Host "Live at: https://$fqdn" -ForegroundColor Green
Write-Host "The Foundry role can take a few minutes to apply: if the first match fails, wait 5 minutes and retry."
