#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seeder.py  |  Sistema penitenciario  |  Generador de datos sintéticos (Faker)

Genera:
  - DML.sql    -> datos para las tablas de PostgreSQL (ver DDL.sql)
  - seeds.json -> datos para las colecciones de MongoDB (ver Desacople_aMongo.js)

Uso:
  pip install faker bcrypt
  python seeder.py --salida .

Los datos son reproducibles: la semilla es fija (SEMILLA).
Todos los usuarios de prueba comparten la contraseña CONTRASENA_PRUEBA,
pero cada uno tiene un hash bcrypt distinto (sal aleatoria por usuario).

Por defecto DML.sql se escribe junto a este script (PostgreSQL_relacional/) y seeds.json en
../Mongo_noRelacional/ (si existe). Con --salida DIR ambos van a la misma carpeta.
"""
import argparse
import json
import os
import random
import unicodedata
import re
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from pathlib import Path

import bcrypt
from faker import Faker

# ---------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------
SEMILLA = 2026
CONTRASENA_PRUEBA = "Prueba123!"      # solo para pruebas locales
RONDAS_BCRYPT = 10                    # 10 = rápido para pruebas; 12 en producción
LOTE_INSERT = 500                     # filas por sentencia INSERT
TOTAL_USUARIOS = 130
MINIMO_CATALOGO = 15

REFERENCIA = datetime(2026, 11, 3, 12, 0, 0)   # "hoy" fijo para que los datos no cambien
HACE_3_ANIOS = REFERENCIA - timedelta(days=3 * 365)

fake = Faker("es_MX")
Faker.seed(SEMILLA)
random.seed(SEMILLA)

# ---------------------------------------------------------------------
# Registro de lo generado
# ---------------------------------------------------------------------
TABLAS = OrderedDict()        # nombre -> {"pk": columna SERIAL | None, "filas": [dict]}
COLECCIONES = OrderedDict()   # nombre -> [dict]

# Datos auxiliares que no se escriben tal cual en la base (apoyan la coherencia entre tablas)
RECLUSOS = []                 # un dict por recluso, con fechas de sentencia, perfil, etc.
EMPLEADOS = []                # un dict por empleado, con su rol y puesto
UBICACION = {}                # id_celda -> (sección, pabellón, número de celda)
NOMBRES_USUARIO = []          # nombre real de cada usuario (misma posición que la tabla usuario)

# Orden de carga en PostgreSQL (respeta las llaves foráneas)
ORDEN_CARGA = [
    "permiso", "rol", "rol_permiso", "usuario",
    "seccion", "pabellon", "celda", "recluso",
    "puesto", "turno", "empleado", "sala", "asignacion_trabajo",
    "diagnostico", "expediente", "consulta_medica", "examen", "receta",
    "parentesco", "domicilio", "visitante", "visita",
]

# (tabla, columna, tabla_referenciada, columna_referenciada)
LLAVES_FORANEAS = [
    ("usuario", "id_rol", "rol", "id_rol"),
    ("rol_permiso", "id_rol", "rol", "id_rol"),
    ("rol_permiso", "id_permiso", "permiso", "id_permiso"),
    ("pabellon", "id_seccion", "seccion", "id_seccion"),
    ("celda", "id_pabellon", "pabellon", "id_pabellon"),
    ("recluso", "id_celda", "celda", "id_celda"),
    ("empleado", "id_usuario", "usuario", "id_usuario"),
    ("asignacion_trabajo", "id_empleado", "empleado", "id_empleado"),
    ("asignacion_trabajo", "id_puesto", "puesto", "id_puesto"),
    ("asignacion_trabajo", "id_turno", "turno", "id_turno"),
    ("asignacion_trabajo", "id_seccion", "seccion", "id_seccion"),
    ("asignacion_trabajo", "id_sala", "sala", "id_sala"),
    ("asignacion_trabajo", "id_recluso", "recluso", "id_recluso"),
    ("expediente", "id_recluso", "recluso", "id_recluso"),
    ("consulta_medica", "id_recluso", "recluso", "id_recluso"),
    ("consulta_medica", "id_empleado", "empleado", "id_empleado"),
    ("consulta_medica", "id_expediente", "expediente", "id_expediente"),
    ("consulta_medica", "id_sala", "sala", "id_sala"),
    ("consulta_medica", "id_diagnostico", "diagnostico", "id_diagnostico"),
    ("examen", "id_consulta", "consulta_medica", "id_consulta"),
    ("examen", "id_diagnostico", "diagnostico", "id_diagnostico"),
    ("receta", "id_consulta", "consulta_medica", "id_consulta"),
    ("visitante", "id_domicilio", "domicilio", "id_domicilio"),
    ("visita", "id_recluso", "recluso", "id_recluso"),
    ("visita", "id_visitante", "visitante", "id_visitante"),
    ("visita", "id_parentesco", "parentesco", "id_parentesco"),
]

CATALOGOS_MINIMO_15 = [
    "permiso", "rol", "puesto", "turno", "seccion", "pabellon", "sala",
    "parentesco", "diagnostico",
]


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------
def construir(pk, filas):
    """Asigna ids consecutivos (1..n) a una lista de diccionarios."""
    return [{pk: i, **fila} for i, fila in enumerate(filas, start=1)]


def registrar_tabla(nombre, pk, filas):
    """Guarda las filas de una tabla. pk=None si no tiene SERIAL (tabla puente)."""
    TABLAS[nombre] = {"pk": pk, "filas": filas}
    return filas


def slug(texto):
    """'María Pérez' -> 'maria_perez'."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_")


def datetime_aleatorio(desde, hasta):
    segundos = int((hasta - desde).total_seconds())
    return desde + timedelta(seconds=random.randint(0, segundos))


def fecha_aleatoria(desde, hasta):
    return (datetime.combine(desde, time()) +
            timedelta(days=random.randint(0, (hasta - desde).days))).date()


def hash_bcrypt(contrasena):
    sal = bcrypt.gensalt(rounds=RONDAS_BCRYPT)       # sal aleatoria: hash distinto cada vez
    return bcrypt.hashpw(contrasena.encode("utf-8"), sal).decode("utf-8")


# ---------------------------------------------------------------------
# Datos base de los catálogos
# ---------------------------------------------------------------------
PERMISOS = [
    ("ver_reclusos", "Consultar la información de los reclusos"),
    ("registrar_reclusos", "Dar de alta nuevos reclusos"),
    ("editar_reclusos", "Modificar los datos de los reclusos"),
    ("ver_celdas", "Consultar celdas, pabellones y secciones"),
    ("asignar_celdas", "Asignar o cambiar la celda de un recluso"),
    ("ver_visitas", "Consultar el registro de visitas"),
    ("registrar_visitas", "Registrar entradas y salidas de visitas"),
    ("autorizar_visitas", "Autorizar o negar visitas"),
    ("ver_expedientes_medicos", "Consultar expedientes médicos"),
    ("editar_expedientes_medicos", "Modificar expedientes médicos"),
    ("registrar_consultas", "Registrar consultas médicas"),
    ("recetar_medicamentos", "Emitir recetas médicas"),
    ("ver_incidentes", "Consultar incidentes y sanciones"),
    ("registrar_incidentes", "Registrar incidentes"),
    ("aplicar_sanciones", "Asignar castigos y sanciones"),
    ("ver_empleados", "Consultar la información del personal"),
    ("administrar_empleados", "Alta, baja y asignación de personal"),
    ("administrar_usuarios", "Gestionar usuarios, roles y permisos"),
    ("ver_reportes", "Consultar reportes y estadísticas"),
    ("auditar_sistema", "Revisar bitácoras y accesos del sistema"),
]

_TODOS = [p for p, _ in PERMISOS]
_VER = [p for p in _TODOS if p.startswith("ver_")]

# rol -> (descripción, permisos)
ROLES = OrderedDict([
    ("administrador", ("Control total del sistema", _TODOS)),
    ("director", ("Dirección general del centro", _VER + ["auditar_sistema"])),
    ("subdirector", ("Subdirección operativa", _VER + ["aplicar_sanciones", "asignar_celdas"])),
    ("jefe_custodios", ("Jefatura del cuerpo de custodios",
                        ["ver_reclusos", "ver_celdas", "asignar_celdas", "ver_visitas", "ver_empleados",
                         "ver_incidentes", "registrar_incidentes", "aplicar_sanciones"])),
    ("custodio", ("Vigilancia y custodia de reclusos",
                  ["ver_reclusos", "ver_celdas", "ver_visitas", "ver_incidentes", "registrar_incidentes"])),
    ("medico", ("Atención médica a reclusos",
                ["ver_reclusos", "ver_expedientes_medicos", "editar_expedientes_medicos",
                 "registrar_consultas", "recetar_medicamentos"])),
    ("enfermero", ("Apoyo en el área médica",
                   ["ver_reclusos", "ver_expedientes_medicos", "registrar_consultas"])),
    ("psicologo", ("Atención psicológica",
                   ["ver_reclusos", "ver_expedientes_medicos", "registrar_consultas"])),
    ("trabajador_social", ("Seguimiento social y familiar",
                           ["ver_reclusos", "ver_visitas", "autorizar_visitas", "ver_incidentes"])),
    ("abogado", ("Asesoría jurídica de oficio", ["ver_reclusos", "ver_incidentes"])),
    ("recepcionista_visitas", ("Control de acceso de visitantes",
                               ["ver_reclusos", "ver_visitas", "registrar_visitas"])),
    ("archivista", ("Gestión de expedientes y registros",
                    ["ver_reclusos", "registrar_reclusos", "editar_reclusos", "ver_empleados"])),
    ("auditor", ("Auditoría y control interno", _VER + ["auditar_sistema"])),
    ("recursos_humanos", ("Administración del personal", ["ver_empleados", "administrar_empleados"])),
    ("soporte_ti", ("Soporte técnico del sistema", ["administrar_usuarios", "ver_reportes"])),
])

# Probabilidad de cada rol al generar usuarios no de prueba
PESOS_ROL = {
    "administrador": 2, "director": 1, "subdirector": 2, "jefe_custodios": 6, "custodio": 45,
    "medico": 8, "enfermero": 10, "psicologo": 5, "trabajador_social": 5, "abogado": 3,
    "recepcionista_visitas": 6, "archivista": 3, "auditor": 2, "recursos_humanos": 3, "soporte_ti": 2,
}

SECCIONES = [
    "Máxima seguridad", "Mediana seguridad", "Mínima seguridad", "Femenil", "Procesados",
    "Sentenciados", "Aislamiento", "Enfermería", "Ingreso", "Observación", "Población vulnerable",
    "Adultos mayores", "Psiquiatría", "Cumplimiento especial", "Preliberación",
]
PABELLONES_POR_SECCION = 2
CELDAS_POR_PABELLON = 12

PUESTOS = [
    "Director", "Subdirector", "Jefe de custodios", "Custodio", "Médico general", "Enfermero",
    "Psicólogo", "Trabajador social", "Abogado de oficio", "Recepcionista de visitas", "Archivista",
    "Administrativo", "Cocinero", "Personal de limpieza", "Mantenimiento", "Conductor",
    "Operador de cámaras", "Instructor de taller",
]

_BLOQUES = [("Matutino", time(6, 0), time(14, 0)),
            ("Vespertino", time(14, 0), time(22, 0)),
            ("Nocturno", time(22, 0), time(6, 0))]
_PATRONES = [("L-V", "Lunes a viernes"), ("L-S", "Lunes a sábado"),
             ("Fines de semana", "Sábado y domingo"),
             ("Mixto A", "Lunes, miércoles y viernes"), ("Mixto B", "Martes, jueves y sábado")]

SALAS = [
    "Consultorio 1", "Consultorio 2", "Consultorio 3", "Consultorio 4", "Enfermería general",
    "Urgencias", "Rayos X", "Laboratorio", "Psicología", "Odontología", "Observación",
    "Curaciones", "Farmacia", "Aislamiento médico", "Rehabilitación", "Salud mental",
]

DIAGNOSTICOS = [
    "Hipertensión arterial", "Diabetes mellitus tipo 2", "Infección respiratoria aguda", "Gastritis",
    "Lumbalgia", "Migraña", "Asma bronquial", "Dermatitis", "Conjuntivitis", "Influenza estacional",
    "Hepatitis viral", "Tuberculosis pulmonar", "Trastorno de ansiedad", "Depresión", "Insomnio",
    "Contusión por golpe", "Fractura simple", "Caries dental", "Infección urinaria", "Deshidratación",
]

TIPOS_INCIDENTE = [
    ("Riña", "Pelea entre internos"),
    ("Posesión de objetos prohibidos", "Hallazgo de artículos no permitidos en celda"),
    ("Intento de fuga", "Intento de evadir la custodia"),
    ("Agresión a custodio", "Agresión física o verbal al personal"),
    ("Desobediencia", "Incumplimiento de órdenes del personal"),
    ("Daños a instalaciones", "Destrucción de bienes del centro"),
    ("Consumo de sustancias", "Consumo de sustancias no autorizadas"),
    ("Tráfico de objetos", "Introducción o intercambio de objetos prohibidos"),
    ("Motín", "Alteración grupal del orden"),
    ("Autolesión", "Lesión provocada por el propio interno"),
    ("Robo entre internos", "Sustracción de pertenencias de otro interno"),
    ("Amenazas", "Amenazas a internos o al personal"),
    ("Falta de respeto", "Conducta irrespetuosa hacia el personal"),
    ("Incumplimiento de horarios", "No respetar horarios de conteo o descanso"),
    ("Comunicación no autorizada", "Uso de medios de comunicación no permitidos"),
    ("Acoso", "Hostigamiento a otro interno"),
]

SANCIONES = [
    ("Amonestación verbal", "Llamada de atención verbal registrada"),
    ("Amonestación escrita", "Llamada de atención con acta"),
    ("Pérdida de visita 1 semana", "Suspensión de visitas por siete días"),
    ("Pérdida de visita 1 mes", "Suspensión de visitas por treinta días"),
    ("Aislamiento 3 días", "Aislamiento temporal por tres días"),
    ("Aislamiento 7 días", "Aislamiento temporal por siete días"),
    ("Aislamiento 15 días", "Aislamiento temporal por quince días"),
    ("Pérdida de trabajo", "Retiro de la actividad laboral asignada"),
    ("Restricción de llamadas", "Suspensión del derecho a llamadas"),
    ("Cambio de pabellón", "Reubicación disciplinaria"),
    ("Trabajo comunitario", "Servicio en áreas comunes del centro"),
    ("Restricción de patio", "Reducción del tiempo de patio"),
    ("Suspensión de beneficios", "Suspensión de beneficios de conducta"),
    ("Retiro de privilegios", "Retiro de privilegios de economato y recreación"),
    ("Traslado disciplinario", "Traslado a otra sección por conducta"),
]

PARENTESCOS = [
    "Padre", "Madre", "Hermano", "Hermana", "Hijo", "Hija", "Esposo", "Esposa", "Pareja",
    "Abuelo", "Abuela", "Tío", "Tía", "Primo", "Prima", "Amigo", "Abogado", "Vecino",
    "Compañero de trabajo",
]

# Catálogo de MongoDB: (tipo_delito, delito, descripcion_delito)
DELITOS = [
    ("Contra la vida", "Homicidio doloso", "Privar de la vida a otra persona con intención"),
    ("Contra la vida", "Lesiones graves", "Causar lesiones que ponen en peligro la vida"),
    ("Patrimonio", "Robo con violencia", "Apoderarse de bienes ajenos mediante violencia"),
    ("Patrimonio", "Robo a casa habitación", "Robo en un inmueble destinado a vivienda"),
    ("Patrimonio", "Robo de vehículo", "Apoderamiento de un vehículo ajeno"),
    ("Patrimonio", "Fraude", "Engaño para obtener un beneficio económico"),
    ("Patrimonio", "Abuso de confianza", "Disponer indebidamente de bienes confiados"),
    ("Patrimonio", "Daño a propiedad ajena", "Destrucción de bienes de otra persona"),
    ("Libertad", "Secuestro", "Privar de la libertad con fines de rescate"),
    ("Libertad", "Extorsión", "Obligar a otro a dar algo mediante amenazas"),
    ("Salud", "Narcomenudeo", "Venta o posesión de narcóticos en pequeñas cantidades"),
    ("Salud", "Tráfico de drogas", "Transporte o comercio de narcóticos"),
    ("Seguridad pública", "Portación ilegal de armas", "Portar armas sin autorización"),
    ("Seguridad pública", "Delincuencia organizada", "Asociación para cometer delitos de forma permanente"),
    ("Seguridad pública", "Evasión de presos", "Facilitar o realizar la fuga de un interno"),
    ("Económicos", "Lavado de dinero", "Ocultar el origen ilícito de recursos"),
    ("Familia", "Violencia familiar", "Maltrato físico o psicológico en el entorno familiar"),
    ("Domicilio", "Allanamiento de morada", "Ingresar a un domicilio sin permiso"),
    ("Servicio público", "Cohecho", "Ofrecer o recibir dádivas para alterar un servicio público"),
    ("Documentos", "Falsificación de documentos", "Alterar o fabricar documentos oficiales"),
]


# ---------------------------------------------------------------------
# Generación de catálogos
# ---------------------------------------------------------------------
def generar_catalogos():
    # --- Sistema: permisos, roles y su relación N:M
    permisos = construir("id_permiso", [{"permiso": p, "descripcion": d} for p, d in PERMISOS])
    registrar_tabla("permiso", "id_permiso", permisos)
    id_permiso = {p["permiso"]: p["id_permiso"] for p in permisos}

    roles = construir("id_rol", [{"rol": r, "descripcion": d} for r, (d, _) in ROLES.items()])
    registrar_tabla("rol", "id_rol", roles)
    id_rol = {r["rol"]: r["id_rol"] for r in roles}

    rol_permiso = [
        {"id_rol": id_rol[rol], "id_permiso": id_permiso[p]}
        for rol, (_, perms) in ROLES.items() for p in sorted(set(perms))
    ]
    registrar_tabla("rol_permiso", None, rol_permiso)

    # --- Infraestructura: secciones -> pabellones -> celdas
    secciones = construir("id_seccion", [{"seccion": s} for s in SECCIONES])
    registrar_tabla("seccion", "id_seccion", secciones)

    pabellones = construir("id_pabellon", [
        {"id_seccion": s["id_seccion"], "pabellon": f"Pabellón {n}"}
        for s in secciones for n in range(1, PABELLONES_POR_SECCION + 1)
    ])
    registrar_tabla("pabellon", "id_pabellon", pabellones)

    nombre_seccion = {s["id_seccion"]: s["seccion"] for s in secciones}
    celdas = []
    for pab in pabellones:
        seccion = nombre_seccion[pab["id_seccion"]]
        for numero in range(1, CELDAS_POR_PABELLON + 1):
            if seccion == "Aislamiento":
                tipo = "aislamiento"
            elif seccion == "Enfermería":
                tipo = "enfermeria"
            else:
                tipo = random.choices(["individual", "compartida"], weights=[40, 60])[0]
            celdas.append({"id_pabellon": pab["id_pabellon"], "numero_celda": numero, "tipo_celda": tipo})
    registrar_tabla("celda", "id_celda", construir("id_celda", celdas))

    # --- Trabajadores: puestos y turnos
    registrar_tabla("puesto", "id_puesto", construir("id_puesto", [{"puesto": p} for p in PUESTOS]))
    turnos = [
        {"turno": f"{nombre} {abrev}", "dias": dias, "hora_inicio": inicio, "hora_salida": fin}
        for nombre, inicio, fin in _BLOQUES for abrev, dias in _PATRONES
    ]
    registrar_tabla("turno", "id_turno", construir("id_turno", turnos))

    # --- Área médica: salas y diagnósticos
    salas = []
    for nombre in SALAS:
        camillas = random.randint(1, 12)
        salas.append({"nombre": nombre, "camillas": camillas, "ocupadas": random.randint(0, camillas)})
    registrar_tabla("sala", "id_sala", construir("id_sala", salas))
    registrar_tabla("diagnostico", "id_diagnostico",
                    construir("id_diagnostico", [{"diagnostico": d} for d in DIAGNOSTICOS]))

    # --- MongoDB: catálogos del módulo de sanciones
    COLECCIONES["tipos_incidente"] = construir(
        "id_tipo_incidente", [{"incidente": i, "descripcion": d} for i, d in TIPOS_INCIDENTE])
    COLECCIONES["sanciones"] = construir(
        "id_sancion", [{"sancion": s, "descripcion": d} for s, d in SANCIONES])

    # --- Visitas: parentescos
    registrar_tabla("parentesco", "id_parentesco",
                    construir("id_parentesco", [{"parentesco": p} for p in PARENTESCOS]))

    # --- MongoDB: catálogo de delitos
    COLECCIONES["delitos"] = construir("id_delito", [
        {"tipo_delito": t, "delito": d, "descripcion_delito": desc} for t, d, desc in DELITOS
    ])


# ---------------------------------------------------------------------
# Generación de usuarios (bcrypt)
# ---------------------------------------------------------------------
def generar_usuarios(total=TOTAL_USUARIOS):
    id_rol = {r["rol"]: r["id_rol"] for r in TABLAS["rol"]["filas"]}
    usados = set()
    usuarios = []
    NOMBRES_USUARIO.clear()

    # 1) Un usuario de prueba conocido por rol (usuario = nombre del rol)
    for rol in ROLES:
        usados.add(rol)
        NOMBRES_USUARIO.append(nombre_completo())
        usuarios.append({
            "id_rol": id_rol[rol],
            "nombre_usuario": rol,
            "contrasena_hash": hash_bcrypt(CONTRASENA_PRUEBA),
            "estatus": "activo",
            "fecha_registro": datetime_aleatorio(HACE_3_ANIOS, REFERENCIA - timedelta(days=700)),
        })

    # 2) Resto de usuarios con nombres generados por Faker
    roles = list(PESOS_ROL)
    pesos = [PESOS_ROL[r] for r in roles]
    while len(usuarios) < total:
        nombre_pila, apellido = fake.first_name(), fake.last_name()
        base = f"{slug(nombre_pila)}.{slug(apellido)}"
        nombre, n = base, 1
        while nombre in usados:
            n += 1
            nombre = f"{base}{n}"
        usados.add(nombre)
        NOMBRES_USUARIO.append(f"{nombre_pila} {apellido} {fake.last_name()}")
        usuarios.append({
            "id_rol": id_rol[random.choices(roles, weights=pesos)[0]],
            "nombre_usuario": nombre,
            "contrasena_hash": hash_bcrypt(CONTRASENA_PRUEBA),
            "estatus": random.choices(["activo", "inactivo", "bloqueado"], weights=[90, 7, 3])[0],
            "fecha_registro": datetime_aleatorio(HACE_3_ANIOS, REFERENCIA),
        })

    registrar_tabla("usuario", "id_usuario", construir("id_usuario", usuarios))


# ---------------------------------------------------------------------
# PASO 5 · Volúmenes, constantes y utilidades
# ---------------------------------------------------------------------
N_RECLUSOS = 600
PCT_FEMENIL = 0.06
PCT_NUEVOS = 0.06            # recién ingresados (ingreso < 30 días): aún sin bitácora
N_EXTRA_EMPLEADOS = 20       # personal sin acceso al sistema (cocina, limpieza...)
N_CONSULTAS = 800
N_DOMICILIOS = 300
N_VISITANTES = 400
N_VISITAS = 1500
N_TRASLADOS = 300
N_INCIDENTES = 700
N_INGRESOS = 2500
N_DECOMISOS = 250

HOY = REFERENCIA.date()
LADAS = ["55", "81", "33", "222", "664", "442", "614", "999", "844", "871"]
DIAS_VISITA = {2, 5, 6}      # weekday(): miércoles, sábado y domingo
EN_CUSTODIA = ("activo", "hospitalizado")
CAPACIDAD_CELDA = {"individual": 1, "compartida": 4, "aislamiento": 1, "enfermeria": 2}

DELITOS_GRAVES = {"Homicidio doloso", "Lesiones graves", "Secuestro",
                  "Delincuencia organizada", "Tráfico de drogas"}
PESO_DELITO = {
    "Robo con violencia": 12, "Narcomenudeo": 12, "Robo a casa habitación": 8, "Robo de vehículo": 7,
    "Fraude": 5, "Homicidio doloso": 4, "Secuestro": 2, "Delincuencia organizada": 2,
    "Tráfico de drogas": 3, "Lavado de dinero": 2, "Cohecho": 1, "Falsificación de documentos": 2,
    "Evasión de presos": 1,
}
SECCIONES_GRAVES = {"Máxima seguridad": 45, "Cumplimiento especial": 20, "Mediana seguridad": 25,
                    "Observación": 5, "Psiquiatría": 5}
SECCIONES_COMUNES = {"Mediana seguridad": 30, "Mínima seguridad": 22, "Sentenciados": 25,
                     "Población vulnerable": 8, "Observación": 5, "Psiquiatría": 4,
                     "Máxima seguridad": 6}
PERFIL_ESTADO = {            # probabilidad del estado mensual según el perfil del recluso
    "buena": {"buena": 75, "regular": 20, "mala": 5},
    "regular": {"buena": 30, "regular": 50, "mala": 20},
    "mala": {"buena": 10, "regular": 30, "mala": 60},
}


def ponderado(opciones):
    """Elige una clave de un diccionario {opción: peso}."""
    return random.choices(list(opciones), weights=list(opciones.values()))[0]


def anios(n):
    return timedelta(days=int(n * 365.25))


def telefono():
    return f"{random.choice(LADAS)}-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"


def nombre_completo(sexo=None):
    if sexo == "M":
        nombre = fake.first_name_male()
    elif sexo == "F":
        nombre = fake.first_name_female()
    else:
        nombre = fake.first_name()
    return f"{nombre} {fake.last_name()} {fake.last_name()}"


def fines_de_mes(desde, hasta):
    """Último día de cada mes d con desde < d <= hasta."""
    resultado, anio, mes = [], desde.year, desde.month
    while True:
        siguiente = date(anio + (mes == 12), mes % 12 + 1, 1)
        fin = siguiente - timedelta(days=1)
        if fin > hasta:
            break
        if fin > desde:
            resultado.append(fin)
        anio, mes = siguiente.year, siguiente.month
    return resultado


def texto_condena(dias):
    a, m = dias // 365, (dias % 365) // 30
    s = f"Prisión de {a} {'año' if a == 1 else 'años'}"
    return s + (f" y {m} {'mes' if m == 1 else 'meses'}" if m else "")


# ---------------------------------------------------------------------
# PASO 5 · Reclusos (PostgreSQL)
# ---------------------------------------------------------------------
def generar_reclusos():
    secciones = {s["id_seccion"]: s["seccion"] for s in TABLAS["seccion"]["filas"]}
    pabellones = {p["id_pabellon"]: p for p in TABLAS["pabellon"]["filas"]}
    celdas_por_seccion = {}
    for c in TABLAS["celda"]["filas"]:
        p = pabellones[c["id_pabellon"]]
        seccion = secciones[p["id_seccion"]]
        UBICACION[c["id_celda"]] = (seccion, p["pabellon"], c["numero_celda"])
        celdas_por_seccion.setdefault(seccion, []).append(c)
    capacidad = {c["id_celda"]: CAPACIDAD_CELDA[c["tipo_celda"]] for c in TABLAS["celda"]["filas"]}
    ocupacion = dict.fromkeys(capacidad, 0)
    delitos = COLECCIONES["delitos"]
    pesos_delito = [PESO_DELITO.get(d["delito"], 5) for d in delitos]

    infos = []
    for _ in range(N_RECLUSOS):
        sexo = "F" if random.random() < PCT_FEMENIL else random.choices(["M", "O"], weights=[98, 2])[0]
        nuevo = random.random() < PCT_NUEVOS
        estatus = "activo" if nuevo else ponderado(
            {"activo": 86, "hospitalizado": 4, "liberado": 6, "trasladado": 4})
        delito = random.choices(delitos, weights=pesos_delito)[0]
        grave = delito["delito"] in DELITOS_GRAVES
        if nuevo:
            ingreso = HOY - timedelta(days=random.randint(1, 29))
        elif estatus == "liberado":
            ingreso = HOY - timedelta(days=random.randint(4 * 365, 12 * 365))
        else:
            ingreso = HOY - timedelta(days=int(random.triangular(35, 12 * 365, 3 * 365)))
        edad = int(random.triangular(19, 65, 28))
        nacimiento = ingreso - timedelta(days=edad * 365 + random.randint(0, 364))
        inicio = min(ingreso + timedelta(days=random.randint(0, 120)), HOY)
        transcurridos = (HOY - inicio).days
        if estatus == "liberado":                       # condena ya cumplida
            duracion = random.randint(365, transcurridos - 30)
        else:                                           # condena vigente: termina en el futuro
            minimo, maximo = (10 * 365, 35 * 365) if grave else (365, 15 * 365)
            duracion = min(max(random.randint(minimo, maximo), transcurridos + 60), 40 * 365)
        infos.append({
            "sexo": sexo, "nuevo": nuevo, "estatus": estatus, "grave": grave,
            "id_delito": delito["id_delito"], "ingreso": ingreso, "nacimiento": nacimiento,
            "inicio": inicio, "duracion": duracion, "termino": inicio + timedelta(days=duracion),
            "estado_sent": "cumplida" if estatus == "liberado"
                           else ponderado({"vigente": 90, "apelada": 5, "suspendida": 5}),
            "perfil": ponderado({"buena": 50, "regular": 35, "mala": 15}),
            "nombre": nombre_completo("F" if sexo == "F" else "M" if sexo == "M" else None),
        })
    infos.sort(key=lambda i: i["ingreso"])              # id menor = ingreso más antiguo

    def libre(seccion):
        opciones = [c for c in celdas_por_seccion[seccion]
                    if ocupacion[c["id_celda"]] < capacidad[c["id_celda"]]]
        return random.choice(opciones) if opciones else None

    def elegir_seccion(i):
        edad_hoy = (HOY - i["nacimiento"]).days / 365.25
        custodia = i["estatus"] in EN_CUSTODIA
        if i["sexo"] == "F":
            return "Femenil"
        if i["estatus"] == "hospitalizado":
            return "Enfermería"
        if i["nuevo"]:
            return "Ingreso"
        if custodia and random.random() < 0.03:
            return "Aislamiento"
        if edad_hoy >= 60:
            return "Adultos mayores"
        if custodia and i["estado_sent"] == "vigente" and (i["termino"] - HOY).days <= 730:
            return "Preliberación"
        if i["estado_sent"] in ("apelada", "suspendida"):
            return "Procesados"
        return ponderado(SECCIONES_GRAVES if i["grave"] else SECCIONES_COMUNES)

    for i in infos:
        seccion = elegir_seccion(i)
        if i["estatus"] in EN_CUSTODIA:
            celda = libre(seccion)
            if celda is None and i["sexo"] != "F":      # sección llena: usa una común con espacio
                for alterna in random.sample(list(SECCIONES_COMUNES), len(SECCIONES_COMUNES)):
                    celda = libre(alterna)
                    if celda:
                        break
            assert celda is not None, f"Sin celdas libres para {seccion}"
            ocupacion[celda["id_celda"]] += 1
        else:                                           # liberado/trasladado: última celda, sin ocupar lugar
            celda = random.choice(celdas_por_seccion[seccion])
        i["id_celda"] = celda["id_celda"]

    filas = [{"id_celda": i["id_celda"], "nombre": i["nombre"], "sexo": i["sexo"],
              "fecha_nacimiento": i["nacimiento"], "fecha_ingreso": i["ingreso"],
              "estatus": i["estatus"]} for i in infos]
    registrar_tabla("recluso", "id_recluso", construir("id_recluso", filas))
    for n, i in enumerate(infos, start=1):
        i["id_recluso"] = n
    RECLUSOS.extend(infos)


# ---------------------------------------------------------------------
# PASO 5 · Empleados y asignaciones de trabajo
# ---------------------------------------------------------------------
ROL_A_PUESTO = {
    "administrador": "Administrativo", "director": "Director", "subdirector": "Subdirector",
    "jefe_custodios": "Jefe de custodios", "custodio": "Custodio", "medico": "Médico general",
    "enfermero": "Enfermero", "psicologo": "Psicólogo", "trabajador_social": "Trabajador social",
    "abogado": "Abogado de oficio", "recepcionista_visitas": "Recepcionista de visitas",
    "archivista": "Archivista", "auditor": "Administrativo", "recursos_humanos": "Administrativo",
    "soporte_ti": "Administrativo",
}
PUESTOS_EXTRA = ["Cocinero", "Personal de limpieza", "Mantenimiento", "Conductor",
                 "Operador de cámaras", "Instructor de taller"]
SUELDO_PUESTO = {
    "Director": (60000, 90000), "Subdirector": (45000, 65000), "Jefe de custodios": (22000, 32000),
    "Custodio": (11000, 18000), "Médico general": (28000, 45000), "Enfermero": (14000, 22000),
    "Psicólogo": (18000, 28000), "Trabajador social": (14000, 22000),
    "Abogado de oficio": (20000, 35000), "Recepcionista de visitas": (9000, 13000),
    "Archivista": (10000, 15000), "Administrativo": (11000, 20000), "Cocinero": (9000, 13000),
    "Personal de limpieza": (8000, 11000), "Mantenimiento": (9000, 14000),
    "Conductor": (9500, 14000), "Operador de cámaras": (10000, 15000),
    "Instructor de taller": (11000, 17000),
}
PUESTOS_MEDICOS = {"Médico general", "Enfermero", "Psicólogo"}
PUESTOS_OFICINA = {"Director", "Subdirector", "Administrativo", "Archivista", "Abogado de oficio",
                   "Trabajador social", "Recepcionista de visitas"}
SALAS_ATENCION = ["Consultorio 1", "Consultorio 2", "Consultorio 3", "Consultorio 4",
                  "Enfermería general", "Urgencias", "Psicología", "Odontología", "Observación",
                  "Curaciones", "Salud mental", "Aislamiento médico", "Rehabilitación"]


def generar_empleados():
    rol_de = {r["id_rol"]: r["rol"] for r in TABLAS["rol"]["filas"]}
    pendientes = []                                     # (fila, rol, puesto)
    for idx, u in enumerate(TABLAS["usuario"]["filas"]):
        rol = rol_de[u["id_rol"]]
        puesto = ROL_A_PUESTO[rol]
        if idx < len(ROLES):                            # usuarios de prueba: siempre activos
            estado = "activo"
        elif u["estatus"] == "inactivo":
            estado = "baja"
        elif u["estatus"] == "bloqueado":
            estado = "licencia"
        else:
            estado = ponderado({"activo": 88, "vacaciones": 8, "licencia": 4})
        pendientes.append(({
            "id_usuario": u["id_usuario"], "nombre": NOMBRES_USUARIO[idx],
            "fecha_ingreso": u["fecha_registro"].date() - timedelta(days=random.randint(0, 45)),
            "sueldo": round(random.uniform(*SUELDO_PUESTO[puesto]), 2), "estado": estado,
        }, rol, puesto))
    for _ in range(N_EXTRA_EMPLEADOS):
        puesto = random.choice(PUESTOS_EXTRA)
        pendientes.append(({
            "id_usuario": None, "nombre": nombre_completo(),
            "fecha_ingreso": fecha_aleatoria(HOY - anios(10), HOY - timedelta(days=30)),
            "sueldo": round(random.uniform(*SUELDO_PUESTO[puesto]), 2),
            "estado": ponderado({"activo": 90, "vacaciones": 6, "licencia": 4}),
        }, None, puesto))
    filas = construir("id_empleado", [p[0] for p in pendientes])
    registrar_tabla("empleado", "id_empleado", filas)
    for fila, (_, rol, puesto) in zip(filas, pendientes):
        EMPLEADOS.append({**fila, "rol": rol, "puesto": puesto})


def generar_asignaciones():
    id_puesto = {p["puesto"]: p["id_puesto"] for p in TABLAS["puesto"]["filas"]}
    id_seccion = {s["seccion"]: s["id_seccion"] for s in TABLAS["seccion"]["filas"]}
    id_sala = {s["nombre"]: s["id_sala"] for s in TABLAS["sala"]["filas"]}
    turnos = TABLAS["turno"]["filas"]
    en_custodia = [r["id_recluso"] for r in RECLUSOS if r["estatus"] in EN_CUSTODIA]
    filas = []
    for e in EMPLEADOS:
        p = e["puesto"]
        if p in PUESTOS_OFICINA:
            opciones = [t for t in turnos if t["turno"].startswith("Matutino")
                        and t["turno"].endswith(("L-V", "L-S"))]
        elif p in PUESTOS_MEDICOS:
            opciones = [t for t in turnos if t["turno"].startswith(("Matutino", "Vespertino"))]
        else:
            opciones = turnos
        sala = seccion = None
        if p in PUESTOS_MEDICOS:
            sala = id_sala[random.choice(SALAS_ATENCION)]
        elif p in PUESTOS_OFICINA:
            seccion = id_seccion["Ingreso"]
        else:
            seccion = random.choice(TABLAS["seccion"]["filas"])["id_seccion"]
        recluso = random.choice(en_custodia) if p == "Custodio" and random.random() < 0.15 else None
        inicio = e["fecha_ingreso"] + timedelta(
            days=random.randint(0, min(365, (HOY - e["fecha_ingreso"]).days)))
        filas.append({
            "id_empleado": e["id_empleado"], "id_puesto": id_puesto[p],
            "id_turno": random.choice(opciones)["id_turno"], "id_seccion": seccion,
            "id_sala": sala, "id_recluso": recluso,
            "registro": f"Alta de asignación del {inicio.strftime('%d/%m/%Y')} ({p})",
            "inicio_trabajo": inicio,
        })
    registrar_tabla("asignacion_trabajo", "id_asignacion", construir("id_asignacion", filas))


# ---------------------------------------------------------------------
# PASO 5 · Área médica
# ---------------------------------------------------------------------
# diagnóstico -> (razón de consulta, tipo de atención, examen, medicamento)
DIAG_INFO = {
    "Hipertensión arterial": ("Control de presión arterial", "general", "Electrocardiograma", "Losartán"),
    "Diabetes mellitus tipo 2": ("Seguimiento de glucosa", "general", "Glucosa en ayunas", "Metformina"),
    "Infección respiratoria aguda": ("Tos y fiebre", "general", "Radiografía de tórax", "Amoxicilina"),
    "Gastritis": ("Dolor abdominal", "general", "Prueba de Helicobacter pylori", "Omeprazol"),
    "Lumbalgia": ("Dolor de espalda baja", "general", "Radiografía de columna", "Naproxeno"),
    "Migraña": ("Dolor de cabeza recurrente", "general", "Valoración neurológica", "Paracetamol"),
    "Asma bronquial": ("Dificultad para respirar", "general", "Espirometría", "Salbutamol"),
    "Dermatitis": ("Irritación en la piel", "general", "Valoración dermatológica", "Hidrocortisona"),
    "Conjuntivitis": ("Enrojecimiento ocular", "general", "Examen oftalmológico", "Tobramicina oftálmica"),
    "Influenza estacional": ("Fiebre y malestar general", "general", "Prueba rápida de influenza", "Oseltamivir"),
    "Hepatitis viral": ("Ictericia y cansancio", "general", "Perfil hepático", "Silimarina"),
    "Tuberculosis pulmonar": ("Tos persistente", "general", "Baciloscopia", "Isoniazida y rifampicina"),
    "Trastorno de ansiedad": ("Nerviosismo y palpitaciones", "psico", "Escala de ansiedad de Hamilton", "Sertralina"),
    "Depresión": ("Tristeza persistente", "psico", "Escala de depresión de Beck", "Fluoxetina"),
    "Insomnio": ("Dificultad para dormir", "psico", "Evaluación psicológica", "Melatonina"),
    "Contusión por golpe": ("Lesión por golpe", "urgencia", "Radiografía", "Ibuprofeno"),
    "Fractura simple": ("Dolor e inflamación tras caída", "urgencia", "Radiografía", "Ketorolaco"),
    "Caries dental": ("Dolor dental", "dental", "Radiografía dental", "Amoxicilina"),
    "Infección urinaria": ("Ardor al orinar", "general", "Examen general de orina", "Nitrofurantoína"),
    "Deshidratación": ("Mareo y sed intensa", "urgencia", "Química sanguínea", "Suero oral"),
}
SALAS_POR_TIPO = {
    "general": ["Consultorio 1", "Consultorio 2", "Consultorio 3", "Consultorio 4",
                "Enfermería general", "Observación"],
    "psico": ["Psicología", "Salud mental"], "dental": ["Odontología"],
    "urgencia": ["Urgencias", "Curaciones"],
}
ROLES_POR_TIPO = {"general": ["medico", "enfermero"], "psico": ["psicologo"],
                  "dental": ["medico"], "urgencia": ["medico", "enfermero"]}
UNIDAD_MEDICAMENTO = {"Salbutamol": "2 inhalaciones", "Suero oral": "1 sobre disuelto en un litro de agua",
                      "Hidrocortisona": "una aplicación tópica", "Tobramicina oftálmica": "1 gota"}
EXAMENES_COMUNES = ["Biometría hemática", "Química sanguínea", "Examen general de orina"]
RESULTADOS_EXAMEN = {"Sin hallazgos relevantes": 40, "Resultados dentro de parámetros normales": 25,
                     "Se recomienda seguimiento en 15 días": 15,
                     "Valores alterados; ajustar tratamiento": 12,
                     "Pendiente de interpretación por especialista": 8}


def indicacion(medicamento):
    unidad = UNIDAD_MEDICAMENTO.get(medicamento, "1 tableta")
    return (f"Tomar {unidad} cada {random.choice([8, 12, 24])} horas "
            f"durante {random.choice([5, 7, 10, 15, 30])} días")


def generar_area_medica():
    for diag in TABLAS["diagnostico"]["filas"]:
        assert diag["diagnostico"] in DIAG_INFO, f"Falta información del diagnóstico {diag['diagnostico']}"
    id_diag = {d["diagnostico"]: d["id_diagnostico"] for d in TABLAS["diagnostico"]["filas"]}
    id_sala = {s["nombre"]: s["id_sala"] for s in TABLAS["sala"]["filas"]}

    # --- expedientes: uno por recluso
    expedientes = []
    for r in RECLUSOS:
        afecciones = [ponderado({
            "ninguna": 45, "Hipertensión": 12, "Diabetes": 10, "Asma": 8, "Gastritis crónica": 7,
            "Hepatitis C": 3, "Epilepsia": 3, "Obesidad": 6, "Insuficiencia renal": 2,
            "Lumbalgia crónica": 4, "Anemia": 3})]
        if afecciones[0] != "ninguna" and random.random() < 0.15:
            afecciones.append(random.choice(["Hipertensión", "Obesidad", "Asma", "Anemia"]))
        expedientes.append({
            "id_recluso": r["id_recluso"],
            "expediente": f"Expediente clínico EXP-{r['ingreso'].year}-{r['id_recluso']:05d}. "
                          f"Ingreso: {r['ingreso'].isoformat()}",
            "alergias": ponderado({"ninguna": 60, "Penicilina": 8, "Polen": 6, "Mariscos": 5,
                                   "Látex": 3, "Ibuprofeno": 4, "Sulfas": 3, "Polvo": 6, "Lácteos": 5}),
            "afecciones": ", ".join(dict.fromkeys(afecciones)),
        })
    registrar_tabla("expediente", "id_expediente", construir("id_expediente", expedientes))

    # --- consultas: solo reclusos en custodia (los hospitalizados se atienden más)
    pool = [r for r in RECLUSOS if r["estatus"] in EN_CUSTODIA]
    pesos = [6 if r["estatus"] == "hospitalizado" else 1 for r in pool]
    personal = [e for e in EMPLEADOS if e["estado"] == "activo" and e["rol"] in ("medico", "enfermero", "psicologo")]
    consultas = []
    while len(consultas) < N_CONSULTAS:
        r = random.choices(pool, weights=pesos)[0]
        diag = random.choice(TABLAS["diagnostico"]["filas"])
        razon, tipo, _, _ = DIAG_INFO[diag["diagnostico"]]
        e = random.choice([x for x in personal if x["rol"] in ROLES_POR_TIPO[tipo]])
        desde = max(r["ingreso"], HOY - timedelta(days=730), e["fecha_ingreso"])
        if desde >= HOY:
            continue
        dia = fecha_aleatoria(desde, HOY)
        momento = datetime.combine(dia, time(random.randint(8, 18), random.randint(0, 59)))
        if momento > REFERENCIA - timedelta(hours=1):
            continue
        consultas.append({
            "id_recluso": r["id_recluso"], "id_empleado": e["id_empleado"],
            "id_expediente": r["id_recluso"], "id_sala": id_sala[random.choice(SALAS_POR_TIPO[tipo])],
            "id_diagnostico": diag["id_diagnostico"], "razon_consulta": razon, "fecha": momento,
            "_diag": diag["diagnostico"],
        })
    consultas.sort(key=lambda c: c["fecha"])
    diag_de = [c.pop("_diag") for c in consultas]
    filas = construir("id_consulta", consultas)
    registrar_tabla("consulta_medica", "id_consulta", filas)

    # --- exámenes y recetas derivados de cada consulta
    examenes, recetas = [], []
    for c, nombre_diag in zip(filas, diag_de):
        _, _, examen, medicamento = DIAG_INFO[nombre_diag]
        tipos = []
        if random.random() < 0.55:
            tipos.append(examen)
            if random.random() < 0.10:
                tipos.append(random.choice(EXAMENES_COMUNES))
        for t in tipos:
            examenes.append({"id_consulta": c["id_consulta"],
                             "id_diagnostico": c["id_diagnostico"] if random.random() < 0.85 else None,
                             "tipo_examen": t, "observaciones": ponderado(RESULTADOS_EXAMEN)})
        meds = []
        if random.random() < 0.65:
            meds.append(medicamento)
            if random.random() < 0.15:
                meds.append(random.choice([m for m in ["Paracetamol", "Omeprazol", "Loratadina",
                                                       "Vitamina C"] if m != medicamento]))
        for m in meds:
            recetas.append({"id_consulta": c["id_consulta"], "medicamento": m,
                            "indicacion_medica": indicacion(m)})
    registrar_tabla("examen", "id_examen", construir("id_examen", examenes))
    registrar_tabla("receta", "id_receta", construir("id_receta", recetas))


# ---------------------------------------------------------------------
# PASO 5 · Visitas (domicilios, visitantes y visitas)
# ---------------------------------------------------------------------
PARENTESCO_M = {"Padre": 11, "Hermano": 8, "Hijo": 7, "Esposo": 7, "Abuelo": 2, "Tío": 3, "Primo": 3,
                "Pareja": 4, "Amigo": 5, "Abogado": 3, "Vecino": 1, "Compañero de trabajo": 1}
PARENTESCO_F = {"Madre": 11, "Hermana": 8, "Hija": 7, "Esposa": 7, "Abuela": 2, "Tía": 3, "Prima": 3,
                "Pareja": 4, "Amigo": 4, "Abogado": 2, "Vecino": 1, "Compañero de trabajo": 1}


def razon_visita(parentesco):
    if parentesco == "Abogado":
        return random.choice(["Asesoría legal", "Revisión de expediente jurídico", "Preparación de audiencia"])
    if parentesco in ("Amigo", "Vecino", "Compañero de trabajo"):
        return random.choice(["Visita de amistad", "Visita de apoyo emocional", "Visita de rutina"])
    if parentesco in ("Esposo", "Esposa", "Pareja") and random.random() < 0.3:
        return "Visita conyugal"
    return random.choice(["Visita familiar", "Visita de apoyo emocional", "Entrega de documentos",
                          "Visita de cumpleaños", "Visita de rutina"])


def generar_visitas():
    id_par = {p["parentesco"]: p["id_parentesco"] for p in TABLAS["parentesco"]["filas"]}
    domicilios = [{"direccion": fake.street_address(), "ciudad": fake.city(), "estado": fake.state()}
                  for _ in range(N_DOMICILIOS)]
    registrar_tabla("domicilio", "id_domicilio", construir("id_domicilio", domicilios))

    visitantes, sexos = [], []
    for n in range(N_VISITANTES):
        sexo = random.choice(["M", "F"])
        sexos.append(sexo)
        visitantes.append({"id_domicilio": n + 1 if n < N_DOMICILIOS else random.randint(1, N_DOMICILIOS),
                           "nombre": nombre_completo(sexo)})
    registrar_tabla("visitante", "id_visitante", construir("id_visitante", visitantes))

    # relaciones (visitante, recluso, parentesco): cada visitante viene por 1 o 2 reclusos
    elegibles = [r for r in RECLUSOS if r["estatus"] in EN_CUSTODIA and (HOY - r["ingreso"]).days >= 10]
    relaciones = []
    for n, sexo in enumerate(sexos, start=1):
        for r in random.sample(elegibles, 2 if random.random() < 0.20 else 1):
            relaciones.append((n, r, ponderado(PARENTESCO_M if sexo == "M" else PARENTESCO_F)))

    dias_permitidos = {}

    def dias_de(r):
        if r["id_recluso"] not in dias_permitidos:
            desde = max(r["ingreso"] + timedelta(days=1), HOY - timedelta(days=540))
            hasta = HOY - timedelta(days=1)
            dias_permitidos[r["id_recluso"]] = [
                desde + timedelta(days=i) for i in range((hasta - desde).days + 1)
                if (desde + timedelta(days=i)).weekday() in DIAS_VISITA]
        return dias_permitidos[r["id_recluso"]]

    elegidas = relaciones + random.choices(relaciones, k=N_VISITAS - len(relaciones))
    visitas = []
    for n_visitante, r, parentesco in elegidas:
        entrada = time(random.randint(9, 15), random.choice(range(0, 60, 5)))
        salida = (datetime.combine(date.min, entrada) + timedelta(minutes=random.randint(30, 120))).time()
        visitas.append({
            "id_recluso": r["id_recluso"], "id_visitante": n_visitante, "id_parentesco": id_par[parentesco],
            "razon_visita": razon_visita(parentesco), "fecha": random.choice(dias_de(r)),
            "hora_ingreso": entrada, "hora_salida": salida,
        })
    visitas.sort(key=lambda v: (v["fecha"], v["hora_ingreso"]))
    registrar_tabla("visita", "id_visita", construir("id_visita", visitas))


# ---------------------------------------------------------------------
# PASO 5 · MongoDB: administración de reclusos
# ---------------------------------------------------------------------
RAZONES_TRASLADO = ["Reubicación por sobrepoblación", "Solicitud del interno", "Cambio por conducta",
                    "Separación por seguridad", "Reclasificación penitenciaria",
                    "Cercanía con familiares", "Mantenimiento de instalaciones"]
RAZON_POR_DESTINO = {"Enfermería": "Atención médica", "Aislamiento": "Medida disciplinaria",
                     "Preliberación": "Preparación para la liberación",
                     "Adultos mayores": "Reclasificación por edad", "Psiquiatría": "Valoración psiquiátrica"}


def generar_sentencias():
    delitos = {d["id_delito"]: d for d in COLECCIONES["delitos"]}
    docs, id_fianza = [], 0
    for r in RECLUSOS:
        doc = {
            "id_sentencia": r["id_recluso"], "id_recluso": r["id_recluso"],
            "sentencia": texto_condena(r["duracion"]),
            "inicio_condena": r["inicio"], "termino_condena": r["termino"],
            "estado": r["estado_sent"], "delito": dict(delitos[r["id_delito"]]),
        }
        if not r["grave"] and random.random() < 0.25:   # fianza opcional, solo delitos no graves
            id_fianza += 1
            doc["fianza"] = {
                "id_fianza": id_fianza, "monto": random.randint(10, 800) * 500, "telefono": telefono(),
                "acreedores": [nombre_completo() for _ in range(random.randint(1, 3))],
            }
        docs.append(doc)
    COLECCIONES["sentencias"] = docs


def generar_traslados():
    pool_f = [c for c, u in UBICACION.items() if u[0] == "Femenil"]
    pool_m = [c for c, u in UBICACION.items() if u[0] != "Femenil"]
    candidatos = [r for r in RECLUSOS if r["estatus"] in EN_CUSTODIA and (HOY - r["ingreso"]).days >= 60]
    random.shuffle(candidatos)
    dobles = N_TRASLADOS // 10                           # reclusos con dos traslados
    elegidos = [(r, 2) for r in candidatos[:dobles]] + \
               [(r, 1) for r in candidatos[dobles:dobles + N_TRASLADOS - 2 * dobles]]
    docs = []
    for r, k in elegidos:
        pool = pool_f if r["sexo"] == "F" else pool_m
        fechas = sorted(fecha_aleatoria(r["ingreso"] + timedelta(days=30), HOY - timedelta(days=1))
                        for _ in range(k))
        if k == 2 and fechas[0] == fechas[1]:
            fechas[0] -= timedelta(days=1)
        destino = r["id_celda"]                          # el último traslado termina en la celda actual
        for fecha in reversed(fechas):
            origen = random.choice([c for c in pool if c != destino])
            seccion_destino = UBICACION[destino][0]
            docs.append({
                "id_recluso": r["id_recluso"],
                "razon_traslado": RAZON_POR_DESTINO.get(seccion_destino, random.choice(RAZONES_TRASLADO)),
                "id_celda_origen": origen, "id_celda_nueva": destino, "fecha_traslado": fecha,
            })
            destino = origen
    docs.sort(key=lambda d: (d["fecha_traslado"], d["id_recluso"]))
    COLECCIONES["traslados"] = construir("id_traslado", docs)


def generar_antecedentes():
    catalogo = COLECCIONES["delitos"]
    docs = []
    for r in RECLUSOS:
        desde = r["nacimiento"] + anios(18)
        hasta = r["ingreso"] - timedelta(days=60)
        n = ponderado({0: 55, 1: 20, 2: 12, 3: 8, 4: 3, 5: 2}) if hasta > desde + timedelta(days=90) else 0
        cargos = []
        fechas = sorted(desde + timedelta(days=random.randint(0, (hasta - desde).days)) for _ in range(n))
        for idx, f in enumerate(fechas):
            limite = (fechas[idx + 1] if idx + 1 < n else hasta) - timedelta(days=1)
            max_meses = (limite - f).days // 30
            resolucion = ponderado({"condenado": 50, "absuelto": 15, "sobreseido": 15,
                                    "libertad_condicional": 20})
            if resolucion in ("condenado", "libertad_condicional") and max_meses < 1:
                resolucion = "absuelto"
            d = random.choice(catalogo)
            cargo = {
                "id_delito": d["id_delito"], "tipo_delito": d["tipo_delito"], "delito": d["delito"],
                "fecha_cargo": f,
                "autoridad": random.choice([
                    f"Juzgado {random.randint(1, 20)}° Penal de {fake.city()}",
                    f"Fiscalía General del Estado de {fake.state()}"])[:120],
                "resolucion": resolucion,
            }
            if resolucion in ("condenado", "libertad_condicional"):
                meses = min(random.randint(6, 120), max_meses)
                cargo["condena_meses"] = meses
                cargo["lugar_reclusion"] = f"Centro de Reinserción Social de {fake.city()}"[:120]
                cargo["fecha_liberacion"] = f + timedelta(days=meses * 30)
            cargos.append(cargo)
        condenas = sum(c["resolucion"] in ("condenado", "libertad_condicional") for c in cargos)
        docs.append({
            "id_antecedente": r["id_recluso"], "id_recluso": r["id_recluso"],
            "reincidente": condenas > 0, "total_cargos_previos": len(cargos), "cargos_previos": cargos,
            "observaciones": (f"Reincidente: {condenas} condena(s) previa(s)." if condenas
                              else "Cargos previos sin condena." if cargos else "Sin antecedentes penales."),
            "fecha_actualizacion": r["ingreso"] + timedelta(days=random.randint(0, (HOY - r["ingreso"]).days)),
        })
    COLECCIONES["antecedentes"] = docs


OBSERVACIONES_BITACORA = {
    "buena": ["Conducta ejemplar", "Participa en talleres", "Cumple con sus actividades"],
    "regular": ["Conducta aceptable con observaciones", "Requiere seguimiento"],
    "mala": ["Reportes de indisciplina", "Sanción disciplinaria en el periodo"],
}


def generar_bitacoras():
    docs = []
    for r in RECLUSOS:
        if r["nuevo"]:                                   # recién ingresados: aún sin bitácora
            continue
        fin = min(HOY, r["termino"]) if r["estatus"] == "liberado" else HOY
        cierres = fines_de_mes(r["ingreso"], fin)[-6:]   # últimos (hasta) 6 cierres mensuales
        if not cierres:
            continue
        trabaja = random.random() < 0.70
        registros = []
        for cierre in cierres:
            estado = ponderado(PERFIL_ESTADO[r["perfil"]])
            horas_trabajo = random.randint(16, 160) if trabaja and (estado != "mala" or random.random() < 0.3) else 0
            por_trabajo = min(40, max(4, horas_trabajo // 4)) if horas_trabajo else 0   # 4 a 40 h
            if estado == "mala":
                reducidas, motivo = 0, "ninguno"
            elif estado == "buena":
                conducta = random.randint(8, 24)                                          # 8 a 24 h
                reducidas, motivo = (por_trabajo + conducta, "ambos") if horas_trabajo \
                    else (conducta, "buena_conducta")
            else:
                reducidas, motivo = (por_trabajo, "trabajo") if horas_trabajo else (0, "ninguno")
            registros.append({
                "fecha": cierre, "estado": estado, "horas_trabajo": horas_trabajo,
                "horas_reducidas": reducidas, "motivo_reduccion": motivo,
                "observaciones": random.choice(OBSERVACIONES_BITACORA[estado]),
            })
        docs.append({
            "id_bitacora": len(docs) + 1, "id_recluso": r["id_recluso"],
            "estado_actual": registros[-1]["estado"],
            "total_horas_trabajo": sum(x["horas_trabajo"] for x in registros),
            "total_horas_reducidas": sum(x["horas_reducidas"] for x in registros),
            "registros": registros, "fecha_actualizacion": cierres[-1],
        })
    COLECCIONES["bitacoras"] = docs


PARENTESCOS_CONTACTO_M = ["Padre", "Hermano", "Hijo", "Esposo", "Abuelo", "Tío", "Primo"]
PARENTESCOS_CONTACTO_F = ["Madre", "Hermana", "Hija", "Esposa", "Abuela", "Tía", "Prima"]


def generar_contactos():
    docs = []
    for r in RECLUSOS:
        for _ in range(ponderado({1: 40, 2: 40, 3: 20})):
            tipo = random.choice(["M", "F", "N"])
            if tipo == "M":
                parentesco, sexo = random.choice(PARENTESCOS_CONTACTO_M), "M"
            elif tipo == "F":
                parentesco, sexo = random.choice(PARENTESCOS_CONTACTO_F), "F"
            else:
                parentesco, sexo = random.choice(["Pareja", "Amigo"]), random.choice(["M", "F"])
            docs.append({"id_recluso": r["id_recluso"], "nombre": nombre_completo(sexo),
                         "telefono": telefono(), "parentesco": parentesco})
    COLECCIONES["contactos_emergencia"] = construir("id_contacto", docs)


# ---------------------------------------------------------------------
# PASO 5 · MongoDB: sanciones (catálogos e incidentes con tipo y castigos embebidos)
# ---------------------------------------------------------------------
NIVEL_INCIDENTE = {
    "Desobediencia": 1, "Falta de respeto": 1, "Incumplimiento de horarios": 1,
    "Comunicación no autorizada": 1, "Amenazas": 1,
    "Posesión de objetos prohibidos": 2, "Daños a instalaciones": 2, "Consumo de sustancias": 2,
    "Tráfico de objetos": 2, "Robo entre internos": 2, "Acoso": 2, "Autolesión": 2,
    "Riña": 3, "Intento de fuga": 3, "Agresión a custodio": 3, "Motín": 3,
}
SANCIONES_POR_NIVEL = {
    1: ["Amonestación verbal", "Amonestación escrita", "Pérdida de visita 1 semana",
        "Restricción de patio", "Retiro de privilegios", "Trabajo comunitario"],
    2: ["Pérdida de visita 1 semana", "Pérdida de visita 1 mes", "Aislamiento 3 días", "Pérdida de trabajo",
        "Restricción de llamadas", "Suspensión de beneficios", "Cambio de pabellón"],
    3: ["Aislamiento 7 días", "Aislamiento 15 días", "Pérdida de visita 1 mes",
        "Suspensión de beneficios", "Traslado disciplinario", "Cambio de pabellón"],
}
DURACION_SANCION = {"Amonestación verbal": 0, "Amonestación escrita": 0, "Pérdida de visita 1 semana": 7,
                    "Pérdida de visita 1 mes": 30, "Aislamiento 3 días": 3, "Aislamiento 7 días": 7,
                    "Aislamiento 15 días": 15}


PARTICIPANTES_EXTRA = {          # reclusos adicionales (mínimo, máximo) que suelen intervenir
    "Riña": (1, 2), "Motín": (2, 4), "Robo entre internos": (0, 1), "Acoso": (0, 1),
    "Tráfico de objetos": (0, 1), "Consumo de sustancias": (0, 2), "Intento de fuga": (0, 2),
}


def generar_incidentes():
    """Colección incidentes: un documento por incidente con el tipo embebido y la lista de
    castigos (uno por recluso involucrado), cada castigo con su sanción embebida."""
    tipos = {t["incidente"]: t for t in COLECCIONES["tipos_incidente"]}
    sanciones = {s["sancion"]: s for s in COLECCIONES["sanciones"]}
    assert set(NIVEL_INCIDENTE) == set(tipos), "NIVEL_INCIDENTE no coincide con tipo_incidente"
    for nombres in SANCIONES_POR_NIVEL.values():
        assert set(nombres) <= set(sanciones), "SANCIONES_POR_NIVEL usa una sanción inexistente"
    pool = [r for r in RECLUSOS if r["estatus"] in EN_CUSTODIA and (HOY - r["ingreso"]).days >= 10]
    pesos = [{"buena": 1, "regular": 3, "mala": 8}[r["perfil"]] for r in pool]
    por_seccion = {}
    for r in pool:
        por_seccion.setdefault(UBICACION[r["id_celda"]][0], []).append(r)

    pendientes = []
    for _ in range(N_INCIDENTES):
        principal = random.choices(pool, weights=pesos)[0]
        t = tipos[random.choice(list(tipos))]
        fecha = fecha_aleatoria(max(principal["ingreso"] + timedelta(days=1), HOY - timedelta(days=1095)),
                                HOY - timedelta(days=1))
        seccion, pabellon, numero = UBICACION[principal["id_celda"]]
        candidatos = [r for r in por_seccion[seccion] if r is not principal and r["ingreso"] < fecha]
        extra = random.randint(*PARTICIPANTES_EXTRA.get(t["incidente"], (0, 0)))
        pendientes.append({
            "fila": {"tipo_incidente": dict(t), "fecha_incidente": fecha,
                     "descripcion": f"{t['descripcion']}. Ocurrió en {seccion}, {pabellon}, celda {numero}."},
            "nivel": NIVEL_INCIDENTE[t["incidente"]],
            "participantes": [principal] + random.sample(candidatos, min(extra, len(candidatos))),
        })
    pendientes.sort(key=lambda p: (p["fila"]["fecha_incidente"], p["participantes"][0]["id_recluso"]))

    docs, id_castigo = [], 0
    for p in pendientes:
        lista = []
        for r in p["participantes"]:
            s = sanciones[random.choice(SANCIONES_POR_NIVEL[p["nivel"]])]
            inicio = min(p["fila"]["fecha_incidente"] + timedelta(days=random.randint(1, 5)), HOY)
            dias = DURACION_SANCION.get(s["sancion"], random.randint(7, 60))
            id_castigo += 1
            lista.append({"id_castigo": id_castigo, "id_recluso": r["id_recluso"], "sancion": dict(s),
                          "fecha_inicio": inicio, "fecha_termino": inicio + timedelta(days=dias)})
        docs.append({**p["fila"], "castigos": lista})
    COLECCIONES["incidentes"] = construir("id_incidente", docs)


# ---------------------------------------------------------------------
# PASO 5 · MongoDB: visitas (ingresos y decomisos)
# ---------------------------------------------------------------------
ARTICULOS_PERMITIDOS = {
    "Ropa": ["Playeras blancas", "Pantalón de mezclilla azul", "Ropa interior nueva", "Sudadera lisa"],
    "Alimentos empacados": ["Galletas selladas", "Pan empacado", "Botana sellada", "Café soluble"],
    "Artículos de higiene": ["Jabón de barra", "Pasta dental", "Shampoo en envase transparente",
                             "Papel higiénico"],
    "Libros": ["Novela", "Libro de texto", "Biblia", "Libro de crucigramas"],
    "Cartas y fotografías": ["Cartas familiares", "Fotografías impresas", "Dibujos de los hijos"],
    "Medicamento con receta": ["Tratamiento con receta médica vigente", "Vitaminas selladas"],
    "Documentos": ["Copia de acta de nacimiento", "Documentos legales", "Constancia de estudios"],
    "Calzado": ["Tenis blancos sin agujetas metálicas", "Sandalias de plástico"],
}
ARTICULOS_PROHIBIDOS = {                                 # artículo -> motivo del decomiso
    "Teléfono celular": "Equipo de comunicación no permitido en el centro",
    "Cargador y audífonos": "Accesorios de comunicación no permitidos",
    "Navaja": "Objeto punzocortante",
    "Cigarrillos": "Tabaco no autorizado",
    "Bebida alcohólica": "Bebidas alcohólicas prohibidas",
    "Sustancia no identificada": "Posible narcótico; se da aviso a la autoridad",
    "Dinero en efectivo": "Efectivo por encima del monto permitido",
    "Encendedor": "Objeto inflamable",
    "Aerosol": "Envase presurizado",
    "Memoria USB": "Dispositivo de almacenamiento no autorizado",
}


def generar_ingresos_decomisos():
    visitas = TABLAS["visita"]["filas"]
    articulos = ([("permitido", a) for a in random.choices(list(ARTICULOS_PERMITIDOS),
                                                           k=N_INGRESOS - N_DECOMISOS)] +
                 [("prohibido", a) for a in random.choices(list(ARTICULOS_PROHIBIDOS), k=N_DECOMISOS)])
    random.shuffle(articulos)
    ingresos = []
    for clase, articulo in articulos:
        v = random.choice(visitas)
        if clase == "permitido":
            descripcion = f"{random.choice(ARTICULOS_PERMITIDOS[articulo])} ({random.randint(1, 5)} pieza(s))"
        else:
            descripcion = (f"{articulo} detectado en revisión "
                           f"({random.choice(['bolsa de mano', 'alimentos', 'calzado', 'ropa', 'revisión corporal'])})")
        ingresos.append({"id_visita": v["id_visita"], "articulo": articulo,
                         "descripcion_articulos": descripcion, "fecha_ingreso": v["fecha"],
                         "_prohibido": clase == "prohibido"})
    ingresos.sort(key=lambda d: (d["fecha_ingreso"], d["id_visita"]))
    ingresos = construir("id_ingreso", ingresos)
    decomisos = [{"id_ingreso": i["id_ingreso"], "articulo": i["articulo"],
                  "motivo": ARTICULOS_PROHIBIDOS[i["articulo"]], "fecha_decomiso": i["fecha_ingreso"]}
                 for i in ingresos if i["_prohibido"]]
    for i in ingresos:
        del i["_prohibido"]
    COLECCIONES["ingresos"] = ingresos
    COLECCIONES["decomisos"] = construir("id_decomiso", decomisos)


# ---------------------------------------------------------------------
# PASO 5 · Validación de coherencia de los datos
# ---------------------------------------------------------------------
def validar_datos():
    def ids(tabla, pk):
        return {f[pk] for f in TABLAS[tabla]["filas"]}

    rec = {r["id_recluso"]: r for r in RECLUSOS}
    visitas = {v["id_visita"]: v for v in TABLAS["visita"]["filas"]}
    celdas = ids("celda", "id_celda")
    tipos = {t["id_tipo_incidente"] for t in COLECCIONES["tipos_incidente"]}
    sanc = {x["id_sancion"] for x in COLECCIONES["sanciones"]}
    delitos = {d["id_delito"] for d in COLECCIONES["delitos"]}

    # --- volúmenes mínimos
    for t in ("usuario", "recluso", "empleado", "asignacion_trabajo", "consulta_medica", "examen",
              "receta", "domicilio", "visitante", "visita"):
        assert len(TABLAS[t]["filas"]) >= 100, f"{t} tiene menos de 100 filas"
    for c in ("sentencias", "traslados", "antecedentes", "bitacoras", "contactos_emergencia",
              "ingresos", "incidentes"):
        assert len(COLECCIONES[c]) >= 100, f"{c} tiene menos de 100 documentos"
    assert len(TABLAS) + len(COLECCIONES) >= 30, "Menos de 30 tablas y colecciones"

    # --- celdas: capacidad y sección femenil
    ocupacion = {}
    for r, fila in zip(RECLUSOS, TABLAS["recluso"]["filas"]):
        assert (UBICACION[fila["id_celda"]][0] == "Femenil") == (fila["sexo"] == "F"), "Sexo/sección Femenil"
        if fila["estatus"] in EN_CUSTODIA:
            ocupacion[fila["id_celda"]] = ocupacion.get(fila["id_celda"], 0) + 1
    tipo_celda = {c["id_celda"]: c["tipo_celda"] for c in TABLAS["celda"]["filas"]}
    for c, n in ocupacion.items():
        assert n <= CAPACIDAD_CELDA[tipo_celda[c]], f"Celda {c} sobrepasa su capacidad"

    # --- sentencias
    assert len(COLECCIONES["sentencias"]) == len(rec)
    for s in COLECCIONES["sentencias"]:
        r = rec[s["id_recluso"]]
        assert r["ingreso"] <= s["inicio_condena"] < s["termino_condena"], "Fechas de sentencia"
        assert (s["estado"] == "cumplida") == (r["estatus"] == "liberado"), "Estado de sentencia/recluso"
        assert (s["termino_condena"] <= HOY) == (s["estado"] == "cumplida"), "Término de condena"
        assert s["delito"]["id_delito"] in delitos

    # --- traslados: celdas válidas y la celda actual es el destino del último traslado
    ultimo = {}
    for t in COLECCIONES["traslados"]:
        r = rec[t["id_recluso"]]
        assert t["id_celda_origen"] in celdas and t["id_celda_nueva"] in celdas
        assert t["id_celda_origen"] != t["id_celda_nueva"]
        assert t["fecha_traslado"] >= r["ingreso"]
        ultimo[t["id_recluso"]] = t                      # ordenados por fecha: queda el más reciente
    for id_r, t in ultimo.items():
        assert t["id_celda_nueva"] == rec[id_r]["id_celda"], "Último traslado no coincide con la celda actual"

    # --- antecedentes
    assert {a["id_recluso"] for a in COLECCIONES["antecedentes"]} == set(rec), "Un antecedente por recluso"
    for a in COLECCIONES["antecedentes"]:
        r = rec[a["id_recluso"]]
        assert a["total_cargos_previos"] == len(a["cargos_previos"])
        condenas = any(c["resolucion"] in ("condenado", "libertad_condicional") for c in a["cargos_previos"])
        assert a["reincidente"] == condenas, "Regla de reincidencia"
        for c in a["cargos_previos"]:
            assert c["id_delito"] in delitos and c["fecha_cargo"] < r["ingreso"], "Cargo previo posterior al ingreso"
            if "fecha_liberacion" in c:
                assert c["fecha_cargo"] <= c["fecha_liberacion"] < r["ingreso"]

    # --- bitácoras
    con_bitacora = {b["id_recluso"] for b in COLECCIONES["bitacoras"]}
    assert con_bitacora == {i for i, r in rec.items() if not r["nuevo"]}, "Solo los recién ingresados quedan sin bitácora"
    for b in COLECCIONES["bitacoras"]:
        regs = b["registros"]
        assert b["total_horas_trabajo"] == sum(x["horas_trabajo"] for x in regs)
        assert b["total_horas_reducidas"] == sum(x["horas_reducidas"] for x in regs)
        assert b["estado_actual"] == regs[-1]["estado"]
        assert [x["fecha"] for x in regs] == sorted(x["fecha"] for x in regs)
        for x in regs:
            if x["estado"] == "mala":
                assert x["horas_reducidas"] == 0 and x["motivo_reduccion"] == "ninguno"
            if x["motivo_reduccion"] in ("trabajo", "ambos"):
                assert x["horas_trabajo"] > 0
            if x["motivo_reduccion"] == "ninguno":
                assert x["horas_reducidas"] == 0
            else:
                assert x["horas_reducidas"] > 0

    # --- incidentes con tipo y castigos embebidos (MongoDB)
    tipos_cat = {t["id_tipo_incidente"]: t for t in COLECCIONES["tipos_incidente"]}
    sanc_cat = {x["id_sancion"]: x for x in COLECCIONES["sanciones"]}
    ids_castigo = []
    for i in COLECCIONES["incidentes"]:
        assert tipos_cat[i["tipo_incidente"]["id_tipo_incidente"]] == i["tipo_incidente"], "Tipo embebido distinto al catálogo"
        assert i["castigos"], "Todo incidente provoca al menos un castigo"
        reclusos = [c["id_recluso"] for c in i["castigos"]]
        assert len(reclusos) == len(set(reclusos)), "Un castigo por recluso en cada incidente"
        for c in i["castigos"]:
            r = rec[c["id_recluso"]]
            assert sanc_cat[c["sancion"]["id_sancion"]] == c["sancion"], "Sanción embebida distinta al catálogo"
            assert r["estatus"] in EN_CUSTODIA and i["fecha_incidente"] > r["ingreso"], "Castigo a recluso no presente"
            assert i["fecha_incidente"] < c["fecha_inicio"] <= HOY, "Fecha de inicio del castigo"
            assert c["fecha_inicio"] <= c["fecha_termino"], "Fecha de término del castigo"
            ids_castigo.append(c["id_castigo"])
    assert ids_castigo == list(range(1, len(ids_castigo) + 1)), "id_castigo consecutivo y único"

    # --- contactos
    assert all(c["id_recluso"] in rec for c in COLECCIONES["contactos_emergencia"])

    # --- visitas, ingresos y decomisos
    relacion = {}
    for v in TABLAS["visita"]["filas"]:
        r = rec[v["id_recluso"]]
        assert r["estatus"] in EN_CUSTODIA and v["fecha"] > r["ingreso"] and v["fecha"] < HOY
        assert v["fecha"].weekday() in DIAS_VISITA and v["hora_salida"] > v["hora_ingreso"]
        assert relacion.setdefault((v["id_visitante"], v["id_recluso"]), v["id_parentesco"]) == v["id_parentesco"], \
            "Un visitante tiene un solo parentesco con cada recluso"
    ing = {i["id_ingreso"]: i for i in COLECCIONES["ingresos"]}
    for i in ing.values():
        assert visitas[i["id_visita"]]["fecha"] == i["fecha_ingreso"]
    usados = set()
    for d in COLECCIONES["decomisos"]:
        i = ing[d["id_ingreso"]]
        assert d["articulo"] == i["articulo"] and d["fecha_decomiso"] == i["fecha_ingreso"]
        assert d["articulo"] in ARTICULOS_PROHIBIDOS and d["id_ingreso"] not in usados
        usados.add(d["id_ingreso"])
    assert sum(i["articulo"] in ARTICULOS_PROHIBIDOS for i in ing.values()) == len(COLECCIONES["decomisos"])

    # --- personal
    usuarios_emp = [e["id_usuario"] for e in TABLAS["empleado"]["filas"] if e["id_usuario"]]
    assert len(usuarios_emp) == len(set(usuarios_emp)), "Usuario repetido en empleado"
    emp = {e["id_empleado"]: e for e in EMPLEADOS}
    for a in TABLAS["asignacion_trabajo"]["filas"]:
        assert a["inicio_trabajo"] >= emp[a["id_empleado"]]["fecha_ingreso"]
    for c in TABLAS["consulta_medica"]["filas"]:
        assert emp[c["id_empleado"]]["puesto"] in PUESTOS_MEDICOS
        assert rec[c["id_recluso"]]["ingreso"] <= c["fecha"].date() <= HOY
        assert c["fecha"] >= datetime.combine(emp[c["id_empleado"]]["fecha_ingreso"], time())


# ---------------------------------------------------------------------
# Validaciones previas a escribir
# ---------------------------------------------------------------------
def validar():
    for nombre in CATALOGOS_MINIMO_15:
        n = len(TABLAS[nombre]["filas"])
        assert n >= MINIMO_CATALOGO, f"Catálogo {nombre} tiene {n} (< {MINIMO_CATALOGO})"
    for nombre in ("delitos", "tipos_incidente", "sanciones"):
        assert len(COLECCIONES[nombre]) >= MINIMO_CATALOGO, f"Catálogo {nombre} < {MINIMO_CATALOGO}"

    # Llaves foráneas: cada valor no nulo debe existir en la tabla referenciada
    for tabla, col, ref, col_ref in LLAVES_FORANEAS:
        if tabla not in TABLAS or ref not in TABLAS:
            continue
        existentes = {f[col_ref] for f in TABLAS[ref]["filas"]}
        for fila in TABLAS[tabla]["filas"]:
            valor = fila.get(col)
            assert valor is None or valor in existentes, f"FK rota: {tabla}.{col}={valor} -> {ref}"

    for u in TABLAS["usuario"]["filas"]:
        assert u["contrasena_hash"].startswith("$2b$") and len(u["contrasena_hash"]) == 60
    hashes = {u["contrasena_hash"] for u in TABLAS["usuario"]["filas"]}
    assert len(hashes) == len(TABLAS["usuario"]["filas"]), "Hashes repetidos"


# ---------------------------------------------------------------------
# Escritura: DML.sql (PostgreSQL) y seeds.json (MongoDB)
# ---------------------------------------------------------------------
def sql_valor(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, datetime):
        return f"'{v.strftime('%Y-%m-%d %H:%M:%S')}'"
    if isinstance(v, date):
        return f"'{v.isoformat()}'"
    if isinstance(v, time):
        return f"'{v.strftime('%H:%M:%S')}'"
    return "'" + str(v).replace("'", "''") + "'"


def escribir_dml(ruta):
    lineas = [
        "-- =====================================================================",
        "-- DML.sql  |  Datos sintéticos generados por seeder.py (semilla %d)" % SEMILLA,
        "-- Ejecutar DESPUÉS de DDL.sql. No editar a mano: regenerar con el seeder.",
        "-- =====================================================================",
        "BEGIN;", "",
    ]
    for nombre in ORDEN_CARGA:
        if nombre not in TABLAS:
            continue
        tabla = TABLAS[nombre]
        filas, pk = tabla["filas"], tabla["pk"]
        columnas = list(filas[0].keys())
        lineas.append(f"-- {nombre}: {len(filas)} registros")
        for i in range(0, len(filas), LOTE_INSERT):
            valores = ",\n".join(
                "  (" + ", ".join(sql_valor(f[c]) for c in columnas) + ")"
                for f in filas[i:i + LOTE_INSERT]
            )
            lineas.append(f"INSERT INTO {nombre} ({', '.join(columnas)}) VALUES\n{valores};")
        if pk:   # deja la secuencia del SERIAL lista para nuevos inserts
            lineas.append(
                f"SELECT setval(pg_get_serial_sequence('{nombre}', '{pk}'), (SELECT MAX({pk}) FROM {nombre}));"
            )
        lineas.append("")
    lineas.append("COMMIT;")
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def a_json(v):
    """Convierte a JSON extendido de MongoDB: las fechas pasan a {"$date": ...}."""
    if isinstance(v, datetime):
        return {"$date": v.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if isinstance(v, date):
        return {"$date": v.isoformat() + "T00:00:00Z"}
    if isinstance(v, dict):
        return {k: a_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [a_json(x) for x in v]
    return v


def escribir_json(ruta):
    """seeds.json (todo junto) y seeds/<colección>.json (arreglos, para mongoimport --jsonArray)."""
    contenido = {nombre: [a_json(d) for d in docs] for nombre, docs in COLECCIONES.items()}
    ruta.write_text(json.dumps(contenido, ensure_ascii=False, indent=1), encoding="utf-8")
    carpeta = ruta.parent / "seeds"
    carpeta.mkdir(exist_ok=True)
    for nombre, docs in contenido.items():
        (carpeta / f"{nombre}.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")


def resumen():
    print(f"\nTablas PostgreSQL ({len(TABLAS)}):")
    for nombre, t in TABLAS.items():
        print(f"  {nombre:<20}{len(t['filas']):>6}")
    print(f"\nColecciones MongoDB ({len(COLECCIONES)}):")
    for nombre, docs in COLECCIONES.items():
        print(f"  {nombre:<20}{len(docs):>6}")
    print(f"\nUsuarios de prueba: nombre del rol (p. ej. 'administrador') / contraseña '{CONTRASENA_PRUEBA}'")


# ---------------------------------------------------------------------
# Programa principal
# ---------------------------------------------------------------------
def main():
    aqui = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Generador de datos sintéticos del sistema penitenciario")
    parser.add_argument("--salida", default=None,
                        help="carpeta única para DML.sql y seeds.json "
                             "(por defecto: DML.sql junto al seeder y seeds.json en ../Mongo_noRelacional)")
    args = parser.parse_args()
    if args.salida:
        carpeta_pg = carpeta_mongo = Path(args.salida)
    else:
        carpeta_pg = aqui
        carpeta_mongo = aqui.parent / "Mongo_noRelacional"
        if not carpeta_mongo.is_dir():
            carpeta_mongo = aqui
    carpeta_pg.mkdir(parents=True, exist_ok=True)
    carpeta_mongo.mkdir(parents=True, exist_ok=True)

    generar_catalogos()
    generar_usuarios()
    generar_reclusos()
    generar_empleados()
    generar_asignaciones()
    generar_area_medica()
    generar_visitas()
    generar_sentencias()
    generar_traslados()
    generar_antecedentes()
    generar_bitacoras()
    generar_contactos()
    generar_incidentes()
    generar_ingresos_decomisos()

    validar()
    validar_datos()
    escribir_dml(carpeta_pg / "DML.sql")
    escribir_json(carpeta_mongo / "seeds.json")
    resumen()
    print(f"\nEscrito: {carpeta_pg / 'DML.sql'}\n         {carpeta_mongo / 'seeds.json'}\n         {carpeta_mongo / 'seeds'}{os.sep}<colección>.json")


if __name__ == "__main__":
    main()
