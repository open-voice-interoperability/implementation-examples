param(
    [Parameter(Mandatory=$true)]
    [string]$TargetUrl,
    [Parameter(Mandatory=$true)]
    [string]$Label,
    [string]$Prompt1 = "Hello",
    [string]$Prompt2 = "Hello again"
)

$proxy = 'http://localhost:8090/api/proxy-send'
$conversation = @{
    id = ("conv-$Label-" + [guid]::NewGuid().ToString())
    conversants = @()
}
$sender = @{
    speakerUri = 'openFloor://localhost/AssistantClientConvenerWeb'
    serviceUrl = 'http://localhost'
}
$L = $Label.ToUpperInvariant()

function Send-Proxy([array]$events) {
    $payload = @{
        openFloor = @{
            conversation = $conversation
            sender = $sender
            events = $events
        }
    }

    $body = @{
        targetUrl = $TargetUrl
        payload = $payload
        timeoutMs = 20000
    } | ConvertTo-Json -Depth 80

    Invoke-RestMethod -Method Post -Uri $proxy -ContentType 'application/json' -Body $body
}

function Event-Types($resp) {
    (($resp.json.openFloor.events | ForEach-Object { $_.eventType }) -join ',')
}

function First-UtteranceText($resp) {
    foreach ($e in $resp.json.openFloor.events) {
        if ($e.eventType -eq 'utterance') {
            $dialog = $e.parameters.dialogEvent
            if ($null -ne $dialog.features.text.tokens -and $dialog.features.text.tokens.Count -gt 0) {
                return $dialog.features.text.tokens[0].value
            }
            if ($null -ne $dialog.features.text.values -and $dialog.features.text.values.Count -gt 0) {
                return $dialog.features.text.values[0]
            }
        }
    }
    return ''
}

try {
    $gm = Send-Proxy @(@{ eventType = 'getManifests'; to = @{ serviceUrl = $TargetUrl } })
    $manifestEvent = $null
    foreach ($evt in $gm.json.openFloor.events) {
        if ($evt.eventType -eq 'publishManifests') {
            $manifestEvent = $evt
            break
        }
    }

    $hasManifest = $false
    if ($manifestEvent -and $manifestEvent.parameters.servicingManifests -and $manifestEvent.parameters.servicingManifests.Count -gt 0) {
        $ident = $manifestEvent.parameters.servicingManifests[0].identification
        $name = $ident.conversationalName
        $speaker = $ident.speakerUri
        $service = $ident.serviceUrl
        $hasManifest = $true
    }
    else {
        $name = $Label
        $speaker = $gm.json.openFloor.sender.speakerUri
        $service = $gm.json.openFloor.sender.serviceUrl
    }

    if (-not $speaker) { $speaker = $TargetUrl }
    if (-not $service) { $service = $TargetUrl }

    if ($hasManifest) {
        $conversation.conversants = @(
            @{
                identification = @{
                    speakerUri = $speaker
                    serviceUrl = $service
                    conversationalName = $name
                }
            }
        )
    }

    $invite = Send-Proxy @(@{ eventType = 'invite'; to = @{ serviceUrl = $TargetUrl } })
    if (-not $hasManifest -and $invite.json.openFloor.sender.speakerUri) {
        $speaker = $invite.json.openFloor.sender.speakerUri
    }

    $utt = Send-Proxy @(
        @{
            eventType = 'utterance'
            to = @{ serviceUrl = $TargetUrl; private = $true }
            parameters = @{
                dialogEvent = @{
                    speakerUri = $sender.speakerUri
                    features = @{
                        text = @{
                            mimeType = 'text/plain'
                            tokens = @(@{ value = $Prompt1 })
                        }
                    }
                }
            }
        }
    )

    $dir = Send-Proxy @(
        @{
            eventType = 'utterance'
            to = @{ speakerUri = $speaker; private = $true }
            parameters = @{
                dialogEvent = @{
                    speakerUri = $sender.speakerUri
                    features = @{
                        text = @{
                            mimeType = 'text/plain'
                            tokens = @(@{ value = $Prompt2 })
                        }
                    }
                }
            }
        }
    )

    Write-Output ("${L}_GETMANIFESTS_OK={0} STATUS={1} TYPES={2}" -f $gm.ok, $gm.status, (Event-Types $gm))
    Write-Output ("${L}_MANIFEST_NAME={0} SPEAKER={1}" -f $name, $speaker)
    Write-Output ("${L}_INVITE_OK={0} STATUS={1} TYPES={2}" -f $invite.ok, $invite.status, (Event-Types $invite))
    Write-Output ("${L}_UTTERANCE_OK={0} STATUS={1} TYPES={2}" -f $utt.ok, $utt.status, (Event-Types $utt))
    Write-Output ("${L}_UTTERANCE_TEXT={0}" -f (First-UtteranceText $utt))
    Write-Output ("${L}_DIRECTED_OK={0} STATUS={1} TYPES={2}" -f $dir.ok, $dir.status, (Event-Types $dir))
    Write-Output ("${L}_DIRECTED_TEXT={0}" -f (First-UtteranceText $dir))
}
catch {
    Write-Output ("${L}_ERROR={0}" -f $_.Exception.Message)
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
        Write-Output ("${L}_ERROR_DETAILS={0}" -f $_.ErrorDetails.Message)
    }
    exit 1
}
