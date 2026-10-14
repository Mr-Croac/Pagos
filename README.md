# Pagos (con servidor)

Servicio web para dividir gastos en grupo. A diferencia de una página que guarda los datos en el navegador, aquí hay un **servidor con base de datos**: cada grupo tiene un código, y todos los miembros ven las mismas cuentas desde cualquier dispositivo.

## Qué incluye
- API REST en Python (Flask).
- Base de datos SQLite con cuatro tablas: grupos, personas, gastos y reparto.
- Cálculo de saldos y de los pagos mínimos para dejar las cuentas a cero, hecho en el servidor.
- Interfaz web adaptada a móvil que se actualiza sola cada 5 segundos.
- Validación de datos y consultas parametrizadas.

## Cómo ejecutarlo
```bash
pip install -r requirements.txt
python server.py
```
Abre http://localhost:5000, crea un grupo y comparte el código.

## API
| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/groups` | Crea un grupo y devuelve su código |
| GET | `/api/groups/<código>` | Devuelve personas, gastos, saldos y pagos |
| POST | `/api/groups/<código>/people` | Añade una persona |
| POST | `/api/groups/<código>/expenses` | Añade un gasto repartido entre los participantes |
| DELETE | `/api/groups/<código>/expenses/<id>` | Borra un gasto |

## Publicarlo online
GitHub Pages no ejecuta Python, así que necesita un hosting que lo haga (por ejemplo Render, Railway o PythonAnywhere). Comando de arranque: `gunicorn server:app`. Con SQLite hay que usar un disco persistente, o variable `DB_PATH` apuntando a él, para no perder los datos al reiniciar.

## Ideas para ampliarlo
Cuentas de usuario, gastos con importes desiguales, varias monedas, migrar a PostgreSQL.
