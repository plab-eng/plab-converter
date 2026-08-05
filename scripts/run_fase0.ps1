<#
.SYNOPSIS
    Orquestra o ciclo da Fase 0: fixture -> leitor -> construtor -> validador.

.DESCRIPTION
    Cada etapa roda dentro de uma instancia do Revit via `pyrevit run`.

    Tres restricoes do CLI moldam este desenho:

    1. `pyrevit run` SEMPRE exige um arquivo de modelo. A forma sem modelo
       documentada no --help falha com "Model does not exist at ''".
    2. Ele valida a versao do modelo e RECUSA .rft ("Can not detect the Revit
       version of model"). Entao passamos uma familia da biblioteca do Revit
       como PORTADORA — ela existe so para satisfazer o CLI e e ignorada pelo
       script, que cria seu proprio documento.
    3. Os scripts nao recebem argv. A comunicacao e por variavel de ambiente,
       herdada pelo processo do Revit.

    Por isso o orquestrador PREPARA OS INSUMOS: resolve o template .rft da
    versao alvo e passa o caminho em RFADG_TEMPLATE.

    Isso espelha o desenho de producao: no Design Automation o .rft tambem e
    um input do workitem, nao algo que o plugin sai procurando no disco.

.EXAMPLE
    .\run_fase0.ps1
    .\run_fase0.ps1 -Etapa fixture
    .\run_fase0.ps1 -RevitOrigem 2025 -RevitDestino 2024
#>
param(
    [ValidateSet("tudo", "fixture", "leitor", "construtor", "validador")]
    [string]$Etapa = "tudo",

    [int]$RevitOrigem = 2025,
    [int]$RevitDestino = 2023,

    # Familia "portadora" — ver Get-Portadora. Precisa ser um .rfa salvo
    # normalmente por um Revit de versao <= $RevitDestino.
    [string]$Portadora = ""
)

$ErrorActionPreference = "Stop"

$Raiz = Split-Path -Parent $PSScriptRoot
$Saida = Join-Path $Raiz "out"

if (-not (Test-Path $Saida)) { New-Item -ItemType Directory -Path $Saida | Out-Null }

function Resolve-TemplateGenericModel {
    <#
        Encontra o template Generic Model de uma versao do Revit.

        O layout muda entre versoes: 2023 poe Metric_Generic_Model-ENU.rft na
        raiz; 2024/2025 usam subpastas por idioma com nomes espacados. Por isso
        a busca e recursiva e por padrao de nome, nunca por caminho fixo.
    #>
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
            foreach ($ruim in $indesejados) {
                if ($nome -like "*$ruim*") { return $false }
            }
            return $true
        } |
        Sort-Object @{
            # Menor pontuacao ganha: prefere variante em ingles.
            Expression = {
                $completo = $_.FullName.ToLower()
                if ($completo -like "*-enu*") { 0 }
                elseif ($completo -like "*\english\*") { 1 }
                else { 2 }
            }
        }, Name

    if (-not $candidatos) {
        throw "Nenhum template Generic Model encontrado em $raizTemplates"
    }

    return $candidatos[0].FullName
}

$env:RFADG_ROOT      = $Raiz
$env:RFADG_FIXTURE   = Join-Path $Saida "fixture_origem.rfa"
$env:RFADG_SPEC      = Join-Path $Saida "familyspec.json"
$env:RFADG_SAIDA     = Join-Path $Saida "familia_convertida.rfa"
$env:RFADG_RELATORIO = Join-Path $Saida "relatorio_fidelidade.json"
$env:RFADG_RELATORIO_FLEX = Join-Path $Saida "relatorio_flex.json"
$env:RFADG_ORIGEM_VERSAO  = $RevitOrigem
$env:RFADG_DESTINO_VERSAO = $RevitDestino

function Invoke-Etapa {
    param([string]$Script, [int]$Revit, [string]$Modelo, [string]$Rotulo)

    Write-Host ""
    Write-Host "=== $Rotulo (Revit $Revit) ===" -ForegroundColor Cyan

    $caminho = Join-Path $PSScriptRoot $Script
    if (-not (Test-Path $caminho)) { throw "Script nao encontrado: $caminho" }
    if (-not (Test-Path $Modelo))  { throw "Modelo de entrada nao existe: $Modelo" }

    Write-Host "    modelo: $Modelo" -ForegroundColor DarkGray
    pyrevit run $caminho $Modelo --revit=$Revit --purge

    if ($LASTEXITCODE -ne 0) { throw "$Rotulo falhou (exit $LASTEXITCODE)" }
}

function Get-Portadora {
    <#
        Familia usada SO para dar boot no Revit e satisfazer a exigencia de
        modelo do CLI. Nenhum script trabalha sobre ela — cada um abre ou cria
        o documento de que precisa.

        Precisa ser um .rfa salvo normalmente pelo Revit, de versao <= a mais
        antiga que o ciclo usa. Nao servem:
          - .rft (o CLI recusa)
          - familias da biblioteca do Revit (BasicFileInfo sem o campo de build)
          - .rfa gerado por Document.SaveAs da API (mesmo problema)
        Em todos esses casos o erro e "Can not detect the Revit version of
        model", que e enganoso: o arquivo esta intacto, o parser do CLI e que
        nao o reconhece.
    #>
    if ($Portadora) {
        if (-not (Test-Path $Portadora)) { throw "Portadora nao encontrada: $Portadora" }
        return $Portadora
    }

    $padrao = Join-Path $Saida "portadora.rfa"
    if (Test-Path $padrao) { return $padrao }

    throw @"
Portadora nao configurada. Copie para $padrao uma familia .rfa qualquer,
salva pelo Revit $RevitDestino ou anterior, ou passe -Portadora <caminho>.
"@
}

function Set-Template {
    <# Resolve e publica o template da versao alvo para o script dentro do Revit. #>
    param([int]$Ano)

    $template = Resolve-TemplateGenericModel -Ano $Ano
    $env:RFADG_TEMPLATE = $template
    Write-Host "    template Revit ${Ano}: $template" -ForegroundColor DarkGray
}

$portadora = Get-Portadora

if ($Etapa -in @("tudo", "fixture")) {
    Set-Template -Ano $RevitOrigem
    Invoke-Etapa -Script "criar_fixture.py" -Revit $RevitOrigem -Modelo $portadora -Rotulo "Fixture"
    if (-not (Test-Path $env:RFADG_FIXTURE)) { throw "Fixture nao foi gerada." }
}

if ($Etapa -in @("tudo", "leitor")) {
    $env:RFADG_ENTRADA = $env:RFADG_FIXTURE
    Invoke-Etapa -Script "leitor.py" -Revit $RevitOrigem -Modelo $portadora -Rotulo "Leitor"
    if (-not (Test-Path $env:RFADG_SPEC)) { throw "FamilySpec nao foi gerado." }
}

if ($Etapa -in @("tudo", "construtor")) {
    Set-Template -Ano $RevitDestino
    Invoke-Etapa -Script "construtor.py" -Revit $RevitDestino -Modelo $portadora -Rotulo "Construtor"
    if (-not (Test-Path $env:RFADG_SAIDA)) { throw "Familia convertida nao foi gerada." }
}

if ($Etapa -in @("tudo", "validador")) {
    $env:RFADG_ENTRADA = $env:RFADG_SAIDA
    Invoke-Etapa -Script "validador.py" -Revit $RevitDestino -Modelo $portadora -Rotulo "Validador"
}

Write-Host ""
Write-Host "Artefatos em $Saida" -ForegroundColor Green
Get-ChildItem $Saida | Format-Table Name, Length, LastWriteTime
