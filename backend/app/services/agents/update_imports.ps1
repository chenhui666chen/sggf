# PowerShell script to update imports in all Python files

$files = Get-ChildItem -Path "." -Filter "*.py" -Exclude "__init__.py","update_imports.ps1"

$replacements = @{
    "from config import" = "from .config import"
    "from knowledge_base import" = "from .knowledge_base import"
    "from memory_manager import" = "from .memory_manager import"
    "from agents import" = "from .agents import"
    "from agent_communication import" = "from .agent_communication import"
    "from agent_coordinator import" = "from .agent_coordinator import"
    "from quality_assessment import" = "from .quality_assessment import"
    "from context_aware_optimizer import" = "from .context_aware_optimizer import"
    "from ai_trace_reduction_processor import" = "from .ai_trace_reduction_processor import"
    "from author_voice_system import" = "from .author_voice_system import"
    "from dialogue_authenticity_module import" = "from .dialogue_authenticity_module import"
    "from chapter_summarizer import" = "from .chapter_summarizer import"
    "from deepseek_integration import" = "from .deepseek_integration import"
    "from outline_expander import" = "from .outline_expander import"
    "from novel_agent import" = "from .novel_agent import"
    "from aliyun_embeddings import" = "from .aliyun_embeddings import"
    "from multi_agent_framework import" = "from .multi_agent_framework import"
}

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw -Encoding UTF8
    $modified = $false
    
    foreach ($key in $replacements.Keys) {
        if ($content -match [regex]::Escape($key)) {
            $content = $content -replace [regex]::Escape($key), $replacements[$key]
            $modified = $true
        }
    }
    
    if ($modified) {
        Set-Content -Path $file.FullName -Value $content -Encoding UTF8 -NoNewline
        Write-Host "Updated: $($file.Name)" -ForegroundColor Green
    }
}

Write-Host "`nImport update complete!" -ForegroundColor Cyan

