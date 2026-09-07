param(
    [Parameter(Mandatory=$true)]
    [string]$Message
)

$ErrorActionPreference = "Stop"
$ProjectDir = $PSScriptRoot
$ServerHost = "beasapps@192.168.1.28"
$ServerPort = "5143"
$ServerProjectDir = "/var/www/stage.beas.in/public_html/machine-monitoring-opencv"

Set-Location $ProjectDir

Write-Host "=== 1. Checking for incoming changes from GitHub ===" -ForegroundColor Cyan
git fetch origin
$incoming = git log HEAD..origin/master --oneline
if ($incoming) {
    Write-Host "WARNING: origin/master has commits you don't have locally:" -ForegroundColor Yellow
    Write-Host $incoming
    Write-Host "Pull and resolve manually before running this script again:" -ForegroundColor Yellow
    Write-Host "  git pull origin master"
    exit 1
}

Write-Host "=== 2. Staging changes ===" -ForegroundColor Cyan
git add -A

Write-Host "=== 3. Review what's staged before committing ===" -ForegroundColor Cyan
git status
Write-Host "Does this look correct? Press Ctrl+C now to abort if anything looks wrong" -ForegroundColor Yellow
Write-Host "(e.g. unexpected large files, machine-monitoring-backend/, or other unrelated folders)." -ForegroundColor Yellow
Start-Sleep -Seconds 8

Write-Host "=== 4. Committing ===" -ForegroundColor Cyan
git commit -m "$Message"

Write-Host "=== 5. Pushing to master ===" -ForegroundColor Cyan
git push origin feature/specific-code:master
if ($LASTEXITCODE -ne 0) {
    Write-Host "PUSH FAILED. Common causes tonight: large file (>100MB), diverged branch." -ForegroundColor Red
    Write-Host "Check the error above and resolve manually - do not force push blindly." -ForegroundColor Red
    exit 1
}

Write-Host "=== 6. Triggering server deployment ===" -ForegroundColor Cyan
Write-Host "You will be prompted for the server password." -ForegroundColor Yellow
ssh $ServerHost -p $ServerPort "cd $ServerProjectDir && bash deploy.sh"

Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "Reminder: this script does NOT sync app/static/images or app/static/videos." -ForegroundColor Yellow
Write-Host "Run sync_to_server.ps1 separately if new evidence files need to reach the server." -ForegroundColor Yellow
