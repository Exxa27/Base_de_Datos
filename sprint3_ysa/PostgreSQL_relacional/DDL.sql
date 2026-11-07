-- =====================================================================
-- DDL.sql  |  Sistema penitenciario  |  PostgreSQL (parte relacional)
-- 22 tablas. La administración de reclusos, los ingresos, los decomisos y todo el
-- módulo de sanciones (tipos de incidente, sanciones, incidentes y castigos) viven
-- en MongoDB (ver Desacople_aMongo.js). Las colecciones de Mongo referencian por
-- entero: id_recluso, id_celda, id_visita (sin FK real entre motores).
-- =====================================================================

-- Reinicio limpio (orden inverso a las dependencias)
DROP TABLE IF EXISTS
    receta, examen, consulta_medica, expediente, diagnostico, sala,
    asignacion_trabajo, empleado, turno, puesto,
    visita, visitante, domicilio, parentesco,
    recluso, celda, pabellon, seccion,
    -- tablas de versiones anteriores del esquema (hoy viven en MongoDB)
    castigo, incidente, sancion, tipo_incidente,
    usuario, rol_permiso, rol, permiso
CASCADE;

-- =====================================================================
-- MÓDULO SISTEMA
-- =====================================================================
CREATE TABLE permiso (
    id_permiso   SERIAL PRIMARY KEY,
    permiso      VARCHAR(60)  NOT NULL UNIQUE,
    descripcion  VARCHAR(255) NOT NULL
);

CREATE TABLE rol (
    id_rol       SERIAL PRIMARY KEY,
    rol          VARCHAR(60)  NOT NULL UNIQUE,
    descripcion  VARCHAR(255) NOT NULL
);

-- Relación "Tiene permisos" (N:M)
CREATE TABLE rol_permiso (
    id_rol      INT NOT NULL REFERENCES rol(id_rol)         ON DELETE CASCADE,
    id_permiso  INT NOT NULL REFERENCES permiso(id_permiso) ON DELETE CASCADE,
    PRIMARY KEY (id_rol, id_permiso)
);

CREATE TABLE usuario (
    id_usuario        SERIAL PRIMARY KEY,
    id_rol            INT NOT NULL REFERENCES rol(id_rol),
    nombre_usuario    VARCHAR(50)  NOT NULL UNIQUE,
    contrasena_hash   VARCHAR(100) NOT NULL,            -- bcrypt ($2b$...)
    estatus           VARCHAR(10)  NOT NULL DEFAULT 'activo'
                      CHECK (estatus IN ('activo','inactivo','bloqueado')),
    fecha_registro    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- =====================================================================
-- MÓDULO INFRAESTRUCTURA
-- =====================================================================
CREATE TABLE seccion (
    id_seccion  SERIAL PRIMARY KEY,
    seccion     VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE pabellon (
    id_pabellon  SERIAL PRIMARY KEY,
    id_seccion   INT NOT NULL REFERENCES seccion(id_seccion),   -- "Ubicado en"
    pabellon     VARCHAR(60) NOT NULL,
    UNIQUE (id_seccion, pabellon)
);

CREATE TABLE celda (
    id_celda        SERIAL PRIMARY KEY,
    id_pabellon     INT NOT NULL REFERENCES pabellon(id_pabellon), -- "Pertenece a"
    numero_celda    INT NOT NULL CHECK (numero_celda > 0),
    tipo_celda      VARCHAR(20) NOT NULL
                    CHECK (tipo_celda IN ('individual','compartida','aislamiento','enfermeria')),
    UNIQUE (id_pabellon, numero_celda)
);

-- =====================================================================
-- NÚCLEO: RECLUSO
-- =====================================================================
CREATE TABLE recluso (
    id_recluso         SERIAL PRIMARY KEY,
    id_celda           INT NOT NULL REFERENCES celda(id_celda),   -- "Se encuentra en"
    nombre             VARCHAR(120) NOT NULL,
    sexo               CHAR(1) NOT NULL CHECK (sexo IN ('M','F','O')),
    fecha_nacimiento   DATE NOT NULL,
    fecha_ingreso      DATE NOT NULL,
    estatus            VARCHAR(15) NOT NULL DEFAULT 'activo'
                       CHECK (estatus IN ('activo','liberado','trasladado','hospitalizado')),
    CHECK (fecha_ingreso >= fecha_nacimiento)
);

-- =====================================================================
-- MÓDULO TRABAJADORES
-- =====================================================================
CREATE TABLE puesto (
    id_puesto  SERIAL PRIMARY KEY,
    puesto     VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE turno (
    id_turno      SERIAL PRIMARY KEY,
    turno         VARCHAR(40) NOT NULL UNIQUE,
    dias          VARCHAR(60) NOT NULL,
    hora_inicio   TIME NOT NULL,
    hora_salida   TIME NOT NULL
);

CREATE TABLE empleado (
    id_empleado     SERIAL PRIMARY KEY,
    id_usuario      INT UNIQUE REFERENCES usuario(id_usuario),     -- "En el sistema es"
    nombre          VARCHAR(120) NOT NULL,
    fecha_ingreso   DATE NOT NULL,
    sueldo          NUMERIC(10,2) NOT NULL CHECK (sueldo > 0),
    estado          VARCHAR(15) NOT NULL DEFAULT 'activo'
                    CHECK (estado IN ('activo','vacaciones','licencia','baja'))
);

-- Une empleado + puesto + turno + lugar de trabajo
CREATE TABLE asignacion_trabajo (
    id_asignacion     SERIAL PRIMARY KEY,
    id_empleado       INT NOT NULL REFERENCES empleado(id_empleado),   -- "Trabajará en"
    id_puesto         INT NOT NULL REFERENCES puesto(id_puesto),       -- "Trabaja de"
    id_turno          INT NOT NULL REFERENCES turno(id_turno),         -- "Trabajará durante"
    id_seccion        INT REFERENCES seccion(id_seccion),              -- "Lugar de trabajo"
    id_sala           INT,                                             -- "Lugar de trabajo" (FK abajo)
    id_recluso        INT REFERENCES recluso(id_recluso),              -- "Lugar asignado"
    registro          VARCHAR(120),
    inicio_trabajo    DATE NOT NULL,
    CHECK (id_seccion IS NOT NULL OR id_sala IS NOT NULL)
);

-- =====================================================================
-- MÓDULO ÁREA MÉDICA
-- =====================================================================
CREATE TABLE sala (
    id_sala    SERIAL PRIMARY KEY,
    nombre     VARCHAR(60) NOT NULL UNIQUE,
    camillas   INT NOT NULL CHECK (camillas >= 0),
    ocupadas   INT NOT NULL DEFAULT 0,
    CHECK (ocupadas BETWEEN 0 AND camillas)
);

ALTER TABLE asignacion_trabajo
    ADD CONSTRAINT fk_asignacion_sala FOREIGN KEY (id_sala) REFERENCES sala(id_sala);

CREATE TABLE diagnostico (
    id_diagnostico  SERIAL PRIMARY KEY,
    diagnostico     VARCHAR(120) NOT NULL UNIQUE
);

CREATE TABLE expediente (
    id_expediente  SERIAL PRIMARY KEY,
    id_recluso     INT NOT NULL UNIQUE REFERENCES recluso(id_recluso),
    expediente     VARCHAR(255) NOT NULL,
    alergias       VARCHAR(255) NOT NULL DEFAULT 'ninguna',
    afecciones     VARCHAR(255) NOT NULL DEFAULT 'ninguna'
);

CREATE TABLE consulta_medica (
    id_consulta      SERIAL PRIMARY KEY,
    id_recluso       INT NOT NULL REFERENCES recluso(id_recluso),       -- "Tomó"
    id_empleado      INT NOT NULL REFERENCES empleado(id_empleado),
    id_expediente    INT NOT NULL REFERENCES expediente(id_expediente), -- "Se consultó"
    id_sala          INT NOT NULL REFERENCES sala(id_sala),             -- "Se realiza"
    id_diagnostico   INT NOT NULL REFERENCES diagnostico(id_diagnostico), -- "Se practicó"
    razon_consulta   VARCHAR(255) NOT NULL,
    fecha            TIMESTAMP NOT NULL
);

CREATE TABLE examen (
    id_examen        SERIAL PRIMARY KEY,
    id_consulta      INT NOT NULL REFERENCES consulta_medica(id_consulta),
    id_diagnostico   INT REFERENCES diagnostico(id_diagnostico),        -- "Se realizaron"
    tipo_examen      VARCHAR(80) NOT NULL,
    observaciones    VARCHAR(255)
);

CREATE TABLE receta (
    id_receta          SERIAL PRIMARY KEY,
    id_consulta        INT NOT NULL REFERENCES consulta_medica(id_consulta), -- "Se recetó"
    medicamento        VARCHAR(100) NOT NULL,
    indicacion_medica  VARCHAR(255) NOT NULL
);

-- =====================================================================
-- MÓDULO SANCIONES: vive completo en MongoDB (Desacople_aMongo.js)
--   tipos_incidente -> incidentes -> castigos <- sanciones
--   castigos.id_recluso referencia a recluso (sin FK real entre motores)
-- =====================================================================

-- =====================================================================
-- MÓDULO VISITAS (ingresos y decomisos van a MongoDB)
-- =====================================================================
CREATE TABLE parentesco (
    id_parentesco  SERIAL PRIMARY KEY,
    parentesco     VARCHAR(40) NOT NULL UNIQUE
);

CREATE TABLE domicilio (
    id_domicilio  SERIAL PRIMARY KEY,
    direccion     VARCHAR(150) NOT NULL,
    ciudad        VARCHAR(80)  NOT NULL,
    estado        VARCHAR(80)  NOT NULL
);

CREATE TABLE visitante (
    id_visitante  SERIAL PRIMARY KEY,
    id_domicilio  INT NOT NULL REFERENCES domicilio(id_domicilio),  -- "Se puede encontrar en"
    nombre        VARCHAR(120) NOT NULL
);

CREATE TABLE visita (
    id_visita       SERIAL PRIMARY KEY,
    id_recluso      INT NOT NULL REFERENCES recluso(id_recluso),     -- "Visita a"
    id_visitante    INT NOT NULL REFERENCES visitante(id_visitante), -- "Viene a"
    id_parentesco   INT NOT NULL REFERENCES parentesco(id_parentesco), -- "Lo conoce de"
    razon_visita    VARCHAR(150) NOT NULL,
    fecha           DATE NOT NULL,
    hora_ingreso    TIME NOT NULL,
    hora_salida     TIME,
    CHECK (hora_salida IS NULL OR hora_salida > hora_ingreso)
);

-- =====================================================================
-- ÍNDICES sobre llaves foráneas de alto volumen
-- =====================================================================
CREATE INDEX idx_usuario_rol         ON usuario(id_rol);
CREATE INDEX idx_recluso_celda       ON recluso(id_celda);
CREATE INDEX idx_asignacion_empleado ON asignacion_trabajo(id_empleado);
CREATE INDEX idx_consulta_recluso    ON consulta_medica(id_recluso);
CREATE INDEX idx_consulta_empleado   ON consulta_medica(id_empleado);
CREATE INDEX idx_consulta_fecha      ON consulta_medica(fecha);
CREATE INDEX idx_examen_consulta     ON examen(id_consulta);
CREATE INDEX idx_receta_consulta     ON receta(id_consulta);
CREATE INDEX idx_visita_recluso      ON visita(id_recluso);
CREATE INDEX idx_visita_visitante    ON visita(id_visitante);
CREATE INDEX idx_visita_fecha        ON visita(fecha);
