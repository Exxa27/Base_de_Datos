-- =====================================================================
-- DQL.sql  |  Sistema penitenciario  |  PostgreSQL
-- Vistas con JOINs y consultas de reporte. Ejecutar DESPUÉS de DDL.sql y DML.sql.
-- Se puede correr varias veces (elimina y recrea las vistas).
--
-- Nota: la capacidad de una celda depende de su tipo:
--   individual = 1, aislamiento = 1, enfermeria = 2, compartida = 4.
-- Los reclusos "liberado" y "trasladado" conservan su última celda en la tabla,
-- pero no ocupan lugar: la ocupación solo cuenta activo y hospitalizado.
-- =====================================================================

DROP VIEW IF EXISTS v_ocupacion_celdas;
DROP VIEW IF EXISTS v_historial_medico;
DROP VIEW IF EXISTS v_personal_asignado;
DROP VIEW IF EXISTS v_actividad_visitas;

-- =====================================================================
-- 1) Ocupación por sección y pabellón
-- =====================================================================
CREATE VIEW v_ocupacion_celdas AS
SELECT
    s.id_seccion,
    s.seccion,
    p.id_pabellon,
    p.pabellon,
    COUNT(DISTINCT c.id_celda)                                         AS celdas,
    SUM(cap.capacidad)                                        AS capacidad_total,
    COALESCE(SUM(oc.reclusos), 0)                                      AS reclusos_en_custodia,
    SUM(cap.capacidad) - COALESCE(SUM(oc.reclusos), 0)        AS lugares_disponibles,
    ROUND(100.0 * COALESCE(SUM(oc.reclusos), 0) / NULLIF(SUM(cap.capacidad), 0), 1)
                                                                       AS porcentaje_ocupacion
FROM seccion s
JOIN pabellon p ON p.id_seccion = s.id_seccion
JOIN celda c    ON c.id_pabellon = p.id_pabellon
CROSS JOIN LATERAL (
    SELECT CASE c.tipo_celda
               WHEN 'individual'  THEN 1
               WHEN 'aislamiento' THEN 1
               WHEN 'enfermeria'  THEN 2
               WHEN 'compartida'  THEN 4
           END AS capacidad
) cap
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS reclusos
    FROM recluso r
    WHERE r.id_celda = c.id_celda
      AND r.estatus IN ('activo', 'hospitalizado')
) oc ON TRUE
GROUP BY s.id_seccion, s.seccion, p.id_pabellon, p.pabellon;

COMMENT ON VIEW v_ocupacion_celdas IS
    'Capacidad, reclusos en custodia y porcentaje de ocupación por pabellón.';

-- =====================================================================
-- 2) Historial médico: una fila por consulta, con exámenes y recetas
-- =====================================================================
CREATE VIEW v_historial_medico AS
SELECT
    cm.id_consulta,
    cm.fecha                                  AS fecha_consulta,
    r.id_recluso,
    r.nombre                                  AS recluso,
    ex.alergias,
    ex.afecciones,
    d.diagnostico,
    cm.razon_consulta,
    sa.nombre                                 AS sala,
    e.nombre                                  AS atendio,
    pu.puesto                                 AS puesto_de_quien_atendio,
    COALESCE(exa.total_examenes, 0)           AS total_examenes,
    exa.examenes,
    COALESCE(rec.total_recetas, 0)            AS total_recetas,
    rec.medicamentos
FROM consulta_medica cm
JOIN recluso r       ON r.id_recluso     = cm.id_recluso
JOIN expediente ex   ON ex.id_expediente = cm.id_expediente
JOIN diagnostico d   ON d.id_diagnostico = cm.id_diagnostico
JOIN sala sa         ON sa.id_sala       = cm.id_sala
JOIN empleado e      ON e.id_empleado    = cm.id_empleado
LEFT JOIN asignacion_trabajo a ON a.id_empleado = e.id_empleado
LEFT JOIN puesto pu            ON pu.id_puesto  = a.id_puesto
LEFT JOIN (
    SELECT id_consulta,
           COUNT(*)                                          AS total_examenes,
           STRING_AGG(tipo_examen, '; ' ORDER BY id_examen)  AS examenes
    FROM examen
    GROUP BY id_consulta
) exa ON exa.id_consulta = cm.id_consulta
LEFT JOIN (
    SELECT id_consulta,
           COUNT(*)                                          AS total_recetas,
           STRING_AGG(medicamento, '; ' ORDER BY id_receta)  AS medicamentos
    FROM receta
    GROUP BY id_consulta
) rec ON rec.id_consulta = cm.id_consulta;

COMMENT ON VIEW v_historial_medico IS
    'Una fila por consulta médica con diagnóstico, sala, personal, exámenes y recetas.';

-- =====================================================================
-- 3) Personal con puesto, turno, lugar de trabajo y acceso al sistema
-- =====================================================================
CREATE VIEW v_personal_asignado AS
SELECT
    e.id_empleado,
    e.nombre,
    e.estado,
    e.fecha_ingreso,
    e.sueldo,
    pu.puesto,
    t.turno,
    t.dias,
    t.hora_inicio,
    t.hora_salida,
    COALESCE(sa.nombre, se.seccion)           AS lugar_de_trabajo,
    CASE WHEN a.id_sala IS NOT NULL THEN 'sala' ELSE 'sección' END AS tipo_de_lugar,
    rc.nombre                                 AS recluso_asignado,
    u.nombre_usuario,
    ro.rol                                    AS rol_en_sistema,
    u.estatus                                 AS estatus_usuario
FROM empleado e
JOIN asignacion_trabajo a ON a.id_empleado = e.id_empleado
JOIN puesto pu            ON pu.id_puesto  = a.id_puesto
JOIN turno t              ON t.id_turno    = a.id_turno
LEFT JOIN sala sa         ON sa.id_sala    = a.id_sala
LEFT JOIN seccion se      ON se.id_seccion = a.id_seccion
LEFT JOIN recluso rc      ON rc.id_recluso = a.id_recluso
LEFT JOIN usuario u       ON u.id_usuario  = e.id_usuario
LEFT JOIN rol ro          ON ro.id_rol     = u.id_rol;

COMMENT ON VIEW v_personal_asignado IS
    'Empleados con puesto, turno, lugar de trabajo y, si tienen, su usuario y rol.';

-- =====================================================================
-- 4) Actividad de visitas por recluso
-- =====================================================================
CREATE VIEW v_actividad_visitas AS
SELECT
    r.id_recluso,
    r.nombre                                           AS recluso,
    r.estatus,
    COUNT(v.id_visita)                                 AS total_visitas,
    COUNT(DISTINCT v.id_visitante)                     AS visitantes_distintos,
    MIN(v.fecha)                                       AS primera_visita,
    MAX(v.fecha)                                       AS ultima_visita,
    ROUND(AVG(EXTRACT(EPOCH FROM (v.hora_salida - v.hora_ingreso)) / 60) FILTER
          (WHERE v.hora_salida IS NOT NULL), 0)        AS minutos_promedio,
    STRING_AGG(DISTINCT pa.parentesco, ', ')           AS parentescos
FROM recluso r
LEFT JOIN visita v       ON v.id_recluso    = r.id_recluso
LEFT JOIN parentesco pa  ON pa.id_parentesco = v.id_parentesco
GROUP BY r.id_recluso, r.nombre, r.estatus;

COMMENT ON VIEW v_actividad_visitas IS
    'Total de visitas, visitantes distintos, fechas y parentescos por recluso (incluye reclusos sin visitas).';

-- =====================================================================
-- CONSULTAS DE REPORTE (usan las vistas anteriores)
-- =====================================================================

-- R1. Pabellones con ocupación mayor a 80 %
SELECT seccion, pabellon, capacidad_total, reclusos_en_custodia, porcentaje_ocupacion
FROM v_ocupacion_celdas
WHERE porcentaje_ocupacion > 80
ORDER BY porcentaje_ocupacion DESC, seccion, pabellon;

-- R2. Diagnósticos más frecuentes en los últimos 12 meses
SELECT diagnostico,
       COUNT(*)                         AS consultas,
       COUNT(DISTINCT id_recluso)       AS reclusos_atendidos,
       SUM(total_recetas)               AS recetas_emitidas
FROM v_historial_medico
WHERE fecha_consulta >= (CURRENT_DATE - INTERVAL '12 months')
GROUP BY diagnostico
ORDER BY consultas DESC
LIMIT 10;

-- R3. Personal activo por puesto y turno, con sueldo promedio
SELECT puesto,
       turno,
       COUNT(*)                         AS empleados,
       ROUND(AVG(sueldo), 2)            AS sueldo_promedio
FROM v_personal_asignado
WHERE estado = 'activo'
GROUP BY puesto, turno
ORDER BY puesto, empleados DESC;

-- R4. Reclusos en custodia que nunca han recibido una visita
SELECT id_recluso, recluso, estatus
FROM v_actividad_visitas
WHERE total_visitas = 0
  AND estatus IN ('activo', 'hospitalizado')
ORDER BY id_recluso;

-- R5. Los 10 reclusos con más visitas
SELECT recluso, total_visitas, visitantes_distintos, ultima_visita, parentescos
FROM v_actividad_visitas
ORDER BY total_visitas DESC, ultima_visita DESC
LIMIT 10;
