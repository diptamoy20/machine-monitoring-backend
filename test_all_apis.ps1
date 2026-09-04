$baseUrl = "http://localhost:8000"

function Test-Endpoint {
    param($Name, $Method, $Url, $Body = $null)
    Write-Host "`n--- $Name ---" -ForegroundColor Cyan
    try {
        if ($Body) {
            $response = Invoke-RestMethod -Uri $Url -Method $Method -Body ($Body | ConvertTo-Json -Depth 5) -ContentType "application/json"
        } else {
            $response = Invoke-RestMethod -Uri $Url -Method $Method
        }
        Write-Host "OK" -ForegroundColor Green
        $response | ConvertTo-Json -Depth 5 | Select-Object -First 1 | Write-Host
        return $response
    } catch {
        Write-Host "FAILED: $($_.Exception.Message)" -ForegroundColor Red
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message -ForegroundColor Yellow }
    }
}

# --- Root / Health ---
Test-Endpoint "Root" "GET" "$baseUrl/"
Test-Endpoint "Health" "GET" "$baseUrl/health"

# --- Machines (read) ---
Test-Endpoint "Get all machines" "GET" "$baseUrl/api/machines"
Test-Endpoint "Get single machine (MC-001)" "GET" "$baseUrl/api/machines/MC-001"
Test-Endpoint "Get utilization/state (JSON file + image_url)" "GET" "$baseUrl/api/machines/utilization/state"

# --- Machines (write) - uses a throwaway test machine, does not touch real MC-XXX ---
Test-Endpoint "Create test machine (MC-TEST-999)" "POST" "$baseUrl/api/machines" @{
    mc_id = "MC-TEST-999"
    name = "Test Machine"
    status = "stop"
    camera_status = "offline"
}
Test-Endpoint "Patch test machine" "PATCH" "$baseUrl/api/machines/MC-TEST-999" @{
    status = "running"
    camera_status = "online"
}
Test-Endpoint "Put (full update) test machine" "PUT" "$baseUrl/api/machines/MC-TEST-999" @{
    name = "Test Machine Updated"
    status = "stop"
    camera_status = "offline"
}
Test-Endpoint "Get test machine after updates" "GET" "$baseUrl/api/machines/MC-TEST-999"

# --- Detections ---
Test-Endpoint "Get all detections" "GET" "$baseUrl/api/detections"
Test-Endpoint "Get detections for MC-001" "GET" "$baseUrl/api/detections/MC-001"
Test-Endpoint "Create detection event (test machine)" "POST" "$baseUrl/api/detections" @{
    mc_id = "MC-TEST-999"
    status = "running"
    video_url = "/static/videos/test.mp4"
    detected_at = (Get-Date).ToString("o")
}

# --- Inference ---
Test-Endpoint "Inference status" "GET" "$baseUrl/api/inference/status"
# run / run-all skipped by default - uncomment to test (requires mapped video files)
# Test-Endpoint "Run inference (MC-001)" "POST" "$baseUrl/api/inference/run" @{ mc_id = "MC-001" }
# Test-Endpoint "Run inference (all)" "POST" "$baseUrl/api/inference/run-all"

# --- Utilization ---
Test-Endpoint "Get all utilization (DB)" "GET" "$baseUrl/api/utilization"
Test-Endpoint "Sync utilization (test machine)" "POST" "$baseUrl/api/utilization/sync" @{
    data = @{
        "MC-TEST-999" = @{
            runtime = 1.0
            downtime = 2.0
            idle = 3.0
            total_available_time = 6.0
            total_available_time_formatted = "0h 6m"
            utilization_percent = 16.67
        }
    }
}

Write-Host "`n=== ALL TESTS COMPLETE ===" -ForegroundColor Magenta
Write-Host "Note: MC-TEST-999 was created for write-endpoint testing. There is no DELETE endpoint, so it will remain in the database - safe to ignore or remove manually via direct DB access if needed." -ForegroundColor Yellow
