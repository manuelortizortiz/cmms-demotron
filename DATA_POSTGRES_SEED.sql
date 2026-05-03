-- CMMS DEMOTRON - DATA POSTGRES LISTO PARA COPIAR Y PEGAR
-- Ejecutar en Railway > Postgres > Query

CREATE TABLE IF NOT EXISTS equipos (
  id SERIAL PRIMARY KEY,
  codigo TEXT UNIQUE NOT NULL,
  tipo_equipo TEXT,
  familia TEXT,
  marca TEXT,
  modelo TEXT,
  descripcion TEXT,
  ubicacion TEXT,
  control_base TEXT,
  frecuencia_base DOUBLE PRECISION DEFAULT 0,
  lectura_actual DOUBLE PRECISION DEFAULT 0,
  ultima_pm DOUBLE PRECISION DEFAULT 0,
  proxima_pm DOUBLE PRECISION DEFAULT 0,
  margen DOUBLE PRECISION DEFAULT 0,
  costo_total_pm DOUBLE PRECISION DEFAULT 0,
  estado_operacional TEXT DEFAULT 'OPERATIVO',
  estado_calculado TEXT,
  semaforo TEXT,
  fecha_actualizacion TEXT
);

INSERT INTO equipos
(codigo,tipo_equipo,familia,marca,modelo,descripcion,ubicacion,control_base,frecuencia_base,lectura_actual,ultima_pm,proxima_pm,margen,costo_total_pm,estado_operacional,estado_calculado,semaforo,fecha_actualizacion)
VALUES
('MD-01','Maquinaria Pesada','Excavadora','SANY','SY215C','SANY SY215C','Q-459','HORAS',250,2350,2250,2500,150,1850000,'OPERATIVO','PRÓXIMA','orange',NOW()),
('MD-02','Maquinaria Pesada','Excavadora','CAT','320D','CAT 320D','Faena Norte','HORAS',250,1510,1250,1500,-10,2100000,'OPERATIVO','ATRASADA','red',NOW()),
('CD-100','Camión','Camión Tolva','Mercedes Benz','Actros','Mercedes Benz Actros','Q-459','KM',15000,328900,315000,330000,1100,1250000,'OPERATIVO','PRÓXIMA','orange',NOW()),
('CD-102','Camión','Camión Plano','MAN','40400','MAN 40400','Taltal','KM',15000,302500,300000,315000,12500,980000,'OPERATIVO','AL DÍA','green',NOW()),
('VD-01','Vehículo Liviano','Camioneta','Maxus','T60','Maxus T60','Santiago','KM',10000,94800,90000,100000,5200,350000,'OPERATIVO','AL DÍA','green',NOW()),
('EQP-01','Equipo Planta','Generador','Cummins','C220','Cummins C220','Talca','HORAS',250,980,1000,1250,270,560000,'OPERATIVO','AL DÍA','green',NOW())
ON CONFLICT (codigo) DO UPDATE SET
tipo_equipo=EXCLUDED.tipo_equipo,
familia=EXCLUDED.familia,
marca=EXCLUDED.marca,
modelo=EXCLUDED.modelo,
descripcion=EXCLUDED.descripcion,
ubicacion=EXCLUDED.ubicacion,
control_base=EXCLUDED.control_base,
frecuencia_base=EXCLUDED.frecuencia_base,
lectura_actual=EXCLUDED.lectura_actual,
ultima_pm=EXCLUDED.ultima_pm,
proxima_pm=EXCLUDED.proxima_pm,
margen=EXCLUDED.margen,
costo_total_pm=EXCLUDED.costo_total_pm,
estado_operacional=EXCLUDED.estado_operacional,
estado_calculado=EXCLUDED.estado_calculado,
semaforo=EXCLUDED.semaforo,
fecha_actualizacion=EXCLUDED.fecha_actualizacion;
