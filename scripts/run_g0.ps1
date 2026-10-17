<#
.SYNOPSIS
    Roda as sondas da G0 (docs/SPEC-geracao-familias.md §10) numa versao do Revit.

.DESCRIPTION
    Mesmas regras do run_fase0.ps1: portadora para dar boot no CLI, insumos por
    variavel de ambiente, e a saida e APAGADA antes e conferida depois, porque o
    `pyrevit run` devolve exit 0 mesmo quando o script quebra (CLAUDE.md §7, 4b).
    Sem --purge, para o traceback ficar no log.

.EXAMPLE
    .\run_g0.ps1 -Revit 2022
#>
param(
    [int]$Revit = 2022,
    [string]$Portadora = ""
)

$ErrorActionPreference = "Stop"

$Raiz = Split-Path -Parent $PSScriptRoot
$Saida = Join-Path $Raiz "out\g0\$Revit"

function Resolve-TemplateGenericModel {
    param([int]$Ano)
    $raizTemplates = "C:\ProgramData\Autodesk\RVT $Ano\Family Templates"
    if (-not (Test-Path $raizTemplates)) {
        throw "Family Templates nao encontrado para Revit ${Ano}: $raizTemplates"
    }
    $indesejados = @("adaptive", "based", "pattern", "two level")
    $candidatos = Get-ChildItem -Path $raizTemplates -Filter "*.rft" -Recurse -File |
        Where-Object {
            $nome = $_.Name.ToLower().Replace("_", " ")
            if ($nome -notlike "*generic model*") { return $false }
            foreach ($ruim in $indesejados) { if ($nome -like "*$ruim*") { return $false } }
            return $true
        } |
        Sort-Object @{
            Expression = {
                $completo = $_.FullName.ToLower()
                if ($completo -like "*-enu*") { 0 }
                elseif ($completo -like "*\english\*") { 1 }
                else { 2 }
            }
        }, Name
    if (-not $candidatos) { throw "Nenhum template Generic Model em $raizTemplates" }
    return $candidatos[0].FullName
}

if (-not $Portadora) { $Portadora = Join-Path $Raiz "out\portadora.rfa" }
if (-not (Test-Path $Portadora)) { throw "Portadora nao encontrada: $Portadora" }

New-Item -ItemType Directory -Force -Path $Saida | Out-Null
$resultado = Join-Path $Saida "resultado.json"
if (Test-Path $resultado) { Remove-Item $resultado -Force }

$env:RFADG_ROOT = $Raiz
$env:RFADG_TEMPLATE = Resolve-TemplateGenericModel -Ano $Revit
$env:RFADG_G0_SAIDA = $Saida

Write-Host "=== G0 sondas (Revit $Revit) ===" -ForegroundColor Cyan
Write-Host "    template: $env:RFADG_TEMPLATE" -ForegroundColor DarkGray
# Tee para arquivo: o throw abaixo interromperia o pipeline e o log sumiria da tela.
pyrevit run (Join-Path $PSScriptRoot "g0_sondas.py") $Portadora --revit=$Revit 2>&1 |
    Tee-Object -FilePath (Join-Path $Saida "pyrevit.log")

if (-not (Test-Path $resultado)) {
    throw "G0 nao gerou $resultado - ver o traceback no bloco 'Execution Log' acima."
}
Write-Host "Resultado: $resultado" -ForegroundColor Green
