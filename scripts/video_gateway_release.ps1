# Run only the video gateway preflight, backup, migration, and rollout steps.
# Do not deploy unrelated site changes or call paid generation APIs.
param(
    [ValidateSet("preflight", "version", "backup", "migrate", "deploy", "rollback")]
    [string]$Action = "preflight",
    [string]$ImageTag = "",
    [string]$BackupDirectory = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$config = Get-Content (Join-Path $root "deploy_config.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$target = "$($config.server.user)@$($config.server.ip)"
$remoteRoot = $config.server.remote_path
$compose = "cd '$remoteRoot' && docker-compose"
function Invoke-Remote([string]$Command) {
    $singleQuote = [string][char]39
    $quoted = $Command.Replace($singleQuote, $singleQuote + '"' + $singleQuote + '"' + $singleQuote)
    ssh -o BatchMode=yes -o ConnectTimeout=8 $target $quoted
    if ($LASTEXITCODE -ne 0) { throw "Remote command failed with exit code $LASTEXITCODE" }
}
function Require-LocalImage([string]$Tag) {
    if (-not $Tag) { throw "A verified image tag is required" }
    docker image inspect $Tag | Out-Null
}
switch ($Action) {
    "preflight" {
        Invoke-Remote "$compose ps; docker exec novel_postgres psql -U novel_user -d novel_db -At -c 'SELECT version_num FROM alembic_version;'; docker exec novel_postgres psql -U novel_user -d novel_db -At -c 'SELECT project_id, chapter_number, count(*) FROM chapters WHERE deleted_at IS NULL GROUP BY project_id, chapter_number HAVING count(*) > 1 LIMIT 10;'; docker exec novel_postgres psql -U novel_user -d router_gateway -At -c 'SELECT to_regclass(''public.clients'')'; docker exec novel_postgres psql -U novel_user -d router_gateway -At -c 'SELECT count(*) FROM clients;'; docker exec novel_nginx nginx -t"
    }
    "version" {
        Invoke-Remote "docker exec novel_postgres psql -U novel_user -d novel_db -At -c 'SELECT version_num FROM alembic_version;'"
    }
    "backup" {
        if (-not $BackupDirectory) { throw "A backup directory is required" }
        Invoke-Remote "mkdir -p '$BackupDirectory'; docker exec novel_postgres pg_dump -U novel_user -d novel_db -Fc -f /tmp/novel_db.dump; docker exec novel_postgres pg_dump -U novel_user -d router_gateway -Fc -f /tmp/router_gateway.dump; docker cp novel_postgres:/tmp/novel_db.dump '$BackupDirectory/novel_db.dump'; docker cp novel_postgres:/tmp/router_gateway.dump '$BackupDirectory/router_gateway.dump'; docker exec novel_postgres rm -f /tmp/novel_db.dump /tmp/router_gateway.dump"
    }
    "migrate" {
        Invoke-Remote "docker exec novel_backend alembic current; docker exec novel_backend alembic upgrade add_video_api_trial_quota; docker exec novel_gateway_api python -m router_gateway.db.init_db"
    }
    "deploy" {
        Require-LocalImage $ImageTag
        docker save $ImageTag | ssh -o BatchMode=yes $target "docker load"
        Invoke-Remote "$compose up -d --no-deps --no-build gateway-api gateway-worker; docker exec novel_gateway_api python -c 'from urllib.request import urlopen; body=urlopen(\"http://127.0.0.1:8088/health\",timeout=5).read(); raise SystemExit(0 if body==b\"gateway healthy\" else 1)'"
    }
    "rollback" {
        Require-LocalImage $ImageTag
        if (-not $BackupDirectory) { throw "Rollback requires a backup directory" }
        docker save $ImageTag | ssh -o BatchMode=yes $target "docker load"
        Invoke-Remote "$compose up -d --no-deps --no-build gateway-api gateway-worker; docker exec -i novel_postgres pg_restore -U novel_user -d novel_db --clean --if-exists < '$BackupDirectory/novel_db.dump'; docker exec -i novel_postgres pg_restore -U novel_user -d router_gateway --clean --if-exists < '$BackupDirectory/router_gateway.dump'"
    }
}
