"""Pagos: servidor (Flask + SQLite) para dividir gastos en grupo."""
import os
import secrets
import sqlite3

from flask import Flask, g, jsonify, request, send_file

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("DB_PATH", os.path.join(BASE, "pagos.db"))
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I para evitar confusiones

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code TEXT NOT NULL REFERENCES groups(code) ON DELETE CASCADE,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_code TEXT NOT NULL REFERENCES groups(code) ON DELETE CASCADE,
    description TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    payer_id INTEGER NOT NULL REFERENCES people(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS shares (
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    person_id INTEGER NOT NULL REFERENCES people(id),
    amount_cents INTEGER NOT NULL,
    PRIMARY KEY (expense_id, person_id)
);
"""

app = Flask(__name__)


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    with sqlite3.connect(DB) as conn:
        conn.executescript(SCHEMA)


def fail(message, status=400):
    return jsonify(error=message), status


def settle(balances):
    """Empareja al que más debe con al que más le deben: pocos pagos."""
    creditors = [[p, v] for p, v in balances.items() if v > 0]
    debtors = [[p, -v] for p, v in balances.items() if v < 0]
    transfers = []
    while creditors and debtors:
        creditors.sort(key=lambda x: -x[1])
        debtors.sort(key=lambda x: -x[1])
        amount = min(creditors[0][1], debtors[0][1])
        transfers.append({"from": debtors[0][0], "to": creditors[0][0], "amount_cents": amount})
        creditors[0][1] -= amount
        debtors[0][1] -= amount
        if creditors[0][1] == 0:
            creditors.pop(0)
        if debtors[0][1] == 0:
            debtors.pop(0)
    return transfers


def group_state(code):
    conn = db()
    group = conn.execute("SELECT code, name FROM groups WHERE code = ?", (code,)).fetchone()
    if group is None:
        return None
    people = [dict(r) for r in conn.execute(
        "SELECT id, name FROM people WHERE group_code = ? ORDER BY id", (code,))]
    expenses = []
    for row in conn.execute(
            "SELECT id, description, amount_cents, payer_id FROM expenses "
            "WHERE group_code = ? ORDER BY id DESC", (code,)):
        exp = dict(row)
        exp["shares"] = [dict(s) for s in conn.execute(
            "SELECT person_id, amount_cents FROM shares WHERE expense_id = ?", (row["id"],))]
        expenses.append(exp)
    balances = {p["id"]: 0 for p in people}
    for exp in expenses:
        balances[exp["payer_id"]] += exp["amount_cents"]
        for s in exp["shares"]:
            balances[s["person_id"]] -= s["amount_cents"]
    return {"group": dict(group), "people": people, "expenses": expenses,
            "balances": balances, "transfers": settle(balances)}


@app.get("/")
def home():
    return send_file(os.path.join(BASE, "index.html"))


@app.post("/api/groups")
def create_group():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not 1 <= len(name) <= 40:
        return fail("El nombre del grupo debe tener entre 1 y 40 caracteres.")
    conn = db()
    for _ in range(10):
        code = "".join(secrets.choice(ALPHABET) for _ in range(6))
        try:
            conn.execute("INSERT INTO groups (code, name) VALUES (?, ?)", (code, name))
            conn.commit()
            return jsonify(code=code), 201
        except sqlite3.IntegrityError:
            continue
    return fail("No se pudo crear el grupo. Inténtalo de nuevo.", 500)


@app.get("/api/groups/<code>")
def get_group(code):
    state = group_state(code.upper())
    return jsonify(state) if state else fail("Grupo no encontrado.", 404)


@app.post("/api/groups/<code>/people")
def add_person(code):
    code = code.upper()
    conn = db()
    if conn.execute("SELECT 1 FROM groups WHERE code = ?", (code,)).fetchone() is None:
        return fail("Grupo no encontrado.", 404)
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()
    if not 1 <= len(name) <= 24:
        return fail("El nombre debe tener entre 1 y 24 caracteres.")
    if conn.execute("SELECT 1 FROM people WHERE group_code = ? AND lower(name) = lower(?)",
                    (code, name)).fetchone():
        return fail(f"{name} ya está en el grupo.")
    cur = conn.execute("INSERT INTO people (group_code, name) VALUES (?, ?)", (code, name))
    conn.commit()
    return jsonify(id=cur.lastrowid, name=name), 201


@app.post("/api/groups/<code>/expenses")
def add_expense(code):
    code = code.upper()
    conn = db()
    if conn.execute("SELECT 1 FROM groups WHERE code = ?", (code,)).fetchone() is None:
        return fail("Grupo no encontrado.", 404)
    data = request.get_json(silent=True) or {}
    description = str(data.get("description", "")).strip()
    amount = data.get("amount_cents")
    payer = data.get("payer_id")
    participants = data.get("participants")
    if not 1 <= len(description) <= 60:
        return fail("Escribe una descripción de hasta 60 caracteres.")
    if not isinstance(amount, int) or isinstance(amount, bool) or not 0 < amount < 10**9:
        return fail("El importe no es válido.")
    ids = {r["id"] for r in conn.execute("SELECT id FROM people WHERE group_code = ?", (code,))}
    if payer not in ids:
        return fail("Elige quién pagó.")
    if (not isinstance(participants, list) or not participants
            or any(p not in ids for p in participants) or len(set(participants)) != len(participants)):
        return fail("Marca al menos una persona que participe.")
    base, rest = divmod(amount, len(participants))
    cur = conn.execute(
        "INSERT INTO expenses (group_code, description, amount_cents, payer_id) VALUES (?, ?, ?, ?)",
        (code, description, amount, payer))
    for i, person in enumerate(participants):
        conn.execute("INSERT INTO shares (expense_id, person_id, amount_cents) VALUES (?, ?, ?)",
                     (cur.lastrowid, person, base + (1 if i < rest else 0)))
    conn.commit()
    return jsonify(id=cur.lastrowid), 201


@app.delete("/api/groups/<code>/expenses/<int:expense_id>")
def delete_expense(code, expense_id):
    conn = db()
    cur = conn.execute("DELETE FROM expenses WHERE id = ? AND group_code = ?",
                       (expense_id, code.upper()))
    conn.commit()
    return ("", 204) if cur.rowcount else fail("Gasto no encontrado.", 404)


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
