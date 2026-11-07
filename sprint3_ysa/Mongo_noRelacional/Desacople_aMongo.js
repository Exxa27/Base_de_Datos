// =====================================================================
// Desacople_aMongo.js  |  Sistema penitenciario  |  MongoDB (parte no relacional)
// Uso:  mongosh --file Desacople_aMongo.js   (base de datos: la_penal)
//
// 11 colecciones:
//   administración de reclusos: traslados, sentencias (con delito y fianza
//   embebidos), delitos (catálogo), antecedentes (reincidencia y cargos
//   previos), bitacoras, contactos_emergencia
//   visitas: ingresos, decomisos
//   sanciones: tipos_incidente y sanciones (catálogos) e incidentes, con el tipo y los
//     castigos embebidos (cada castigo lleva su sanción y el id del recluso castigado)
//
// Las referencias a PostgreSQL son enteros sin FK real entre motores:
//   id_recluso, id_celda_origen, id_celda_nueva, id_visita
// El seeder garantiza la coherencia generando primero lo relacional.
// =====================================================================

const bd = db.getSiblingDB("la_penal");

// Reinicio limpio
[
  "traslados", "sentencias", "delitos", "antecedentes", "bitacoras", "contactos_emergencia",
  "ingresos", "decomisos", "tipos_incidente", "sanciones", "incidentes",
].forEach((c) => bd.getCollection(c).drop());

// Atajos para el validador
const num = { bsonType: "number" };                       // int, long o double
const entero = (min) => ({ bsonType: "number", minimum: min });
const texto = (max) => ({ bsonType: "string", minLength: 1, maxLength: max });
const fecha = { bsonType: "date" };

function crear(nombre, requeridos, propiedades) {
  bd.createCollection(nombre, {
    validator: {
      $jsonSchema: {
        bsonType: "object",
        required: requeridos,
        properties: propiedades,
      },
    },
    validationLevel: "strict",
    validationAction: "error",
  });
}

// ---------------------------------------------------------------------
// delitos (catálogo)
// ---------------------------------------------------------------------
crear("delitos", ["id_delito", "tipo_delito", "delito", "descripcion_delito"], {
  id_delito: entero(1),
  tipo_delito: texto(60),
  delito: texto(100),
  descripcion_delito: texto(255),
});

// ---------------------------------------------------------------------
// sentencias: delito y fianza embebidos
// ---------------------------------------------------------------------
crear(
  "sentencias",
  ["id_sentencia", "id_recluso", "sentencia", "inicio_condena", "termino_condena", "estado", "delito"],
  {
    id_sentencia: entero(1),
    id_recluso: entero(1),                                // -> PostgreSQL recluso
    sentencia: texto(150),
    inicio_condena: fecha,
    termino_condena: fecha,
    estado: { enum: ["vigente", "cumplida", "suspendida", "apelada"] },
    delito: {                                             // "Cometió" (snapshot del catálogo)
      bsonType: "object",
      required: ["id_delito", "tipo_delito", "delito", "descripcion_delito"],
      properties: {
        id_delito: entero(1),
        tipo_delito: texto(60),
        delito: texto(100),
        descripcion_delito: texto(255),
      },
    },
    fianza: {                                             // opcional: "Se perdona con"
      bsonType: "object",
      required: ["id_fianza", "monto", "telefono", "acreedores"],
      properties: {
        id_fianza: entero(1),
        monto: { bsonType: "number", minimum: 0 },
        telefono: texto(20),
        acreedores: { bsonType: "array", minItems: 1, items: texto(120) },
      },
    },
  }
);

// ---------------------------------------------------------------------
// traslados
// ---------------------------------------------------------------------
crear(
  "traslados",
  ["id_traslado", "id_recluso", "razon_traslado", "id_celda_origen", "id_celda_nueva", "fecha_traslado"],
  {
    id_traslado: entero(1),
    id_recluso: entero(1),
    razon_traslado: texto(255),
    id_celda_origen: entero(1),                           // -> PostgreSQL celda
    id_celda_nueva: entero(1),                            // -> PostgreSQL celda
    fecha_traslado: fecha,
  }
);

// ---------------------------------------------------------------------
// bitacoras: un documento por recluso con sus registros embebidos.
// Cada registro representa un periodo (mensual) y las horas que redujo,
// ya sea por trabajo, por buena conducta o por ambos.
// Reglas que cumple el seeder:
//   - total_horas_trabajo y total_horas_reducidas = suma de los registros
//   - estado "mala"  -> horas_reducidas = 0 y motivo_reduccion = "ninguno"
//   - motivo "trabajo" o "ambos" -> horas_trabajo > 0
//   - estado_actual = estado del registro más reciente
// ---------------------------------------------------------------------
crear(
  "bitacoras",
  ["id_bitacora", "id_recluso", "estado_actual", "total_horas_trabajo", "total_horas_reducidas",
   "registros", "fecha_actualizacion"],
  {
    id_bitacora: entero(1),
    id_recluso: entero(1),                                // -> PostgreSQL recluso (uno a uno)
    estado_actual: { enum: ["buena", "regular", "mala"] },
    total_horas_trabajo: entero(0),
    total_horas_reducidas: entero(0),
    registros: {
      bsonType: "array",
      minItems: 1,
      items: {
        bsonType: "object",
        required: ["fecha", "estado", "horas_trabajo", "horas_reducidas", "motivo_reduccion"],
        properties: {
          fecha: fecha,                                   // cierre del periodo
          estado: { enum: ["buena", "regular", "mala"] },
          horas_trabajo: entero(0),
          horas_reducidas: entero(0),
          motivo_reduccion: { enum: ["trabajo", "buena_conducta", "ambos", "ninguno"] },
          observaciones: texto(255),
        },
      },
    },
    fecha_actualizacion: fecha,
  }
);

// ---------------------------------------------------------------------
// antecedentes: un documento por recluso con su historial penal previo.
// Regla que cumple el seeder: reincidente = true si y solo si hay al menos
// un antecedente con resolucion "condenado" o "libertad_condicional".
// ---------------------------------------------------------------------
crear(
  "antecedentes",
  ["id_antecedente", "id_recluso", "reincidente", "total_cargos_previos", "cargos_previos", "fecha_actualizacion"],
  {
    id_antecedente: entero(1),
    id_recluso: entero(1),                                // -> PostgreSQL recluso (uno a uno)
    reincidente: { bsonType: "bool" },
    total_cargos_previos: entero(0),
    cargos_previos: {
      bsonType: "array",
      items: {
        bsonType: "object",
        required: ["id_delito", "tipo_delito", "delito", "fecha_cargo", "autoridad", "resolucion"],
        properties: {
          id_delito: entero(1),                           // -> catálogo delitos
          tipo_delito: texto(60),
          delito: texto(100),
          fecha_cargo: fecha,
          autoridad: texto(120),                          // juzgado o fiscalía
          resolucion: { enum: ["condenado", "absuelto", "sobreseido", "libertad_condicional"] },
          condena_meses: entero(0),
          lugar_reclusion: texto(120),
          fecha_liberacion: fecha,
        },
      },
    },
    observaciones: texto(255),
    fecha_actualizacion: fecha,
  }
);

// ---------------------------------------------------------------------
// contactos_emergencia
// ---------------------------------------------------------------------
crear("contactos_emergencia", ["id_contacto", "id_recluso", "nombre", "telefono", "parentesco"], {
  id_contacto: entero(1),
  id_recluso: entero(1),
  nombre: texto(120),
  telefono: texto(20),
  parentesco: texto(40),
});

// ---------------------------------------------------------------------
// ingresos: objetos con los que entra una visita
// ---------------------------------------------------------------------
crear("ingresos", ["id_ingreso", "id_visita", "articulo", "descripcion_articulos", "fecha_ingreso"], {
  id_ingreso: entero(1),
  id_visita: entero(1),                                   // -> PostgreSQL visita
  articulo: texto(100),
  descripcion_articulos: texto(255),
  fecha_ingreso: fecha,
});

// ---------------------------------------------------------------------
// decomisos: artículos con los que no se puede entrar
// ---------------------------------------------------------------------
crear("decomisos", ["id_decomiso", "id_ingreso", "articulo", "fecha_decomiso"], {
  id_decomiso: entero(1),
  id_ingreso: entero(1),                                  // -> ingresos
  articulo: texto(100),
  motivo: texto(255),
  fecha_decomiso: fecha,
});

// ---------------------------------------------------------------------
// MÓDULO SANCIONES
//   tipos_incidente y sanciones: catálogos (la sentencia/incidente guarda una copia)
//   incidentes: tipo_incidente embebido + castigos[] embebidos; cada castigo lleva su
//   sanción y el id_recluso (-> PostgreSQL). Un recluso aparece una sola vez por incidente
//   (regla que cumple el seeder; un índice no puede imponerla dentro de un arreglo).
// ---------------------------------------------------------------------
crear("tipos_incidente", ["id_tipo_incidente", "incidente", "descripcion"], {
  id_tipo_incidente: entero(1),
  incidente: texto(80),
  descripcion: texto(255),
});

crear("sanciones", ["id_sancion", "sancion", "descripcion"], {
  id_sancion: entero(1),
  sancion: texto(80),
  descripcion: texto(255),
});

crear(
  "incidentes",
  ["id_incidente", "tipo_incidente", "fecha_incidente", "descripcion", "castigos"],
  {
    id_incidente: entero(1),
    tipo_incidente: {                                     // "Que pertenece fue" (copia del catálogo)
      bsonType: "object",
      required: ["id_tipo_incidente", "incidente", "descripcion"],
      properties: {
        id_tipo_incidente: entero(1),
        incidente: texto(80),
        descripcion: texto(255),
      },
    },
    fecha_incidente: fecha,
    descripcion: texto(255),
    castigos: {                                           // "Que provocó el castigo": uno por recluso involucrado
      bsonType: "array",
      minItems: 1,
      items: {
        bsonType: "object",
        required: ["id_castigo", "id_recluso", "sancion", "fecha_inicio", "fecha_termino"],
        properties: {
          id_castigo: entero(1),
          id_recluso: entero(1),                          // "A quién se le da el castigo" -> PostgreSQL recluso
          sancion: {                                      // "Se castigará con" (copia del catálogo)
            bsonType: "object",
            required: ["id_sancion", "sancion", "descripcion"],
            properties: {
              id_sancion: entero(1),
              sancion: texto(80),
              descripcion: texto(255),
            },
          },
          fecha_inicio: fecha,
          fecha_termino: fecha,
        },
      },
    },
  }
);

// =====================================================================
// ÍNDICES
// =====================================================================
// Identificadores únicos
bd.delitos.createIndex({ id_delito: 1 }, { unique: true });
bd.sentencias.createIndex({ id_sentencia: 1 }, { unique: true });
bd.traslados.createIndex({ id_traslado: 1 }, { unique: true });
bd.bitacoras.createIndex({ id_bitacora: 1 }, { unique: true });
bd.bitacoras.createIndex({ id_recluso: 1 }, { unique: true });      // un documento por recluso
bd.bitacoras.createIndex({ estado_actual: 1 });
bd.bitacoras.createIndex({ "registros.fecha": -1 });
bd.contactos_emergencia.createIndex({ id_contacto: 1 }, { unique: true });
bd.ingresos.createIndex({ id_ingreso: 1 }, { unique: true });
bd.decomisos.createIndex({ id_decomiso: 1 }, { unique: true });
bd.antecedentes.createIndex({ id_antecedente: 1 }, { unique: true });
bd.antecedentes.createIndex({ id_recluso: 1 }, { unique: true });   // un documento por recluso
bd.antecedentes.createIndex({ reincidente: 1 });
bd.antecedentes.createIndex({ "cargos_previos.id_delito": 1 });

// Sanciones
bd.tipos_incidente.createIndex({ id_tipo_incidente: 1 }, { unique: true });
bd.tipos_incidente.createIndex({ incidente: 1 }, { unique: true });
bd.sanciones.createIndex({ id_sancion: 1 }, { unique: true });
bd.sanciones.createIndex({ sancion: 1 }, { unique: true });
bd.incidentes.createIndex({ id_incidente: 1 }, { unique: true });
bd.incidentes.createIndex({ "castigos.id_castigo": 1 }, { unique: true });
bd.incidentes.createIndex({ "tipo_incidente.id_tipo_incidente": 1, fecha_incidente: -1 });
bd.incidentes.createIndex({ "castigos.id_recluso": 1, fecha_incidente: -1 });
bd.incidentes.createIndex({ "castigos.sancion.id_sancion": 1 });

// Búsquedas por recluso (la consulta más frecuente)
bd.sentencias.createIndex({ id_recluso: 1, inicio_condena: -1 });
bd.traslados.createIndex({ id_recluso: 1, fecha_traslado: -1 });
bd.contactos_emergencia.createIndex({ id_recluso: 1 });

// Referencias y filtros específicos
bd.ingresos.createIndex({ id_visita: 1 });
bd.decomisos.createIndex({ id_ingreso: 1 });
bd.sentencias.createIndex({ estado: 1 });
bd.sentencias.createIndex({ "delito.id_delito": 1 });
bd.traslados.createIndex({ id_celda_nueva: 1 });

print("Colecciones creadas: " + bd.getCollectionNames().sort().join(", "));
