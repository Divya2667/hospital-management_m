import os
import logging
from pathlib import Path
import click
from flask import current_app, g
from pymongo import MongoClient, ReturnDocument, ASCENDING
import mongomock

logger = logging.getLogger(__name__)


def get_client():
    """Retrieve or create the MongoDB client for the application."""
    if current_app.config.get("TESTING"):
        if not hasattr(current_app, "_test_mongo_client"):
            current_app._test_mongo_client = mongomock.MongoClient()
        return current_app._test_mongo_client

    if "mongo_client" not in g:
        uri = current_app.config.get("MONGO_URI", "mongodb://localhost:27017/hospital_management")
        if uri.startswith("mongomock://"):
            g.mongo_client = mongomock.MongoClient()
        else:
            g.mongo_client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    return g.mongo_client


def get_db():
    """Get or create the MongoDB database object for the current request context."""
    if "db" not in g:
        client = get_client()
        db_name = current_app.config.get("MONGO_DB_NAME", "hospital_management")
        db = client[db_name]
        g.db = db

        # Auto-initialize and seed dataset on cold-start (e.g., Vercel) if database is brand new
        try:
            if db.users.count_documents({}) == 0:
                init_indexes(db)
                from app.seeder import import_csv_dataset
                try:
                    import_csv_dataset(db)
                except Exception as ex:
                    logger.warning("Dataset auto-seed skipped or failed: %s", ex)
                    from werkzeug.security import generate_password_hash
                    db.users.update_one(
                        {"Username": "admin"},
                        {"$setOnInsert": {
                            "User_ID": 1,
                            "Username": "admin",
                            "Password_Hash": generate_password_hash("Admin@123"),
                            "Role": "Admin",
                            "Full_Name": "System Administrator",
                            "Email": "admin@hospital.local"
                        }},
                        upsert=True
                    )
        except Exception as e:
            logger.warning("Could not auto-verify database state: %s", e)

    return g.db


def close_db(e=None):
    """Clean up request context database references."""
    g.pop("db", None)
    client = g.pop("mongo_client", None)
    if client is not None and current_app.config.get("TESTING"):
        client.close()


def get_next_sequence_value(db, sequence_name):
    """Generate atomic, incrementing integer IDs for entities."""
    doc = db.counters.find_one_and_update(
        {"_id": sequence_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return doc["seq"]


def init_indexes(db):
    """Ensure all required MongoDB indexes and unique constraints exist."""
    db.users.create_index([("Username", ASCENDING)], unique=True)
    db.patients.create_index([("Patient_id", ASCENDING)], unique=True)
    db.doctors.create_index([("Doctor_ID", ASCENDING)], unique=True)
    db.doctors.create_index([("D_Phone", ASCENDING)], unique=True)
    db.appointments.create_index([("Appointment_ID", ASCENDING)], unique=True)
    db.appointments.create_index([
        ("Doctor_ID", ASCENDING),
        ("Appointment_Date", ASCENDING),
        ("Appointment_Time", ASCENDING)
    ])
    db.bills.create_index([("Bill_ID", ASCENDING)], unique=True)


def init_db():
    """Drop existing collections, re-initialize indexes, and create default admin."""
    client = get_client()
    db_name = current_app.config.get("MONGO_DB_NAME", "hospital_management")
    db = client[db_name]

    # Clear existing collections
    for collection_name in ["users", "patients", "doctors", "appointments", "bills", "treatments", "counters"]:
        db[collection_name].drop()

    init_indexes(db)

    # Create default Admin credentials
    from werkzeug.security import generate_password_hash
    db.users.insert_one({
        "User_ID": 1,
        "Username": "admin",
        "Password_Hash": generate_password_hash("Admin@123"),
        "Role": "Admin",
        "Full_Name": "System Administrator",
        "Email": "admin@hospital.local"
    })
    db.counters.update_one({"_id": "User_ID"}, {"$set": {"seq": 1}}, upsert=True)


@click.command("init-db")
def init_db_command():
    """Clear existing collections and initialize MongoDB indexes and default admin."""
    init_db()
    click.echo("Initialized the MongoDB database successfully.")


from flask.cli import with_appcontext


@click.command("load-dataset")
@click.option("--dir", "dataset_dir", default=None, help="Custom path to dataset folder")
@with_appcontext
def load_dataset_command(dataset_dir):
    """Ingest CSV files from dataset/ directory into MongoDB collections."""
    from app.seeder import import_csv_dataset
    db = get_db()
    stats = import_csv_dataset(db, dataset_dir)
    click.echo(
        f"MongoDB dataset loaded successfully: {stats['patients']} patients, "
        f"{stats['doctors']} doctors, {stats['appointments']} appointments, "
        f"{stats['bills']} bills, {stats['treatments']} treatments."
    )


def init_app(app):
    """Register database functions and CLI commands with the Flask application."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(load_dataset_command)
