<#
.SYNOPSIS
    Converte uma familia JA EXISTENTE pela Rota A: leitor (origem) -> construtor (destino) -> validador.

.DESCRIPTION
    Serve para o teste de ida e volta da geracao: uma familia gerada no 2024 e
    lida pelo leitor e reconstruida no 2023, com a regua do validador do
    conversor. Mesmas regras do run_fase0.ps1: saida apagada antes e conferida
    depois, porque o `pyrevit run` devolve exit 0 mesmo quando quebra.

.EXAMPLE
    .\run_ida_e_volta.ps1 -Entrada ..\out\gerador\PLAB_MOB_Mesa_Redonda\2024\PLAB_MOB_Mesa_Redonda.rfa -Origem 2024 -Destino 2023
#>
param(
    [Parameter(Mandatory = $true)][string]$Entrada,
    [int]$Origem = 2024,
    [int]$Destino = 2023,
    [string]$Pyrevit = "C:\Program Files\pyRevit CLI\bin\pyrevit.exe"
)

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
$Entrada = (Resolve-Path $Entrada).Path
$nome = [IO.Path]::GetFileNameWithoutExtension($Entrada)
$Saida = Join-Path $Raiz "out\ida_e_volta\$nome\$Origem-$Destino"
New-Item -ItemType Directory -Force -Path $Saida | Out-Null
$Portadora = Join-Path $Raiz "out\portadora.rfa"

$spec = Join-Path $Saida "familyspec.json"
$rfa = Join-Path $Saida "$nome.rfa"
$fidelidade = Join-Path $Saida "fidelidade.json"
$flex = Join-Path $Saida "flex.json"
foreach ($f in $spec, $rfa, $fidelidade, $flex) { if (Test-Path $f) { Remove-Item $f -Force } }

$template = Get-ChildItem "C:\ProgramData\Autodesk\RVT $Destino\Family Templates" -Recurse -Filter "*.rft" |
    Where-Object { $_.Name -match "^Metric[ _]Generic[ _]Model(-ENU)?\.rft$" } | Select-Object -First 1
if (-not $template) { throw "template Generic Model do $Destino nao encontrado" }

$env:RFADG_ROOT = $Raiz
function Etapa([string]$script, [int]$ano, [string]$espera) {
    & $Pyrevit run (Join-Path $PSScriptRoot $script) $Portadora --revit=$ano 2>&1 |
        Out-File (Join-Path $Saida "$script.log") -Encoding utf8
    if (-not (Test-Path $espera)) { throw "$script nao gerou $espera (ver $script.log)" }
}

$env:RFADG_ENTRADA = $Entrada; $env:RFADG_SPEC = $spec
Etapa "leitor.py" $Origem $spec
$env:RFADG_SAIDA = $rfa; $env:RFADG_TEMPLATE = $template.FullName; $env:RFADG_RELATORIO = $fidelidade
Etapa "construtor.py" $Destino $rfa
$env:RFADG_ENTRADA = $rfa; $env:RFADG_RELATORIO_FLEX = $flex
Etapa "validador.py" $Destino $flex
Write-Host "Ida e volta: $Saida" -ForegroundColor Green
