-- PRE-ENTREGA 7 | Modelo relacional del comercio electrónico.
-- Los montos se calculan sobre líneas de pedido, nunca multiplicando el total del pedido
-- por la cantidad de artículos. SQLite en memoria: no se crea ningún archivo .db.
PRAGMA foreign_keys = ON;

CREATE TABLE usuarios (
    usuario_id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL,
    ciudad TEXT NOT NULL,
    fecha_alta TEXT NOT NULL
);

CREATE TABLE pedidos (
    pedido_id INTEGER PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(usuario_id),
    fecha TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('completado', 'cancelado', 'pendiente'))
);

CREATE TABLE detalles_pedido (
    detalle_id INTEGER PRIMARY KEY,
    pedido_id INTEGER NOT NULL REFERENCES pedidos(pedido_id),
    producto TEXT NOT NULL,
    cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario REAL NOT NULL CHECK (precio_unitario >= 0)
);

CREATE INDEX idx_pedidos_usuario_fecha ON pedidos(usuario_id, fecha);
CREATE INDEX idx_detalles_pedido ON detalles_pedido(pedido_id);
