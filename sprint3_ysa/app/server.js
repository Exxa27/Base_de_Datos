// API de solo lectura para La Penal (PostgreSQL + MongoDB). Uso: npm install && npm start
const express = require('express');
const path = require('path');
const { Pool, types } = require('pg');
const { MongoClient } = require('mongodb');

types.setTypeParser(1082, (v) => v); // DATE como texto (evita corrimientos de zona horaria)

const pool = new Pool({
  host: process.env.PGHOST || 'localhost',
  port: +(process.env.PGPORT || 5432),
  user: process.env.PGUSER || 'postgres',
  password: process.env.PGPASSWORD || undefined,
  database: 'la_penal',
});
const mongo = new MongoClient(process.env.MONGO_URI || 'mongodb://localhost:27017');
const mdb = () => mongo.db('la_penal');

const app = express();
app.use(express.static(path.join(__dirname, 'public')));
const ruta = (f) => (req, res) => f(req, res).catch((e) => res.status(500).json({ error: e.message }));
const sql = async (q, p = []) => (await pool.query(q, p)).rows;

// Reportes de DQL.sql (R1-R5)
const REPORTES = {
  r1: ['Pabellones con ocupación > 80 %', `SELECT seccion, pabellon, capacidad_total, reclusos_en_custodia, porcentaje_ocupacion FROM v_ocupacion_celdas WHERE porcentaje_ocupacion > 80 ORDER BY porcentaje_ocupacion DESC, seccion, pabellon`],
  r2: ['Diagnósticos más frecuentes (12 meses)', `SELECT diagnostico, COUNT(*) AS consultas, COUNT(DISTINCT id_recluso) AS reclusos_atendidos, SUM(total_recetas) AS recetas_emitidas FROM v_historial_medico WHERE fecha_consulta >= (CURRENT_DATE - INTERVAL '12 months') GROUP BY diagnostico ORDER BY consultas DESC LIMIT 10`],
  r3: ['Personal activo por puesto y turno', `SELECT puesto, turno, COUNT(*) AS empleados, ROUND(AVG(sueldo), 2) AS sueldo_promedio FROM v_personal_asignado WHERE estado = 'activo' GROUP BY puesto, turno ORDER BY puesto, empleados DESC`],
  r4: ['Reclusos en custodia sin visitas', `SELECT id_recluso, recluso, estatus FROM v_actividad_visitas WHERE total_visitas = 0 AND estatus IN ('activo','hospitalizado') ORDER BY id_recluso`],
  r5: ['Top 10 reclusos con más visitas', `SELECT recluso, total_visitas, visitantes_distintos, ultima_visita, parentescos FROM v_actividad_visitas ORDER BY total_visitas DESC, ultima_visita DESC LIMIT 10`],
};
app.get('/api/reportes', ruta(async (_q, res) => res.json(Object.entries(REPORTES).map(([id, [titulo]]) => ({ id, titulo })))));
app.get('/api/reportes/:id', ruta(async (req, res) => {
  const r = REPORTES[req.params.id];
  if (!r) return res.status(404).json({ error: 'Reporte no existe' });
  res.json(await sql(r[1]));
}));

// Tablas y vistas de PostgreSQL (lista blanca tomada de information_schema)
const tablasPg = async () => (await sql(`SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_type, table_name`)).map((t) => t.table_name);
app.get('/api/tablas', ruta(async (_q, res) => res.json(await tablasPg())));
app.get('/api/tablas/:n', ruta(async (req, res) => {
  if (!(await tablasPg()).includes(req.params.n)) return res.status(404).json({ error: 'Tabla no existe' });
  res.json(await sql(`SELECT * FROM "${req.params.n}" LIMIT 500`));
}));

// Colecciones de MongoDB
const colsMongo = async () => (await mdb().listCollections().toArray()).map((c) => c.name).sort();
app.get('/api/mongo', ruta(async (_q, res) => res.json(await colsMongo())));
app.get('/api/mongo/:c', ruta(async (req, res) => {
  if (!(await colsMongo()).includes(req.params.c)) return res.status(404).json({ error: 'Colección no existe' });
  res.json(await mdb().collection(req.params.c).find({}, { projection: { _id: 0 } }).limit(300).toArray());
}));

// Búsqueda de reclusos y ficha combinada (PostgreSQL + MongoDB)
app.get('/api/reclusos', ruta(async (req, res) => {
  const q = String(req.query.q || '').trim();
  res.json(await sql(`SELECT id_recluso, nombre, estatus FROM recluso WHERE nombre ILIKE $1 OR id_recluso::text = $2 ORDER BY nombre LIMIT 50`, [`%${q}%`, q]));
}));
app.get('/api/recluso/:id', ruta(async (req, res) => {
  const id = parseInt(req.params.id, 10);
  const [recluso] = await sql(`SELECT r.*, c.numero_celda, c.tipo_celda, p.pabellon, s.seccion FROM recluso r JOIN celda c ON c.id_celda = r.id_celda JOIN pabellon p ON p.id_pabellon = c.id_pabellon JOIN seccion s ON s.id_seccion = p.id_seccion WHERE r.id_recluso = $1`, [id]);
  if (!recluso) return res.status(404).json({ error: 'Recluso no encontrado' });
  const m = mdb(), por = { id_recluso: id }, sinId = { projection: { _id: 0 } };
  const [visitas, consultas, sentencias, antecedentes, bitacora, traslados, contactos, incidentes] = await Promise.all([
    sql(`SELECT v.fecha, vi.nombre AS visitante, pa.parentesco, v.razon_visita FROM visita v JOIN visitante vi ON vi.id_visitante = v.id_visitante JOIN parentesco pa ON pa.id_parentesco = v.id_parentesco WHERE v.id_recluso = $1 ORDER BY v.fecha DESC LIMIT 20`, [id]),
    sql(`SELECT fecha_consulta, diagnostico, razon_consulta, sala, atendio, examenes, medicamentos FROM v_historial_medico WHERE id_recluso = $1 ORDER BY fecha_consulta DESC`, [id]),
    m.collection('sentencias').find(por, sinId).toArray(),
    m.collection('antecedentes').findOne(por, sinId),
    m.collection('bitacoras').findOne(por, sinId),
    m.collection('traslados').find(por, sinId).toArray(),
    m.collection('contactos_emergencia').find(por, sinId).toArray(),
    m.collection('incidentes').find({ 'castigos.id_recluso': id }, sinId).toArray(),
  ]);
  const castigos = incidentes.flatMap((i) => i.castigos.filter((c) => c.id_recluso === id).map((c) => ({
    fecha_incidente: i.fecha_incidente, incidente: i.tipo_incidente.incidente, descripcion: i.descripcion,
    sancion: c.sancion.sancion, fecha_inicio: c.fecha_inicio, fecha_termino: c.fecha_termino })));
  res.json({
    recluso,
    sentencias: sentencias.map((s) => ({ sentencia: s.sentencia, estado: s.estado, inicio: s.inicio_condena, termino: s.termino_condena, delito: s.delito.delito, tipo_delito: s.delito.tipo_delito, fianza: s.fianza ? s.fianza.monto : null })),
    antecedentes: antecedentes ? { reincidente: antecedentes.reincidente, cargos_previos: antecedentes.cargos_previos } : null,
    bitacora: bitacora ? { estado_actual: bitacora.estado_actual, total_horas_trabajo: bitacora.total_horas_trabajo, total_horas_reducidas: bitacora.total_horas_reducidas, registros: bitacora.registros } : null,
    traslados, contactos, castigos, visitas, consultas,
  });
}));

const PUERTO = process.env.PORT || 3000;
mongo.connect().then(() => app.listen(PUERTO, () => console.log(`La Penal en http://localhost:${PUERTO}`)))
  .catch((e) => { console.error('No se pudo conectar a MongoDB:', e.message); process.exit(1); });
