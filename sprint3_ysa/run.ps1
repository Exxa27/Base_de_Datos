<#
.SYNOPSIS
    Orquesta el proyecto "la_penal": dependencias, datos sintéticos, PostgreSQL y MongoDB.

.DESCRIPTION
    Requiere en el PATH: python (o py), psql, mongosh y mongoimport.
    PostgreSQL: usuario postgres, sin contraseña, localhost:5432.
    MongoDB: sin autenticación, localhost:27017.
    La base de datos se llama "la_penal" en ambos motores.

.EXAMPLE
    .\run.ps1                    # todo el proceso, de principio a fin
    .\run.ps1 -Paso generar      # solo regenera DML.sql y los seeds de Mongo
    .\run.ps1 -Paso postgres     # solo carga DDL.sql, DML.sql y DQL.sql
    .\run.ps1 -Paso mongo        # solo crea colecciones e importa los seeds
    .\run.ps1 -Paso verificar    # solo comprueba lo cargado
#>
param(
    [ValidateSet("todo", "dependencias", "generar", "postgres", "mongo", "verificar")]
    [string]$Paso = "todo"
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------
$BaseDatos = "la_penal"
$PgUsuario = "postgres"
$PgHost    = "localhost"
$PgPuerto  = 5432
$MongoUri  = "mongodb://localhost:27017"

$DirPg    = Join-Path $PSScriptRoot "PostgreSQL_relacional"
$DirMongo = Join-Path $PSScriptRoot "Mongo_noRelacional"

$env:PGCLIENTENCODING = "UTF8"
$env:PYTHONUTF8       = "1"
$env:PGOPTIONS        = "-c client_min_messages=warning"   # oculta los NOTICE de DROP ... IF EXISTS

# -w: nunca pide contraseña (falla en lugar de quedarse esperando)
$PsqlBase = @("-U", $PgUsuario, "-h", $PgHost, "-p", "$PgPuerto", "-w", "-q", "-v", "ON_ERROR_STOP=1")

# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
function Write-Titulo([string]$texto) {
    Write-Host ""
    Write-Host "== $texto ==" -ForegroundColor Cyan
}

# Carpetas habituales de instalación en Windows: se buscan si el comando no está en el PATH
$DirectoriosHerramientas = @{
    "psql"        = @("$env:C:\Users\ochoa\AppData\Local\com.tinyapp.DBngin\Binaries\postgresql\16.4.1\bin", "${env:ProgramFiles(x86)}\PostgreSQL\*\bin")
    "mongosh"     = @("$env:LOCALAPPDATA\Programs\mongosh", "$env:ProgramFiles\mongosh",
                      "$env:ProgramFiles\MongoDB\Server\*\bin")
    "mongoimport" = @("$env:C:\Users\ochoa\Downloads\mongodb-database-tools-windows-x86_64-100.20.1\bin", "$env:ProgramFiles\MongoDB\Server\*\bin")
}

function Assert-Comando([string]$comando) {
    if (Get-Command $comando -ErrorAction SilentlyContinue) { return }

    $encontrados = @()
    foreach ($patron in $DirectoriosHerramientas[$comando]) {
        $encontrados += @(Get-ChildItem -Path (Join-Path $patron "$comando.exe") -ErrorAction SilentlyContinue)
    }
    $exe = $encontrados | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($exe) {
        # Solo para esta ejecución: no modifica el PATH del sistema
        $env:Path = "$($exe.DirectoryName);$env:Path"
        Write-Host "'$comando' no estaba en el PATH; se usará $($exe.FullName)" -ForegroundColor Yellow
        return
    }

    throw ("No se encontró '$comando' en el PATH ni en las carpetas habituales de instalación. " +
           'Agrega su carpeta "bin" al PATH de esta sesión, por ejemplo: ' +
           '$env:Path += ";C:\Program Files\PostgreSQL\16\bin"')
}

function Get-Python {
    foreach ($candidato in @("python", "py")) {
        if (Get-Command $candidato -ErrorAction SilentlyContinue) { return $candidato }
    }
    throw "No se encontró Python (python o py) en el PATH."
}

# Ejecuta un comando nativo y falla si su código de salida no es 0
function Invoke-Comando([string]$mensaje, [scriptblock]$bloque) {
    & $bloque
    if ($LASTEXITCODE -ne 0) { throw "$mensaje (código de salida $LASTEXITCODE)" }
}

function Invoke-Psql {
    & psql @PsqlBase @args
}

function Get-Escalar([string]$valor) {
    return "$valor".Trim()
}

# ---------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------
function Invoke-Dependencias {
    Write-Titulo "Dependencias de Python (faker, bcrypt)"
    $py = Get-Python
    Invoke-Comando "No se pudieron instalar faker y bcrypt" { & $py -m pip install --quiet faker bcrypt }
    Write-Host "Listo." -ForegroundColor Green
}

function Invoke-Generar {
    Write-Titulo "Generando datos sintéticos con Faker"
    $py = Get-Python
    Invoke-Comando "El seeder falló" { & $py (Join-Path $DirPg "seeder.py") }
}

function Invoke-Postgres {
    Assert-Comando "psql"
    Write-Titulo "PostgreSQL ($BaseDatos)"

    foreach ($archivo in @("DDL.sql", "DML.sql", "DQL.sql")) {
        if (-not (Test-Path -LiteralPath (Join-Path $DirPg $archivo))) {
            throw "Falta $archivo. Ejecuta primero: .\run.ps1 -Paso generar"
        }
    }

    $existe = Get-Escalar (Invoke-Psql -d postgres -t -A -c "SELECT 1 FROM pg_database WHERE datname = '$BaseDatos'")
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo conectar a PostgreSQL (usuario $PgUsuario, $PgHost`:$PgPuerto). Si pide contraseña, define `$env:PGPASSWORD."
    }
    if (-not $existe) {
        Write-Host "Creando la base de datos $BaseDatos..."
        Invoke-Psql -d postgres -c "CREATE DATABASE $BaseDatos ENCODING 'UTF8' TEMPLATE template0"
        if ($LASTEXITCODE -ne 0) {
            # La configuración regional de Windows puede impedir forzar UTF8: se crea con los valores por defecto
            Invoke-Psql -d postgres -c "CREATE DATABASE $BaseDatos"
            if ($LASTEXITCODE -ne 0) { throw "No se pudo crear la base de datos $BaseDatos" }
        }
    }

    Write-Host "Aplicando DDL.sql (esquema)..."
    Invoke-Comando "Falló DDL.sql" { Invoke-Psql -d $BaseDatos -f (Join-Path $DirPg "DDL.sql") }

    Write-Host "Aplicando DML.sql (datos)..."
    Invoke-Comando "Falló DML.sql" { Invoke-Psql -d $BaseDatos -f (Join-Path $DirPg "DML.sql") | Out-Null }

    Write-Host "Aplicando DQL.sql (vistas y reportes)..."
    $salidaDql = Join-Path $DirPg "DQL_resultados.txt"
    Invoke-Comando "Falló DQL.sql" { Invoke-Psql -d $BaseDatos -o $salidaDql -f (Join-Path $DirPg "DQL.sql") }
    Write-Host "Resultados de los reportes: $salidaDql"
    Write-Host "PostgreSQL listo." -ForegroundColor Green
}

function Invoke-Mongo {
    Assert-Comando "mongosh"
    Assert-Comando "mongoimport"
    Write-Titulo "MongoDB ($BaseDatos)"

    $seeds = Join-Path $DirMongo "seeds"
    $archivos = @()
    if (Test-Path -LiteralPath $seeds) { $archivos = @(Get-ChildItem -LiteralPath $seeds -Filter "*.json") }
    if ($archivos.Count -eq 0) { throw "No hay seeds en $seeds. Ejecuta primero: .\run.ps1 -Paso generar" }

    Write-Host "Creando colecciones, validadores e índices..."
    Invoke-Comando "Falló Desacople_aMongo.js" {
        mongosh $MongoUri --quiet --file (Join-Path $DirMongo "Desacople_aMongo.js")
    }

    Write-Host "Importando documentos..."
    foreach ($archivo in $archivos) {
        $coleccion = $archivo.BaseName
        # Sin --drop: así se conservan los validadores e índices creados arriba
        Invoke-Comando "Falló la importación de $coleccion" {
            mongoimport --uri "$MongoUri/$BaseDatos" --collection $coleccion --file $archivo.FullName --jsonArray --quiet
        }
        Write-Host ("  {0}" -f $coleccion)
    }
    Write-Host "MongoDB listo." -ForegroundColor Green
}

function Invoke-Verificar {
    Assert-Comando "psql"
    Assert-Comando "mongosh"
    Write-Titulo "Verificación"

    $conteoTablas = "SELECT table_name AS tabla, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I', table_name), false, true, '')))[1]::text::int AS filas FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
    Write-Host "Tablas de PostgreSQL:" -ForegroundColor Yellow
    Invoke-Comando "No se pudo consultar PostgreSQL" { Invoke-Psql -d $BaseDatos -c $conteoTablas }

    Write-Host "Colecciones de MongoDB:" -ForegroundColor Yellow
    $conteoColecciones = "db.getCollectionNames().sort().forEach(c => print(c.padEnd(24) + db.getCollection(c).countDocuments()))"
    Invoke-Comando "No se pudo consultar MongoDB" { mongosh "$MongoUri/$BaseDatos" --quiet --eval $conteoColecciones }

    $tablas   = [int](Get-Escalar (Invoke-Psql -d $BaseDatos -t -A -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"))
    $vistas   = [int](Get-Escalar (Invoke-Psql -d $BaseDatos -t -A -c "SELECT count(*) FROM information_schema.views WHERE table_schema = 'public'"))
    $colecs   = [int](Get-Escalar (mongosh "$MongoUri/$BaseDatos" --quiet --eval "db.getCollectionNames().length"))
    $total    = $tablas + $colecs

    Write-Host ""
    Write-Host "Tablas: $tablas | Colecciones: $colecs | Total: $total | Vistas SQL: $vistas"
    if ($total -lt 30) { throw "Se requieren al menos 30 entre tablas y colecciones (hay $total)" }
    if ($vistas -lt 3) { throw "Se requieren al menos 3 vistas SQL (hay $vistas)" }

    # Coherencia entre motores: Mongo solo referencia reclusos que existen en PostgreSQL
    $reclusos  = [int](Get-Escalar (Invoke-Psql -d $BaseDatos -t -A -c "SELECT count(*) FROM recluso"))
    $maxPg     = [int](Get-Escalar (Invoke-Psql -d $BaseDatos -t -A -c "SELECT max(id_recluso) FROM recluso"))
    $antec     = [int](Get-Escalar (mongosh "$MongoUri/$BaseDatos" --quiet --eval "db.antecedentes.countDocuments()"))
    $jsMax     = "let m = 0; ['sentencias','antecedentes','bitacoras','traslados','contactos_emergencia'].forEach(c => { const d = db.getCollection(c).find().sort({id_recluso: -1}).limit(1).toArray()[0]; if (d && d.id_recluso > m) m = d.id_recluso }); const x = db.incidentes.find().sort({'castigos.id_recluso': -1}).limit(1).toArray()[0]; if (x) m = Math.max(m, ...x.castigos.map(y => y.id_recluso)); print(m)"
    $maxMongo  = [int](Get-Escalar (mongosh "$MongoUri/$BaseDatos" --quiet --eval $jsMax))

    if ($reclusos -ne $antec) { throw "Reclusos en PostgreSQL ($reclusos) no coincide con antecedentes en Mongo ($antec)" }
    if ($maxMongo -gt $maxPg) { throw "Mongo referencia un id_recluso ($maxMongo) que no existe en PostgreSQL (máx. $maxPg)" }
    Write-Host "Coherencia entre motores: OK ($reclusos reclusos; id_recluso máximo en Mongo $maxMongo <= $maxPg en PostgreSQL)" -ForegroundColor Green
    Write-Host ""
    Write-Host "Usuarios de prueba: administrador, director, medico, custodio... / contraseña: Prueba123!"
}

# ---------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------
try {
    switch ($Paso) {
        "dependencias" { Invoke-Dependencias }
        "generar"      { Invoke-Generar }
        "postgres"     { Invoke-Postgres }
        "mongo"        { Invoke-Mongo }
        "verificar"    { Invoke-Verificar }
        "todo" {
            Invoke-Dependencias
            Invoke-Generar
            Invoke-Postgres
            Invoke-Mongo
            Invoke-Verificar
        }
    }
    Write-Host ""
    Write-Host "Terminado." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
